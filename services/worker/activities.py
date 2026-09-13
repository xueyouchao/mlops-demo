"""Temporal activities — the only place external I/O happens.

Activities wrap MLflow registry updates, artifact loads, and Sentry capture.
Keeping side effects here (rather than in the workflow) preserves workflow
determinism: Temporal can safely replay the workflow because only activities
touch the outside world.
"""
from __future__ import annotations

import os

try:
    import sentry_sdk
except Exception:  # sentry optional
    sentry_sdk = None

import mlflow
import mlflow.sklearn
from temporalio import activity
from temporalio.exceptions import ApplicationError
from mlflow.tracking import MlflowClient

from ml_platform.registry_health import artifact_problem

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")

# Fixed so a given hyperparameter set always reproduces the same run — the
# lineage claim only holds if the split and the seed are pinned.
TEST_SIZE = 0.2
RANDOM_STATE = 42


def _client() -> MlflowClient:
    return MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)


def _capture(exc: Exception):
    if sentry_sdk:
        sentry_sdk.capture_exception(exc)


@activity.defn
def promote_stage(payload: dict) -> dict:
    """Approve + transition a version to Production in the MLflow registry.

    Archives whatever was in Production before: MLflow otherwise happily leaves
    several versions marked Production at once, which makes "what is live?"
    ambiguous for every reader — including the console's read model.
    """
    version = int(payload["version_id"])
    name = payload["model_name"]
    # Last line of defence for the invariant "nothing unservable goes live": the
    # api refuses this too, but a workflow can also be signalled directly (the
    # Temporal UI, a script), and this activity is the only writer to the registry.
    problem = artifact_problem(MLFLOW_TRACKING_URI, name, str(version))
    if problem:
        raise ApplicationError(
            f"refusing to promote version {version}: {problem}", non_retryable=True
        )
    try:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        _client().transition_model_version_stage(
            name, version, "Production", archive_existing_versions=True
        )
        return {"version": version, "stage": "Production"}
    except Exception as e:
        _capture(e)
        raise


@activity.defn
def rollback_stage(payload: dict) -> dict:
    """Blue-green flip: send traffic back to a prior version."""
    name = payload["model_name"]
    version = int(payload["version_id"])
    try:
        _client().transition_model_version_stage(name, version, "Production")
        return {"version": version, "stage": "Production", "rolled_back": True}
    except Exception as e:
        _capture(e)
        raise


@activity.defn
def train_and_register(payload: dict) -> dict:
    """Train a candidate model from operator-supplied hyperparameters.

    This is the retrain path behind the console's Train button. It produces a
    *new* registered version staged to Staging — never edits an existing one,
    because ModelVersion is immutable by design. Reaching Production is still a
    separate human-gated promotion.

    Retries are limited: a bad hyperparameter set will not fix itself, so the
    workflow asks for at most two attempts to absorb a transient MLflow hiccup.
    """
    name = payload["model_name"]
    n_estimators = int(payload["n_estimators"])
    max_depth = int(payload["max_depth"])
    learning_rate = float(payload["learning_rate"])
    requested_by = payload.get("requested_by", "system")

    try:
        from sklearn.datasets import load_breast_cancer
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.metrics import accuracy_score, roc_auc_score
        from sklearn.model_selection import train_test_split

        data = load_breast_cancer()
        X, y = data.data, data.target
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
        )

        model = GradientBoostingClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            random_state=RANDOM_STATE,
        )
        model.fit(X_train, y_train)

        acc = float(accuracy_score(y_test, model.predict(X_test)))
        auc = float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))

        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment(name)
        with mlflow.start_run(run_name=f"retrain-{requested_by}") as run:
            mlflow.log_param("n_estimators", n_estimators)
            mlflow.log_param("max_depth", max_depth)
            mlflow.log_param("learning_rate", learning_rate)
            mlflow.log_param("random_state", RANDOM_STATE)
            mlflow.log_param("test_size", TEST_SIZE)
            mlflow.log_param("requested_by", requested_by)
            mlflow.log_param("dataset", "breast_cancer_wisconsin")
            mlflow.log_param("data_hash", _data_hash(X, y))
            mlflow.log_metric("accuracy", acc)
            mlflow.log_metric("roc_auc", auc)
            mlflow.sklearn.log_model(model, artifact_path="model")

            info = mlflow.register_model(
                model_uri=f"runs:/{run.info.run_id}/model", name=name
            )
            _client().transition_model_version_stage(name, int(info.version), "Staging")

            return {
                "version": str(info.version),
                "run_id": run.info.run_id,
                "stage": "Staging",
                "accuracy": round(acc, 4),
                "roc_auc": round(auc, 4),
                "features": int(X.shape[1]),
                "params": {
                    "n_estimators": n_estimators,
                    "max_depth": max_depth,
                    "learning_rate": learning_rate,
                },
            }
    except Exception as e:
        _capture(e)
        raise


def _data_hash(X, y) -> str:
    """Content hash of the training data — the lineage anchor for the run."""
    import hashlib
    import numpy as np

    return hashlib.sha256(
        np.ascontiguousarray(X).tobytes() + np.ascontiguousarray(y).tobytes()
    ).hexdigest()[:16]

"""Train a model on Breast Cancer Wisconsin and register it in the MLflow registry.

This is the *front* of the lifecycle: produce a run, register a version, and
auto-stage it. Promotion to Production is a separate, human-gated Temporal step.
"""
from __future__ import annotations

import os

import joblib
import mlflow
import numpy as np
import mlflow.sklearn
from sklearn.datasets import load_breast_cancer
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
MODEL_NAME = os.getenv("MODEL_NAME", "breast-cancer-classifier")


def main() -> None:
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment("breast-cancer-classifier")

    data = load_breast_cancer()
    X, y = data.data, data.target
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    with mlflow.start_run(run_name="gbt-baseline") as run:
        model = GradientBoostingClassifier(
            n_estimators=120, max_depth=3, learning_rate=0.08, random_state=42
        )
        model.fit(X_train, y_train)

        acc = accuracy_score(y_test, model.predict(X_test))
        auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])

        mlflow.log_param("n_estimators", 120)
        mlflow.log_param("max_depth", 3)
        mlflow.log_param("learning_rate", 0.08)
        # This script trains one family and offers no selector — the console panel and
        # the agent's `train_candidate` tool are where a family is chosen. It still
        # *names* the family it trained, because the console's version table reads it
        # back from the run: a version that says nothing shows as a dash, and "which
        # estimator made this?" is a question the registry should answer on its own.
        mlflow.log_param("model_kind", "gradient_boosting")
        mlflow.log_param("dataset", "breast_cancer_wisconsin")
        mlflow.log_param("data_hash", _data_hash(X, y))
        mlflow.log_metric("accuracy", acc)
        mlflow.log_metric("roc_auc", auc)
        mlflow.sklearn.log_model(model, artifact_path="model")

        # Register a version AND auto-stage it. Human gate happens later.
        model_info = mlflow.register_model(
            model_uri=f"runs:/{run.info.run_id}/model",
            name=MODEL_NAME,
        )
        client = mlflow.tracking.MlflowClient(MLFLOW_TRACKING_URI)
        client.transition_model_version_stage(
            name=MODEL_NAME,
            version=model_info.version,
            stage="Staging",
        )

        print(f"Registered {MODEL_NAME} version {model_info.version} "
              f"(run {run.info.run_id}) | acc={acc:.3f} auc={auc:.3f}")
        print(f"Now promote via the UI /api (human approval gate) to reach Production.")


def _data_hash(X: np.ndarray, y: np.ndarray) -> str:
    import hashlib
    return hashlib.sha256(np.ascontiguousarray(X).tobytes() + np.ascontiguousarray(y).tobytes()).hexdigest()[:16]


if __name__ == "__main__":
    main()

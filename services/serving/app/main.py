"""Serving service — weight-based canary / blue-green router with Sentry.

Forwards a prediction request to a model version according to a routing policy,
captures the routing decision + prediction in Sentry, and supports canary
weight adjustments and blue-green rollback by re-pointing the router.

Routing state is owned here and synced from the api lifecycle facade via the
internal management endpoints (guarded by an internal service token).

Inference is real: the routed version's artifact is loaded from the MLflow
registry and cached per version, so promoting a retrained version genuinely
changes what this endpoint returns.
"""
from __future__ import annotations

import logging
import os
import random

import mlflow
import mlflow.sklearn
import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException
from sklearn.datasets import load_breast_cancer

from ml_platform.context_serving import routing as rt

log = logging.getLogger("mlops-demo.serving")

SENTRY_DSN = os.getenv("SENTRY_DSN", "")
sentry_sdk = None
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(dsn=SENTRY_DSN, environment=os.getenv("SENTRY_ENV", "development"))

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")

INTERNAL_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "change-me-internal")

app = FastAPI(title="mlops-demo — Model Serving Router", version="0.1.0")

_policy = rt.RoutingPolicy("breast-cancer-classifier")

# Loaded artifacts, keyed by version id. Loading is ~seconds, so caching per
# version keeps /v1/predict fast; a newly promoted version simply misses once.
_MODELS: dict[str, object] = {}

# The training data defines the expected input width (30 for this dataset).
_DATASET = load_breast_cancer()
FEATURE_COUNT = int(_DATASET.data.shape[1])


def _capture(exc: Exception) -> None:
    if sentry_sdk is not None:
        sentry_sdk.capture_exception(exc)


def _tag_model_context(version_id: str) -> None:
    """Put the model identity on the Sentry scope for this request.

    An event that reports only "inference failed" cannot be triaged without
    knowing which version, and the version is exactly what varies here.
    """
    if sentry_sdk is not None:
        sentry_sdk.set_tag("model_name", _policy.model_name)
        sentry_sdk.set_tag("model_version", version_id)


def _require_internal(x_internal_token: str = Header(default="")) -> None:
    if not x_internal_token or x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(403, "forbidden")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/v1/predict")
def predict(features: list[float]):
    if not _policy.weights:
        raise HTTPException(400, "no routing policy configured")
    if len(features) != FEATURE_COUNT:
        raise HTTPException(
            422, f"expected {FEATURE_COUNT} features for this model, got {len(features)}"
        )
    target = _pick_version(_policy.weights)
    _tag_model_context(target)
    model = _load_model(target)
    row = np.asarray([features], dtype=float)
    try:
        label = model.predict(row)
        proba = model.predict_proba(row)
    except Exception as e:
        # Log locally as well as reporting: an error that only exists in Sentry
        # leaves whoever is reading `docker logs` with nothing to go on.
        _capture(e)
        log.warning("inference failed for version %s", target, exc_info=True)
        raise HTTPException(500, f"inference failed for version {target}")
    return {
        "model_version": target,
        "predictions": [int(label[0])],
        "probability_malignant": round(float(proba[0][1]), 4),
        "routing": _policy.weights,
    }


@app.get("/v1/sample")
def sample():
    """One real feature row, so a caller can demo a prediction without typing 30 numbers."""
    row = _DATASET.data[0]
    return {
        "features": [round(float(x), 4) for x in row],
        "feature_names": list(_DATASET.feature_names),
        "expected_label": int(_DATASET.target[0]),
    }


@app.get("/v1/routing")
def routing():
    return {
        "model_name": _policy.model_name,
        "weights": _policy.weights,
        "production": _policy.production_version,
    }


# ---- internal management (called by the api lifecycle facade) ---------------
@app.post("/v1/routing", dependencies=[Depends(_require_internal)])
def set_routing(body: dict):
    _policy.set_weights(dict(body["weights"]))
    return _policy.weights


@app.post("/v1/rollback", dependencies=[Depends(_require_internal)])
def do_rollback(body: dict):
    _policy.rollback_to(body["version_id"])
    return _policy.weights


def _pick_version(weights: dict[str, int]) -> str:
    versions = list(weights.keys())
    probs = [weights[v] / 100.0 for v in versions]
    return random.choices(versions, weights=probs, k=1)[0]


def _load_model(version_id: str):
    """Load (and cache) the routed version's artifact from the MLflow registry.

    Loads the concrete sklearn estimator rather than the pyfunc wrapper: pyfunc
    gives us predict() only, and we want predict_proba too. That is safe here
    because the worker and this service pin the same scikit-learn version.
    """
    cached = _MODELS.get(version_id)
    if cached is not None:
        return cached
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    uri = f"models:/{_policy.model_name}/{version_id}"
    try:
        cached = mlflow.sklearn.load_model(uri)
    except Exception as e:
        _capture(e)
        log.warning("could not load %s from the MLflow registry", uri, exc_info=True)
        raise HTTPException(
            503, f"model version {version_id} is not loadable from the registry"
        )
    _MODELS[version_id] = cached
    return cached

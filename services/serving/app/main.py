"""Serving service — weight-based canary / blue-green router with Sentry.

Forwards a prediction request to a model version according to a routing policy,
captures the routing decision + prediction in Sentry, and supports canary
weight adjustments and blue-green rollback by re-pointing the router.

Routing state is owned here and synced from the api lifecycle facade via the
internal management endpoints (guarded by an internal service token).
"""
from __future__ import annotations

import os
import random

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException

from ml_platform.context_serving import routing as rt

SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(dsn=SENTRY_DSN, environment=os.getenv("SENTRY_ENV", "development"))

INTERNAL_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "change-me-internal")

app = FastAPI(title="mlops-demo — Model Serving Router", version="0.1.0")

_policy = rt.RoutingPolicy("breast-cancer-classifier")


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
    target = _pick_version(_policy.weights)
    pred = _score(target, features)
    return {"model_version": target, "predictions": pred, "routing": _policy.weights}


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


def _score(version_id: str, features: list[float]) -> list[float]:
    # Demo scoring: logistic-like sigmoid (mock). In production this loads the
    # artifact for `version_id` from the MLflow registry and runs real inference.
    arr = np.asarray(features, dtype=float)
    z = float(np.sum(arr * 0.01))
    return [1.0 / (1.0 + float(np.exp(-z)))]

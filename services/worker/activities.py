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
from temporalio import activity
from mlflow.tracking import MlflowClient

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")


def _client() -> MlflowClient:
    return MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)


def _capture(exc: Exception):
    if sentry_sdk:
        sentry_sdk.capture_exception(exc)


@activity.defn
def promote_stage(payload: dict) -> dict:
    """Approve + transition a version to Production in the MLflow registry."""
    version = int(payload["version_id"])
    name = payload["model_name"]
    try:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        _client().transition_model_version_stage(name, version, "Production")
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

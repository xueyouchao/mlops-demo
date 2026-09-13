"""API service entrypoint — auth + lifecycle facade.

A thin operations facade: it authenticates, exposes the current lifecycle /
registry / routing state, and triggers the gated actions. The heavy domain
work lives in the shared DDD package and in the Temporal worker / server.
"""
from __future__ import annotations

import os

import sentry_sdk
from fastapi import FastAPI

from . import security
from .config import get_settings

_settings = get_settings()

if _settings.sentry_dsn:
    sentry_sdk.init(
        dsn=_settings.sentry_dsn,
        environment=_settings.sentry_env,
        traces_sample_rate=0.25,
    )

app = FastAPI(title="mlops-demo — Model Lifecycle Platform API", version="0.1.0")

security.seed_users()
app.include_router(security.router)


@app.on_event("startup")
def _init_lifecycle():
    from .state import state
    from .temporal_port import TemporalLifecyclePort
    from .registry_sync import sync_from_registry
    state.ensure_lifecycle(TemporalLifecyclePort())
    # The aggregates are in-memory only, so re-build the read model from MLflow
    # (the registry of record) or every restart starts with an empty console.
    sync_from_registry()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


from . import routes  # noqa: E402

app.include_router(routes.router)

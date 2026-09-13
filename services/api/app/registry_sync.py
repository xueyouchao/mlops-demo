"""Re-build the in-memory lifecycle read model from MLflow.

`state.py` holds the DDD aggregates in memory and MLflow is the registry of
record, so the read model has to be rehydrated from MLflow — otherwise a
redeploy silently empties the console while MLflow still reports a Production
version (which is exactly what happened: the aggregates are not persisted, and
nothing ever read MLflow back).

The sync is additive and best-effort: it never overwrites a version the running
process already knows about, and an unreachable MLflow degrades the console to
in-memory state rather than failing the request.
"""
from __future__ import annotations

import logging

from mlflow.tracking import MlflowClient

from ml_platform.context_modelregistry.events import Stage

from .config import get_settings
from .serving_client import sync_routing
from .state import state

log = logging.getLogger("mlops-demo.api")

# MLflow reports stages as strings; map them onto our Stage enum.
_STAGE_BY_MLFLOW = {
    "production": Stage.PRODUCTION,
    "staging": Stage.STAGING,
    "archived": Stage.ARCHIVED,
    "none": Stage.NONE,
}


def _records() -> list[tuple[str, str, str, Stage]]:
    """Read the model's versions from MLflow, oldest first."""
    client = MlflowClient(tracking_uri=get_settings().mlflow_tracking_uri)
    versions = client.search_model_versions(f"name='{state.model.name}'")
    records = [
        (
            str(mv.version),
            mv.run_id or "",
            mv.source or "",
            _STAGE_BY_MLFLOW.get((mv.current_stage or "none").strip().lower(), Stage.NONE),
        )
        for mv in versions
    ]
    records.sort(key=lambda r: int(r[0]) if r[0].isdigit() else 0)
    return records


def sync_from_registry() -> int:
    """Adopt any MLflow versions the read model is missing. Returns the count.

    Called on startup (the documented back-fill) and on console reads, so a
    trainer run against a live stack shows up without restarting the api.
    """
    try:
        records = _records()
    except Exception:
        log.warning("MLflow registry sync failed; serving in-memory state only", exc_info=True)
        return 0
    if not records:
        return 0

    added = state.model.sync_from_registry(records)
    _ensure_routing()
    if added:
        log.info("hydrated %d version(s) from MLflow: %s", len(added), ", ".join(added))
    return len(added)


def _ensure_routing() -> None:
    """Bootstrap the routing policy and keep the serving router in step with it.

    The policy is derived state that lives in two places (here and in the
    serving process), so it is reconciled on every sync rather than pushed once
    at startup. A one-shot push is not enough: serving may still be starting, and
    the push is best-effort, which would leave the router permanently empty.
    """
    if not state.routing.weights:
        live = state.model.production_version
        if live is None:
            return
        state.routing.promote_to(live.version_id)
    sync_routing(state.routing_weights())

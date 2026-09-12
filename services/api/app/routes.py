"""API routes — read lifecycle state + trigger the gated actions (promote/rollback)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ml_platform.context_lifecycle import orchestrator as orch

from . import security
from .security import require_role
from .serving_client import sync_rollback, sync_routing
from .state import state

router = APIRouter(prefix="/api/models", tags=["models"])


def _lc() -> orch.ModelLifecycle:
    if state.lifecycle is None:
        raise HTTPException(500, "lifecycle not initialised")
    return state.lifecycle


@router.get("")
def list_models(user=Depends(security.get_current_user)):
    return {"model_name": state.model.name, "versions": state.versions()}


@router.get("/routing")
def get_routing(user=Depends(security.get_current_user)):
    return {
        "model_name": state.routing.model_name,
        "weights": state.routing_weights(),
        "production": state.routing.production_version,
        "canary": state.routing.canary_versions,
    }


@router.get("/events")
def get_events(user=Depends(security.get_current_user)):
    return {"events": state.events()}


@router.post("/{version_id}/register")
def register(version_id: str, run_id: str, artifact_uri: str = "",
             user=Depends(require_role("operator", "admin"))):
    _lc().register_and_stage(version_id, run_id, artifact_uri, actor=user["username"])
    return {"ok": True, "version_id": version_id, "stage": "staging"}


@router.post("/{version_id}/promote")
def promote(version_id: str, user=Depends(require_role("operator", "admin"))):
    """Start promotion through the human-approval gate (Temporal workflow)."""
    wf = _lc().request_production_promotion(version_id, actor=user["username"])
    return {"ok": True, "version_id": version_id, "workflow_id": wf, "awaiting_approval": True}


@router.post("/{version_id}/approve")
def approve(version_id: str, workflow_id: str | None = None,
            user=Depends(require_role("operator", "admin"))):
    """The operator's approve button — resumes the Temporal workflow with identity."""
    # Send the human approval signal into the durable workflow, then confirm.
    if workflow_id and state.port is not None:
        state.port.send_approval_signal(workflow_id, True, user["username"])
    _lc().confirm_approval(version_id, workflow_id or "wf-demo", approved_by=user["username"])
    sync_routing(state.routing_weights())
    return {"ok": True, "version_id": version_id, "stage": "production", "approved_by": user["username"]}


@router.post("/rollback")
def rollback(to_version_id: str, user=Depends(require_role("operator", "admin"))):
    _lc().rollback(to_version_id, actor=user["username"])
    sync_rollback(to_version_id)
    return {"ok": True, "rolled_back_to": to_version_id}

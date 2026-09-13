"""API routes — read lifecycle state + trigger the gated actions (promote/rollback)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ml_platform.context_lifecycle import orchestrator as orch
from ml_platform.registry_health import artifact_problem

from . import security
from .config import get_settings
from .security import require_role
from .registry_sync import sync_from_registry
from .serving_client import sync_rollback, sync_routing
from .state import state
from .temporal_port import PromotionAlreadyPending

router = APIRouter(prefix="/api/models", tags=["models"])


class TrainRequest(BaseModel):
    """Operator-supplied hyperparameters for a retrain.

    Bounds are deliberately generous but finite: they keep an accidental
    n_estimators=10**9 from occupying the worker's activity slot forever.
    """

    n_estimators: int = Field(default=120, ge=10, le=1000)
    max_depth: int = Field(default=3, ge=1, le=10)
    learning_rate: float = Field(default=0.08, gt=0.0, le=1.0)


def _assert_servable(version_id: str) -> None:
    """Refuse to move a version toward Production if it cannot actually serve.

    Promotion is what points live traffic at a version, so a version whose
    artifact is missing has to be rejected here — not discovered as a 503 on the
    first prediction. That is exactly how a version with a destroyed artifact
    once reached Production and took the router down with it.
    """
    problem = artifact_problem(
        get_settings().mlflow_tracking_uri, state.model.name, version_id
    )
    if problem:
        raise HTTPException(409, f"version {version_id} cannot be promoted: {problem}")


def _lc() -> orch.ModelLifecycle:
    if state.lifecycle is None:
        raise HTTPException(500, "lifecycle not initialised")
    return state.lifecycle


@router.get("")
def list_models(user=Depends(security.get_current_user)):
    sync_from_registry()  # keep the read model aligned with the MLflow registry
    return {"model_name": state.model.name, "versions": state.versions()}


@router.get("/routing")
def get_routing(user=Depends(security.get_current_user)):
    sync_from_registry()  # bootstraps routing on the first read after a restart
    return {
        "model_name": state.routing.model_name,
        "weights": state.routing_weights(),
        "production": state.routing.production_version,
        "canary": state.routing.canary_versions,
    }


@router.get("/events")
def get_events(user=Depends(security.get_current_user)):
    return {"events": state.events()}


@router.post("/train")
def train(req: TrainRequest, user=Depends(require_role("operator", "admin"))):
    """Retrain from the console: durable TrainingWorkflow -> a new Staging version.

    Declared before the /{version_id}/... routes so the literal path wins. Only
    the pipeline is automated — the new version serves no traffic until a human
    promotes it through the existing approval gate.
    """
    if state.port is None:
        raise HTTPException(500, "lifecycle not initialised")
    wf = state.port.start_training({
        "model_name": state.model.name,
        "n_estimators": req.n_estimators,
        "max_depth": req.max_depth,
        "learning_rate": req.learning_rate,
        "requested_by": user["username"],
    })
    return {"ok": True, "workflow_id": wf, "status": "RUNNING"}


@router.get("/train/{workflow_id}")
def train_status(workflow_id: str, user=Depends(security.get_current_user)):
    """Poll a training run; on completion adopt the new version into the read model."""
    if state.port is None:
        raise HTTPException(500, "lifecycle not initialised")
    info = state.port.training_status(workflow_id)
    if info.get("status") == "COMPLETED":
        sync_from_registry()
    return info


@router.post("/{version_id}/register")
def register(version_id: str, run_id: str, artifact_uri: str = "",
             user=Depends(require_role("operator", "admin"))):
    _lc().register_and_stage(version_id, run_id, artifact_uri, actor=user["username"])
    return {"ok": True, "version_id": version_id, "stage": "staging"}


@router.post("/{version_id}/promote")
def promote(version_id: str, user=Depends(require_role("operator", "admin"))):
    """Start promotion through the human-approval gate (Temporal workflow)."""
    _assert_servable(version_id)
    try:
        wf = _lc().request_production_promotion(version_id, actor=user["username"])
    except PromotionAlreadyPending:
        raise HTTPException(
            409, f"a promotion for version {version_id} is already in progress"
        )
    return {"ok": True, "version_id": version_id, "workflow_id": wf, "awaiting_approval": True}


@router.post("/{version_id}/approve")
def approve(version_id: str, workflow_id: str | None = None,
            user=Depends(require_role("operator", "admin"))):
    """The operator's approve button — resumes the Temporal workflow with identity."""
    # Re-check servability at the moment of approval, not just at promote time:
    # the artifact can disappear in between (a container recreate used to delete
    # every artifact), and approving is what makes a version live.
    _assert_servable(version_id)
    # Send the human approval signal into the durable workflow, then confirm.
    # A signal that cannot be delivered must not be swallowed: we would move
    # MLflow to Production while the durable workflow is still waiting, and the
    # caller would get an unhandled 500 (which is how this reached Sentry).
    if workflow_id and state.port is not None:
        try:
            state.port.send_approval_signal(workflow_id, True, user["username"])
        except Exception:
            raise HTTPException(502, f"could not signal workflow '{workflow_id}'")
    _lc().confirm_approval(version_id, workflow_id or "wf-demo", approved_by=user["username"])
    sync_routing(state.routing_weights())
    return {"ok": True, "version_id": version_id, "stage": "production", "approved_by": user["username"]}


@router.post("/rollback")
def rollback(to_version_id: str, user=Depends(require_role("operator", "admin"))):
    _lc().rollback(to_version_id, actor=user["username"])
    sync_rollback(to_version_id)
    return {"ok": True, "rolled_back_to": to_version_id}

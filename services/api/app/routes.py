"""API routes — read lifecycle state + trigger the gated actions (promote/rollback)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ml_platform import model_kinds
from ml_platform.context_lifecycle import orchestrator as orch
from ml_platform.registry_health import artifact_problem

from . import security
from .config import get_settings
from .security import require_role
from .registry_sync import stage_version, sync_from_registry
from .serving_client import sync_rollback, sync_routing
from .state import state
from .temporal_port import PromotionAlreadyPending

router = APIRouter(prefix="/api/models", tags=["models"])

# The trainer's pre-kind wire shape: gradient boosting's parameters, sent as three
# top-level numbers. These three names *are* `model_kinds.param_names(DEFAULT_KIND)`
# — that is why the flat form still means what it meant — and they are spelled out
# because a pydantic model needs its field names literally. If the shared module
# ever renamed one, `resolve_request` would hand the spec a name it does not have
# and `coerce` would refuse the call *by name*, which is the loud version of this
# drift rather than a silent retrain with a different estimator.
_LEGACY_KNOBS = ("n_estimators", "max_depth", "learning_rate")


class TrainRequest(BaseModel):
    """A retrain request, in either of the trainer's two shapes.

    **The shape the console sends now:** `model_kind` plus that kind's `params` —
    the same shape the agent's `train_candidate` tool and the `train_and_register`
    activity take. The panel offers the family because a human could not name one
    before; it is one trainer either way.

    **The shape it used to send, which must keep working:** the three top-level
    knobs, gradient boosting's parameters. They are kept, typed exactly as
    before, and they merge into `params` — so a caller that posts
    `{"n_estimators": 150}` still trains what it always trained. A knob *not* sent
    is absent rather than a default overwriting anything, which is what makes the
    two shapes agree: `{"model_kind": "gradient_boosting", "params": {...}}` and
    the flat three-knob form resolve to the same validated parameters.

    Bounds and defaults are **not** restated here. They live in
    `ml_platform.model_kinds` — the one module that owns the kinds, which the
    worker trains and validates with — and `resolved()` enforces them, so an
    out-of-range knob or an unknown kind is one 4xx written in that module's own
    words instead of a second, drifting set of rules. (The old
    `n_estimators=10**9` protection survives unchanged: the bound it hit is the
    same one, now enforced in the one place that declares it.)
    """

    model_kind: str = Field(default=model_kinds.DEFAULT_KIND)
    params: dict[str, Any] | None = None
    n_estimators: int | None = None
    max_depth: int | None = None
    learning_rate: float | None = None

    def resolved(self) -> tuple[str, dict | None, str | None]:
        """The (kind, params) this request means, or why it cannot be trained."""
        return model_kinds.resolve_request(
            self.model_kind,
            self.params,
            {name: getattr(self, name) for name in _LEGACY_KNOBS},
        )


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


@router.get("/kinds")
def kinds(user=Depends(security.get_current_user)):
    """The estimator kinds the trainer accepts, with each kind's parameters.

    Read straight out of `ml_platform.model_kinds` — the module the worker builds
    and validates with and this api refuses a bad `TrainRequest` with — so the
    console's Train panel can be *generated* from it. That is what keeps the panel
    honest: it cannot offer a family the trainer does not have, a bound the trainer
    does not enforce, or a default the trainer would override.
    """
    return model_kinds.catalog()


@router.post("/train")
def train(req: TrainRequest, user=Depends(require_role("operator", "admin"))):
    """Retrain from the console: durable TrainingWorkflow -> a new Staging version.

    Declared before the /{version_id}/... routes so the literal path wins. Only
    the pipeline is automated — the new version serves no traffic until a human
    promotes it through the existing approval gate.

    The family is the operator's choice now, and the parameters are that family's.
    Validation happens *here*, against the trainer's own definitions, because a
    kind the trainer does not have is a typo the operator can correct on this
    screen — not a workflow that fails five seconds later with the same sentence
    buried in an activity error. The activity re-checks regardless: the agent
    reaches the same trainer without passing through this route.
    """
    if state.port is None:
        raise HTTPException(500, "lifecycle not initialised")
    kind, params, problem = req.resolved()
    if problem:
        raise HTTPException(400, problem)
    wf = state.port.start_training({
        "model_name": state.model.name,
        "model_kind": kind,
        "params": params,
        "requested_by": user["username"],
    })
    # Echo what was actually started: the panel shows it, and a caller that sent
    # the flat three-knob shape can see the kind and parameters it resolved to.
    return {"ok": True, "workflow_id": wf, "status": "RUNNING",
            "model_kind": kind, "params": params}


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
def approve(version_id: str, workflow_id: str | None = None, approved: bool = True,
            user=Depends(require_role("operator", "admin"))):
    """The operator's decision — approve resumes the workflow, decline ends it.

    Both are decisions, and both have to reach the durable workflow: a decline
    that only changed a screen would leave the workflow waiting for an answer
    that has already been given, and would leave the agent run waiting with it.
    """
    # Servability is re-checked at the moment of approval, not just at promote
    # time: the artifact can disappear in between (a container recreate used to
    # delete every artifact), and approving is what makes a version live. A
    # decline moves nothing, so it does not need the version to be promotable.
    if approved:
        _assert_servable(version_id)
    # A signal that cannot be delivered must not be swallowed: we would move
    # MLflow to Production while the durable workflow is still waiting, and the
    # caller would get an unhandled 500 (which is how this reached Sentry).
    if workflow_id and state.port is not None:
        try:
            state.port.send_approval_signal(workflow_id, approved, user["username"])
        except Exception:
            raise HTTPException(502, f"could not signal workflow '{workflow_id}'")
    if not approved:
        return {"ok": True, "version_id": version_id, "approved": False,
                "declined_by": user["username"]}
    _lc().confirm_approval(version_id, workflow_id or "wf-demo", approved_by=user["username"])
    sync_routing(state.routing_weights())
    return {"ok": True, "version_id": version_id, "stage": "production", "approved_by": user["username"]}


@router.post("/rollback")
def rollback(to_version_id: str, user=Depends(require_role("operator", "admin"))):
    # A rollback is a promotion towards an older version, so it owes the same
    # check _assert_servable makes on the way up. It was the one path without it,
    # and one click put production on v1, whose artifact is gone — the exact
    # failure _assert_servable's docstring describes, through the other door.
    _assert_servable(to_version_id)
    # The stage has to follow the traffic on this path too: MLflow is the registry
    # of record, and this route moves production with no workflow behind it (unlike
    # promote, whose `promote_stage` activity writes the stage). Without it the
    # displaced version kept wearing Production while serving 0% — the console read
    # back two production rows. Written *before* the move so a registry that
    # refuses leaves traffic where it is rather than half-moved.
    try:
        stage_version(to_version_id)
    except Exception:
        raise HTTPException(
            502, f"could not move version {to_version_id} to Production in the registry"
        )
    _lc().rollback(to_version_id, actor=user["username"])
    sync_rollback(to_version_id)
    return {"ok": True, "rolled_back_to": to_version_id}

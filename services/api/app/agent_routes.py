"""Routes for starting an investigation run.

A run is a durable Temporal workflow — the ReAct loop — so starting one is a
workflow start, the same shape as the promote route: role-gated, and the workflow
id is the handle the console uses from then on.

The goal is free text. Presets live in the console and simply fill this field, so
there is one way to start a run and one thing recorded as its input.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .security import require_role
from .state import state

router = APIRouter(prefix="/api/agent", tags=["agent"])

# The goal becomes part of the workflow input and every prompt, so it is bounded
# like any other input that lands in history.
GOAL_MAX = 500


class RunRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=GOAL_MAX)
    max_steps: int = Field(default=8, ge=1, le=8)


@router.post("/runs")
def start_run(body: RunRequest, user=Depends(require_role("operator", "admin"))):
    """Start an investigation and return its run id."""
    if state.port is None:
        raise HTTPException(503, "Temporal is not reachable, so no run can be started")
    goal = body.goal.strip()
    try:
        run_id = state.port.start_investigation(
            goal, actor=user["username"], max_steps=body.max_steps
        )
    except Exception as e:
        raise HTTPException(502, f"could not start the run: {e}") from e
    return {"ok": True, "run_id": run_id, "status": "RUNNING", "goal": goal}

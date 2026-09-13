"""Routes for the investigation agent: starting a run, and reading one back.

Starting is a workflow start, the same shape as the promote route: role-gated,
with the workflow id as the handle from then on.

Reading is the part that matters for the demo. Both read routes project the run
from the Temporal **server** — status and history — so they keep working while
the worker is dead, which is precisely when the console has to show something.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import agent_read, security
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


@router.get("/runs")
def list_runs(user=Depends(security.get_current_user)):
    """Investigations, newest first — read from Temporal, not from the worker."""
    try:
        runs = asyncio.run(agent_read.list_runs())
    except Exception as e:
        raise HTTPException(503, f"Temporal is not reachable: {e}") from e
    return {"runs": runs, "source": "temporal-history"}


@router.get("/runs/{run_id}")
def get_run(run_id: str, user=Depends(security.get_current_user)):
    """One investigation, projected from its own event history.

    Works with the worker stopped, mid-step, or dead: history is on the Temporal
    service, and a query — which the worker would have to answer — is never used.
    """
    try:
        return asyncio.run(agent_read.load_run(run_id))
    except agent_read.RunNotFound:
        raise HTTPException(404, f"no investigation run {run_id}")
    except Exception as e:
        raise HTTPException(503, f"Temporal is not reachable: {e}") from e

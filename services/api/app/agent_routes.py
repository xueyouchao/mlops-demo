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
from .temporal_port import temporal_client

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
        # Say what failed. A bug in the projection used to surface here as
        # "Temporal is not reachable", which sent me looking at the wrong service.
        raise HTTPException(503, f"could not read run {run_id}: {e}") from e


async def _abandon(run_id: str, actor: str) -> dict:
    """Abandon a run — and withdraw the promotion it filed.

    Abandoning decides the *run*; approve and decline decide the *promotion*, so
    they are different actions on different objects (T07). But the promotion
    cannot simply be left behind: one pending promotion per model means an
    orphan would block every later proposal for ever, and nothing would be
    waiting on it any more. So it is terminated rather than approved or
    declined — nobody decided anything, and the record should not pretend
    otherwise.
    """
    run = await agent_read.load_run(run_id)  # raises RunNotFound
    client = await temporal_client()
    withdrawn = None

    promotion = run.get("promotion") or {}
    if promotion.get("workflow_id") and not promotion.get("outcome"):
        handle = client.get_workflow_handle(promotion["workflow_id"])
        try:
            desc = await handle.describe()
            if desc.status.name == "RUNNING":
                await handle.terminate(
                    reason=f"withdrawn by {actor}: the run that asked was abandoned"
                )
                withdrawn = promotion["workflow_id"]
        except Exception:
            pass  # already gone, or never startable: nothing left to withdraw

    handle = client.get_workflow_handle(run_id)
    desc = await handle.describe()
    if desc.status.name != "RUNNING":
        return {"ok": True, "run_id": run_id, "run_status": desc.status.name,
                "withdrawn_promotion": withdrawn, "note": "the run had already finished"}
    await handle.terminate(reason=f"abandoned by {actor}")
    return {"ok": True, "run_id": run_id, "run_status": "TERMINATED",
            "withdrawn_promotion": withdrawn}


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, user=Depends(require_role("operator", "admin"))):
    """Abandon a run. The only escape from an operator who never decides."""
    try:
        return asyncio.run(_abandon(run_id, user["username"]))
    except agent_read.RunNotFound:
        raise HTTPException(404, f"no investigation run {run_id}")
    except Exception as e:
        raise HTTPException(502, f"could not abandon the run: {e}") from e

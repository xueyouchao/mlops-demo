"""TemporalLifecyclePort — adapts the domain's lifecycle port to Temporal.

The domain orchestrator (context_lifecycle) calls these methods to durably
execute promotion. `start_promotion` starts a PromotionWorkflow (by name — the
worker deserializes the dict into its own PromotionWfInput dataclass) that waits
on an approval signal; the approve route separately sends that signal and then
calls `confirm_approval`, whose `wait_for_approval` here returns True (the real
durable wait happens in Temporal, not synchronously in the API).
"""
from __future__ import annotations

import asyncio
import uuid

from temporalio.client import Client as TemporalClient
from temporalio.exceptions import WorkflowAlreadyStartedError

from ml_platform.context_lifecycle import orchestrator as orch
from ml_platform.context_modelregistry import events as ev

from .config import get_settings

TASK_QUEUE = "ml-lifecycle"


class PromotionAlreadyPending(RuntimeError):
    """A promotion for this version already has an active workflow.

    Surfaced instead of Temporal's raw AlreadyStarted error so the console can
    say something useful when Promote is clicked twice.
    """


def _settings():
    return get_settings()


async def _client() -> TemporalClient:
    return await TemporalClient.connect(f"{_settings().temporal_host}:{_settings().temporal_port}")


class TemporalLifecyclePort(orch.LifecyclePort):
    def start_promotion(self, event: ev.PromotionApprovalRequested) -> str:
        return asyncio.run(self._start(event))

    async def _start(self, event: ev.PromotionApprovalRequested) -> str:
        client = await _client()
        try:
            handle = await client.start_workflow(
                "PromotionWorkflow",
                {
                    "version_id": event.version_id,
                    "model_name": event.model_name,
                    "requested_by": event.actor,
                },
                id=f"promote-{event.model_name}-{event.version_id}",
                task_queue=TASK_QUEUE,
            )
        except WorkflowAlreadyStartedError as exc:
            raise PromotionAlreadyPending(
                f"promote-{event.model_name}-{event.version_id}"
            ) from exc
        return handle.id

    def wait_for_approval(self, workflow_id: str) -> bool:
        # The real durable wait is Temporal's job; the route sends the signal
        # out-of-band before confirming. We optimistically report approved.
        return True

    def send_approval_signal(self, workflow_id: str, approved: bool, by: str) -> None:
        asyncio.run(self._signal(workflow_id, approved, by))

    async def _signal(self, workflow_id: str, approved: bool, by: str) -> None:
        client = await _client()
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal("approval_signal", {"approved": approved, "by": by})

    # ---- training (the console's "adjust and retrain" path) ------------------
    def start_training(self, params: dict) -> str:
        return asyncio.run(self._start_training(params))

    async def _start_training(self, params: dict) -> str:
        """Start a TrainingWorkflow. Training is repeatable, so the workflow id
        is unique per request — unlike promotion, where the deterministic id
        doubles as a guard against duplicate promotions of one version."""
        client = await _client()
        handle = await client.start_workflow(
            "TrainingWorkflow",
            params,
            id=f"train-{params['model_name']}-{uuid.uuid4().hex[:8]}",
            task_queue=TASK_QUEUE,
        )
        return handle.id

    def training_status(self, workflow_id: str) -> dict:
        return asyncio.run(self._training_status(workflow_id))

    async def _training_status(self, workflow_id: str) -> dict:
        client = await _client()
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
        status = desc.status.name if desc.status is not None else "UNKNOWN"
        info: dict = {"workflow_id": workflow_id, "status": status, "result": None}
        if status == "COMPLETED":
            info["result"] = await handle.result()
        elif status == "FAILED":
            try:
                await handle.result()
            except Exception as e:  # surface why, instead of a bare FAILED
                info["error"] = str(e).splitlines()[0][:300]
        return info

    # ---- the investigation agent --------------------------------------------
    def start_investigation(self, goal: str, actor: str, max_steps: int = 8) -> str:
        return asyncio.run(self._start_investigation(goal, actor, max_steps))

    async def _start_investigation(self, goal: str, actor: str, max_steps: int) -> str:
        """Start an InvestigationWorkflow — the ReAct loop — and return its run id.

        The id is `agent-<hex>` and that prefix *is* the addressability contract:
        the run's transcript is its own event history, so the workflow id is how
        the console reads it back, and how it finds runs to list. A unique id per
        run, unlike promotion's deterministic one, because starting two
        investigations is not a duplicate — it is two investigations.
        """
        client = await _client()
        handle = await client.start_workflow(
            "InvestigationWorkflow",
            {"goal": goal, "requested_by": actor, "max_steps": max_steps},
            id=f"agent-{uuid.uuid4().hex[:8]}",
            task_queue=TASK_QUEUE,
        )
        return handle.id

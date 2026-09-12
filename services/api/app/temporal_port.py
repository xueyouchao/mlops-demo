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

from temporalio.client import Client as TemporalClient

from ml_platform.context_lifecycle import orchestrator as orch
from ml_platform.context_modelregistry import events as ev

from .config import get_settings

TASK_QUEUE = "ml-lifecycle"


def _settings():
    return get_settings()


async def _client() -> TemporalClient:
    return await TemporalClient.connect(f"{_settings().temporal_host}:{_settings().temporal_port}")


class TemporalLifecyclePort(orch.LifecyclePort):
    def start_promotion(self, event: ev.PromotionApprovalRequested) -> str:
        return asyncio.run(self._start(event))

    async def _start(self, event: ev.PromotionApprovalRequested) -> str:
        client = await _client()
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

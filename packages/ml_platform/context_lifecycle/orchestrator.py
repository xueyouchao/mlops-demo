"""Lifecycle bounded context.

This is the durable-orchestration boundary. The *policy* of the lifecycle lives
here; the *durable execution* of promotion (waiting on the human approval
signal) is implemented in the Temporal worker via this port/interface.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..context_modelregistry import events as ev
from ..context_modelregistry import model as mr
from ..context_serving import routing as rt


class LifecyclePort:
    """Port implemented by the Temporal worker (concrete adapter).

    The domain orchestrator calls these; the durable execution (retries,
    waiting on the approval signal, restart-on-crash) is Temporal's job.
    """

    def start_promotion(self, event: ev.PromotionApprovalRequested) -> str:
        raise NotImplementedError

    def wait_for_approval(self, workflow_id: str) -> bool:
        raise NotImplementedError


@dataclass
class ModelLifecycle:
    """Application service orchestrating the lifecycle across contexts."""

    registry: mr.Model
    routing: rt.RoutingPolicy
    port: LifecyclePort
    event_sink: list[ev.DomainEvent]

    def register_and_stage(self, version_id: str, run_id: str, artifact_uri: str, actor: str = "system"):
        v = self.registry.add_version(version_id, run_id, artifact_uri)
        self.event_sink.append(ev.ModelPromotedToStaging(
            version_id=version_id, model_name=self.registry.name, actor=actor,
        ))
        return v

    def request_production_promotion(self, version_id: str, actor: str = "system"):
        """Enter the staging->production human-approval gate."""
        _ = self.registry._versions[version_id]
        workflow_id = self.port.start_promotion(ev.PromotionApprovalRequested(
            version_id=version_id, model_name=self.registry.name, actor=actor,
            workflow_id="",
        ))
        self.event_sink.append(ev.PromotionApprovalRequested(
            version_id=version_id, model_name=self.registry.name,
            workflow_id=workflow_id, actor=actor,
        ))
        return workflow_id

    def confirm_approval(self, version_id: str, workflow_id: str, approved_by: str):
        """Called when the human signal arrives (or the gate is auto-approved)."""
        approved = self.port.wait_for_approval(workflow_id)
        if not approved:
            raise PermissionError("promotion rejected")
        self.registry.promote_to_production(version_id, approved_by=approved_by)
        self.routing.promote_to(version_id)
        self.event_sink.append(ev.ModelPromotedToProduction(
            version_id=version_id, model_name=self.registry.name,
            workflow_id=workflow_id, approved_by=approved_by,
        ))

    def rollback(self, to_version_id: str, actor: str = "system"):
        # Read the displaced version *before* the move: `registry.rollback` moves the
        # production pointer itself, so asking afterwards answered with the target,
        # and the audit event could never name what it displaced — the console
        # prints these events verbatim, so it printed the same id on both sides.
        displaced = self.registry.production_version
        self.registry.rollback(to_version_id)
        self.routing.rollback_to(to_version_id)
        self.event_sink.append(ev.ModelRolledBack(
            version_id=to_version_id, model_name=self.registry.name,
            previous_version_id=displaced.version_id if displaced else "",
            actor=actor,
        ))

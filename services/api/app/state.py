"""In-memory state facade for the demo.

In a production build these aggregates would be materialised/queryable through
MLflow (registry) + Postgres (state) + Temporal (execution). For the demo the
DDD aggregates are held in memory and back-filled from MLflow on startup, which
keeps the compose real without inventing a full CQRS read model.
"""
from __future__ import annotations

from ml_platform.context_modelregistry import model as mr
from ml_platform.context_serving import routing as rt
from ml_platform.context_lifecycle import orchestrator as orch
from ml_platform.context_modelregistry import events as ev


class State:
    def __init__(self) -> None:
        self.model = mr.Model("breast-cancer-classifier")
        self.routing = rt.RoutingPolicy("breast-cancer-classifier")
        self.outbox: list[ev.DomainEvent] = []
        self.port: orch.LifecyclePort | None = None
        self.lifecycle: orch.ModelLifecycle | None = None

    def ensure_lifecycle(self, port: orch.LifecyclePort) -> orch.ModelLifecycle:
        if self.lifecycle is None:
            self.port = port
            self.lifecycle = orch.ModelLifecycle(
                registry=self.model, routing=self.routing,
                port=port, event_sink=self.outbox,
            )
        return self.lifecycle

    def events(self) -> list[dict]:
        return [e.__dict__ for e in self.outbox]

    def versions(self) -> list[dict]:
        return [v.__dict__ for v in self.model.versions]

    def routing_weights(self) -> dict[str, int]:
        return self.routing.weights


state = State()

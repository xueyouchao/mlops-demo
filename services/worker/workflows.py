"""Temporal workflows — durable orchestration of the lifecycle.

The star here: the **PromotionWorkflow**. It demonstrates the exact durable
pattern we designed — an imperative workflow that starts, *waits indefinitely
on a human approval signal*, and resumes once the operator clicks "approve" in
the UI. If the worker restarts, Temporal replays from the last checkpoint and
the wait continues — the workflow never loses its place.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@dataclass
class PromotionWfInput:
    version_id: str
    model_name: str
    requested_by: str


@workflow.defn
class PromotionWorkflow:
    """Orchestrate version promotion with a human approval gate.

    Activities are referenced by string name so the workflow sandbox never
    imports the (non-deterministic) activity module that pulls in mlflow.
    """

    def __init__(self) -> None:
        self._approved: bool = False
        self._approved_by: str | None = None

    @workflow.run
    async def run(self, inp: PromotionWfInput) -> dict:
        # Durable wait on a signal — human approval arrives from the ops UI.
        await workflow.wait_condition(lambda: self._approved is True)

        # Approve/register in MLflow registry via an activity (by name).
        await workflow.execute_activity(
            "promote_stage",
            {"version_id": inp.version_id, "model_name": inp.model_name,
             "approved_by": self._approved_by},
            retry_policy=RetryPolicy(maximum_attempts=3),
            start_to_close_timeout=timedelta(seconds=30),
        )
        return {"approved": True, "approved_by": self._approved_by, "version_id": inp.version_id}

    @workflow.signal
    async def approval_signal(self, decision: dict) -> None:
        if decision.get("approved"):
            self._approved = True
            self._approved_by = decision.get("by")


@dataclass
class TrainingWfInput:
    model_name: str
    n_estimators: int
    max_depth: int
    learning_rate: float
    requested_by: str


@workflow.defn
class TrainingWorkflow:
    """Train + register a candidate version from operator-supplied knobs.

    No human gate here on purpose: training only ever lands in Staging, and the
    existing promote/approve gate still guards the step that matters — reaching
    Production. The activity is referenced by string name for the same
    determinism reason as promotion (it pulls in sklearn + mlflow).
    """

    @workflow.run
    async def run(self, inp: TrainingWfInput) -> dict:
        return await workflow.execute_activity(
            "train_and_register",
            {
                "model_name": inp.model_name,
                "n_estimators": inp.n_estimators,
                "max_depth": inp.max_depth,
                "learning_rate": inp.learning_rate,
                "requested_by": inp.requested_by,
            },
            # Deliberately low: training is expensive and a bad hyperparameter
            # set will fail identically on every attempt.
            retry_policy=RetryPolicy(maximum_attempts=2),
            start_to_close_timeout=timedelta(minutes=5),
        )


@workflow.defn
class RollbackWorkflow:
    """Rollback to the previous registered version (blue-green flip)."""

    @workflow.run
    async def run(self, payload: dict) -> dict:
        await workflow.execute_activity(
            "rollback_stage", payload,
            retry_policy=RetryPolicy(maximum_attempts=3),
            start_to_close_timeout=timedelta(seconds=30),
        )
        return {"rolled_back": True}

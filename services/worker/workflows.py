"""Temporal workflows — durable orchestration of the lifecycle.

Two stars. **PromotionWorkflow** demonstrates the durable human gate: an
imperative workflow that starts, *waits indefinitely on an approval signal*, and
resumes once the operator clicks approve. If the worker restarts, Temporal
replays from the last checkpoint and the wait continues — the workflow never
loses its place.

**InvestigationWorkflow** is the agent loop, durable for the same reason and
about to be demonstrated the hard way: kill the worker between steps and the run
resumes with its transcript intact, because the transcript *is* this workflow's
instance state — event history, not a process's memory.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError


@dataclass
class PromotionWfInput:
    version_id: str
    model_name: str
    requested_by: str
    # A proposal carries a *pointer*, not a duplicate of the reasoning: who asked
    # (the agent's run, when it is one), one line of why, and the comparison the
    # operator needs on the approval card. All optional, because a
    # human-initiated promotion from the console sends none of them — and the
    # full transcript stays one click away in the agent run's own history.
    agent_run_id: str = ""
    rationale: str = ""
    candidate_metrics: dict | None = None
    incumbent_metrics: dict | None = None


@workflow.defn
class PromotionWorkflow:
    """Orchestrate version promotion with a human approval gate.

    Activities are referenced by string name so the workflow sandbox never
    imports the (non-deterministic) activity module that pulls in mlflow.
    """

    def __init__(self) -> None:
        self._approved: bool = False
        self._approved_by: str | None = None
        self._declined: bool = False
        self._declined_by: str | None = None

    @workflow.run
    async def run(self, inp: PromotionWfInput) -> dict:
        # Durable wait on a signal — human approval arrives from the ops UI.
        # A decline ends it too: otherwise "decline" would be a button that
        # records nothing and leaves the run waiting for a decision already made.
        await workflow.wait_condition(lambda: self._approved or self._declined)

        if self._declined and not self._approved:
            outcome = {
                "approved": False,
                "declined_by": self._declined_by,
                "version_id": inp.version_id,
                "agent_run_id": inp.agent_run_id,
                "promoted": False,
            }
            await self._tell_the_agent(inp, outcome)
            return outcome

        activity_input = {
            "version_id": inp.version_id,
            "model_name": inp.model_name,
            "approved_by": self._approved_by,
        }
        try:
            await workflow.execute_activity(
                "promote_stage",
                activity_input,
                retry_policy=RetryPolicy(maximum_attempts=3),
                start_to_close_timeout=timedelta(seconds=30),
            )
        except Exception as e:
            # The approval succeeded but the promotion did not. The asking run
            # must record that as a failure rather than being left to assume
            # success — this was the one place the optimistic approval response
            # could have become a false claim inside the transcript.
            await self._tell_the_agent(inp, {
                "approved": True,
                "approved_by": self._approved_by,
                "version_id": inp.version_id,
                "agent_run_id": inp.agent_run_id,
                "promoted": False,
                "failed": str(e).splitlines()[0][:300],
            })
            raise

        outcome = {
            "approved": True,
            "approved_by": self._approved_by,
            "version_id": inp.version_id,
            "agent_run_id": inp.agent_run_id,
            "rationale": inp.rationale,
            "promoted": True,
        }
        await self._tell_the_agent(inp, outcome)
        return outcome

    async def _tell_the_agent(self, inp: PromotionWfInput, outcome: dict) -> None:
        """Tell the run that asked, so it records the *real* outcome.

        The api's approval response only acknowledges the click; the durable
        truth is this workflow's own result. Best-effort on purpose: the asking
        run may already be cancelled or past retention, and the promotion itself
        has happened either way.
        """
        if not inp.agent_run_id:
            return
        try:
            await workflow.get_external_workflow_handle(inp.agent_run_id).signal(
                "promotion_outcome", outcome
            )
        except Exception:
            pass

    @workflow.signal
    async def approval_signal(self, decision: dict) -> None:
        if decision.get("approved"):
            self._approved = True
            self._approved_by = decision.get("by")
        else:
            self._declined = True
            self._declined_by = decision.get("by")


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


# --------------------------------------------------------------------------
# The investigation agent
# --------------------------------------------------------------------------
# The cap counts *brain calls*: one step is one brain call, so steps and brain
# calls are the same unit. An activity retry does not consume a step; a
# malformed decision does, which is how a confused brain terminates itself
# instead of spinning.
AGENT_STEP_CAP = 8

# Work, not wall-clock. The ceiling charges each step its own duration and
# subtracts the operator wait, because elapsed time also grows while the platform
# is *not running* — and charging the agent for a worker outage breaks the demo's
# centrepiece in the most embarrassing possible way: a run about surviving a kill
# would die of the kill. Found exactly that way: a ten-minute outage ended a run
# that had recorded five good steps.
AGENT_WORK_CEILING = timedelta(minutes=6)

# What a single step may charge. Without a cap one enormous step could hide a
# wedged activity entirely; with it, two such steps still exceed the ceiling,
# which keeps the original purpose of the ceiling intact.
AGENT_STEP_CHARGE_MAX = timedelta(minutes=2)

# Checked here rather than in the activity: a pure function of recorded values,
# so it is replay-safe, and it keeps the activity's job to *parsing*.
AGENT_TOOLS = (
    "read_registry", "read_run_metrics", "evaluate_version",
    "train_candidate", "propose_promotion", "conclude",
)

# Per-tool retry and timeout policy: reads and evaluate 3 attempts, train 2,
# propose 1 — never retried, because a verdict must never be retried and a blip
# must be. The framework's default is infinite attempts, so each is explicit.
AGENT_TOOL_POLICY: dict[str, dict] = {
    "read_registry": {"attempts": 3, "start_to_close": timedelta(seconds=60)},
    "read_run_metrics": {"attempts": 3, "start_to_close": timedelta(seconds=60)},
    "evaluate_version": {"attempts": 3, "start_to_close": timedelta(seconds=120)},
    "train_candidate": {"attempts": 2, "start_to_close": timedelta(minutes=5)},
    "propose_promotion": {"attempts": 1, "start_to_close": timedelta(seconds=60)},
    # `conclude` is a pure function of its arguments, so retrying it is free —
    # and it is the step whose loss would cost the run its ending.
    "conclude": {"attempts": 3, "start_to_close": timedelta(seconds=30)},
}

# How long an activity task may sit *scheduled but never started*. Temporal's
# default is unlimited, and an unlimited wait is a hang: a task delivered to a
# worker that dies before acknowledging it is leased to nobody, and nothing
# re-delivers it — no timeout fires, because `start_to_close` only begins once a
# task has started. A kill in that window left a run stalled with the worker back
# and healthy, and it would have stalled for ever.
#
# The bound has to be generous, and getting this wrong is easy: a *short* bound
# turns an outage into a failure. A schedule-to-start timeout counts as an
# attempt, so a 60 s bound plus a brain call's two attempts means a worker that
# is down for two minutes does not stall the run — it kills it, which is the
# opposite of what this demo is about. Ten minutes is longer than any outage the
# demo shows, so being down costs the run nothing but time (the run waits, and
# resumes when a worker returns, which is the story), while a task stranded on a
# dead worker is still re-delivered rather than never.
AGENT_SCHEDULE_TO_START = timedelta(minutes=10)

# Above the brain activity's own 60 s request timeout plus its one retry: this is
# the workflow-side safety net, not where the timeout is actually enforced.
AGENT_BRAIN_TIMEOUT = timedelta(seconds=180)

# How long the run waits on the operator before double-checking the promotion's
# status. The signal is the fast path; this is what stops a promotion that was
# terminated — or that failed before it could tell anyone — from leaving the run
# waiting forever.
AGENT_GATE_POLL = timedelta(seconds=30)


@dataclass
class AgentWfInput:
    goal: str
    requested_by: str = "operator"
    max_steps: int = AGENT_STEP_CAP


@workflow.defn
class InvestigationWorkflow:
    """An investigation: a flat ReAct loop that is durable by construction.

    One step is one brain call → exactly one tool call → one observation. The
    transcript *is* workflow instance state, so it is event history — killing the
    worker between steps loses nothing, and the next step resumes from the
    recorded transcript. The brain is stateless, so nothing else has to survive.

    Every decision derives only from recorded values (the goal and the
    transcript) and the clock is Temporal's `workflow.now()`. That property, not
    the activity boundary, is what makes the killed-worker resume work.
    """

    def __init__(self) -> None:
        self._transcript: list[dict] = []
        self._terminal: dict | None = None
        # The few numbers a proposal has to carry (T05 dec. 2). Kept out of the
        # transcript so the digest stays the transcript's only observation text.
        self._evidence: dict[str, dict] = {}
        self._production: str | None = None
        self._promotion: dict | None = None
        self._outcome: dict | None = None

    @workflow.run
    async def run(self, inp: AgentWfInput) -> dict:
        cap = max(1, min(int(inp.max_steps or AGENT_STEP_CAP), AGENT_STEP_CAP))
        worked = timedelta()
        step_started = workflow.now()
        gate_wait = timedelta()
        last_call: str | None = None
        trainings = 0

        while len(self._transcript) < cap:
            # Charge the step that just finished — its own duration, minus any
            # time spent waiting on the operator, capped. Charging at the top
            # covers every path a step can take, including the ones that only
            # record an observation and continue.
            worked += min(
                max(workflow.now() - step_started - gate_wait, timedelta()),
                AGENT_STEP_CHARGE_MAX,
            )
            step_started = workflow.now()
            gate_wait = timedelta()

            if worked > AGENT_WORK_CEILING:
                self._finish(
                    "budget_exhausted",
                    f"the run used its {AGENT_WORK_CEILING} of work over "
                    f"{len(self._transcript)} of {cap} steps without concluding",
                )
                break

            decision = await workflow.execute_activity(
                "brain_decide",
                {"goal": inp.goal, "transcript": self._transcript},
                start_to_close_timeout=AGENT_BRAIN_TIMEOUT,
                schedule_to_start_timeout=AGENT_SCHEDULE_TO_START,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            if not decision.get("ok"):
                kind = decision.get("kind")
                if kind in ("unreachable", "http_error"):
                    # Nothing is standing in for the brain, so the run fails — and
                    # it fails here rather than burning eight steps pretending to
                    # think.
                    raise ApplicationError(
                        f"the brain could not be reached ({kind}): {decision.get('error')}",
                        non_retryable=True,
                    )
                # A decision that could not be produced is an observation that
                # burns a step, so the next call sees the error and can correct.
                self._append(None, {}, decision.get("rationale", ""),
                             f"no usable decision ({kind}): {decision.get('error')}",
                             decision.get("producer"), ok=False, kind=kind)
                continue

            tool = decision["tool"]
            args = decision.get("arguments") or {}
            rationale = decision.get("rationale", "")

            if tool not in AGENT_TOOLS:
                self._append(tool, args, rationale,
                             f"`{tool}` is not a tool you may call. Available: {', '.join(AGENT_TOOLS)}",
                             decision.get("producer"), ok=False, kind="unknown_tool")
                continue

            # Compared against the last *executed* call: an intervening refusal
            # changed the transcript, so repeating after one is not provably wasted.
            call = tool + ":" + json.dumps(args, sort_keys=True)
            if call == last_call:
                self._finish("no_progress",
                             f"{tool} was called twice in a row with identical arguments, "
                             "so nothing happened in between")
                break
            last_call = call

            payload = dict(args)
            if tool == "train_candidate":
                payload["attempt"] = trainings
                payload["requested_by"] = f"agent:{workflow.info().workflow_id}"
            elif tool == "propose_promotion":
                # Same normalisation tools.py applies (`v6` → `6`), for the same
                # reason: the digests write the prefix and the brain copies it
                # back. Duplicated rather than imported — the workflow module must
                # not pull in the activities' dependencies to get at a one-liner.
                wanted = str(args.get("version") or "").strip().lstrip("vV").strip()
                payload.update({
                    "run_id": workflow.info().workflow_id,
                    "requested_by": f"agent:{workflow.info().workflow_id}",
                    "candidate_metrics": self._evidence.get(wanted),
                    "incumbent_metrics": self._evidence.get(self._production or ""),
                })

            policy = AGENT_TOOL_POLICY[tool]
            result = await workflow.execute_activity(
                tool, payload,
                start_to_close_timeout=policy["start_to_close"],
                schedule_to_start_timeout=AGENT_SCHEDULE_TO_START,
                retry_policy=RetryPolicy(maximum_attempts=policy["attempts"]),
            )

            # A training the idempotency lookup answered with an existing version
            # is not a second training, so it does not spend the second slot.
            if tool == "train_candidate" and result.get("ok") and not result.get("resumed"):
                trainings += 1

            self._append(tool, args, rationale, result.get("digest", ""),
                         decision.get("producer"), ok=bool(result.get("ok")),
                         kind=result.get("kind", "ok"))
            self._absorb(tool, result)

            if tool == "conclude" and result.get("ok"):
                self._finish("concluded", result.get("answer", ""),
                             answer=result.get("answer", ""), evidence=result.get("evidence", ""))
                break

            if tool == "propose_promotion" and result.get("ok"):
                # The arc is not over: the run stays alive while the operator
                # decides, and its ending records what was decided.
                self._promotion = {"workflow_id": result["workflow_id"],
                                   "version": result.get("version", "")}
                waited_from = workflow.now()
                self._outcome = await self._await_operator(result["workflow_id"])
                gate_wait = workflow.now() - waited_from
                self._promotion["outcome"] = self._outcome
                if self._outcome.get("promoted"):
                    self._finish("concluded", f"the operator approved v{self._promotion['version']}")
                elif self._outcome.get("approved") is False:
                    self._finish("concluded", f"the operator declined v{self._promotion['version']}")
                else:
                    self._finish("failed", "the promotion did not complete: "
                                 f"{self._outcome.get('failed') or self._outcome.get('status')}")
                break
        else:
            self._finish("budget_exhausted",
                         f"the run used all {cap} steps without concluding")

        if self._terminal is None:  # unreachable, but never return without an ending
            self._finish("budget_exhausted", "the loop ended without a terminal entry")
        return {
            "goal": inp.goal,
            "requested_by": inp.requested_by,
            "steps": len(self._transcript),
            "terminal": self._terminal,
            "transcript": self._transcript,
        }

    async def _await_operator(self, workflow_id: str) -> dict:
        """Wait for the promotion's own outcome, and record that — not the click.

        The fast path is the signal `PromotionWorkflow` sends when it finishes.
        The poll underneath exists because a promotion can also be terminated, or
        fail before it can tell anyone, and then a pure signal wait would leave
        this run waiting for an approval that can never arrive.
        """
        while self._outcome is None:
            try:
                await workflow.wait_condition(lambda: self._outcome is not None,
                                              timeout=AGENT_GATE_POLL)
            except asyncio.TimeoutError:
                state = await workflow.execute_activity(
                    "promotion_outcome", {"workflow_id": workflow_id},
                    start_to_close_timeout=timedelta(seconds=30),
                    schedule_to_start_timeout=AGENT_SCHEDULE_TO_START,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                if state.get("status") != "RUNNING":
                    # A completed promotion carries its result nested; a failed,
                    # terminated or vanished one carries only the status, and that
                    # status *is* the outcome the run has to record.
                    return state.get("outcome") or state
        return self._outcome

    @workflow.signal
    async def promotion_outcome(self, outcome: dict) -> None:
        self._outcome = outcome

    # ---- transcript ------------------------------------------------------
    def _append(self, tool, arguments, rationale, observation, producer,
                ok: bool = True, kind: str = "ok") -> None:
        """One typed entry. The rationale is recorded; raw `thinking` never is."""
        self._transcript.append({
            "step": len(self._transcript) + 1,
            "at": workflow.now().isoformat(),
            "tool": tool,
            "arguments": arguments,
            "rationale": rationale or "",
            "observation": observation or "",
            "producer": producer or "model",
            "ok": bool(ok),
            "kind": kind,
        })

    def _absorb(self, tool: str, result: dict) -> None:
        """Keep the two numbers a proposal needs."""
        if not result.get("ok"):
            return
        if tool == "read_registry":
            for v in result.get("versions") or []:
                if v.get("stage") == "Production":
                    self._production = str(v["version"])
        elif tool == "evaluate_version":
            self._evidence[str(result.get("version"))] = result.get("metrics") or {}

    def _finish(self, reason: str, detail: str, **extra) -> None:
        self._terminal = {
            "reason": reason,
            "detail": detail,
            "at": workflow.now().isoformat(),
            "steps": len(self._transcript),
            "promotion": self._promotion,
            **extra,
        }

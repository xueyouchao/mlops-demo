"""Project an investigation run from Temporal's own history.

The console reads runs from the Temporal **server** — `describe` for the status,
`fetch_history` for the steps — and never through a query. That is not a style
preference: a query is answered by the *worker*, so it fails in exactly the
window this demo is built around. History lives on the service, so the whole
transcript is readable while the worker is dead, which is the demo's climax.

Two things worth knowing while reading this:

- **Nothing here needs the worker.** A run frozen by a killed worker, or one
  that died mid-step, projects fully from history.
- **The projection reads history, not the loop's result.** So it also shows
  what the loop's own transcript omits: a decision the workflow refused to
  execute, the decision that triggered a `no_progress` ending, and a step that
  is in flight *right now* (marked `pending` — this is what the panel renders as
  "deciding…"). Both readings are true; the console shows history.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from temporalio.api.enums.v1 import EventType, RetryState

from .temporal_port import temporal_client

AGENT_RUN_PREFIX = "agent-"
BRAIN_ACTIVITY = "brain_decide"

# Loop plumbing that is not a step: it is never offered to the brain, so it can
# never be part of the transcript.
PLUMBING = ("promotion_outcome",)

# The six tools, named here because the projection has to say *why* a decision
# produced no observation, and "the workflow refused this name" is not
# distinguishable from "the run stopped here" without knowing the allow-list.
TOOL_ACTIVITIES = (
    "read_registry", "read_run_metrics", "evaluate_version",
    "train_candidate", "propose_promotion", "conclude",
)

# How many runs the list endpoint projects. Each one costs a history fetch, and a
# history is a few dozen KB — so the list is bounded, not the transcript.
LIST_LIMIT = 10


class RunNotFound(Exception):
    """No such run, or not a run at all."""


def _kind(event) -> str:
    return EventType.Name(event.event_type).replace("EVENT_TYPE_", "")


def _when(event) -> datetime:
    return event.event_time.ToDatetime(tzinfo=timezone.utc)


def _decode(payloads) -> dict | None:
    if not payloads:
        return None
    try:
        return json.loads(payloads[0].data)
    except Exception:
        return None


def _failure_message(attrs) -> str:
    failure = getattr(attrs, "failure", None)
    message = getattr(failure, "message", "") if failure else ""
    return (message or "the activity failed").splitlines()[0][:300]


def _attempt_seconds(attempt_started: dict, attrs, event, acts) -> float:
    """How long this activity attempt actually executed.

    Per *attempt*, not per step span, and that distinction is the whole point: a
    step whose activity was in flight when the worker was killed would otherwise
    count the entire outage as work. An attempt that never finished contributes
    nothing, and its retry contributes only its own honest duration — so the work
    clock survives the very kill the demo performs.

    Loop plumbing is excluded: polling on the human gate is waiting, not working.
    """
    rec = acts.get(attrs.scheduled_event_id)
    if rec is not None and rec["name"] in PLUMBING:
        return 0.0
    begin = attempt_started.get(getattr(attrs, "started_event_id", None))
    if begin is None:
        return 0.0
    return max(0.0, (_when(event) - begin).total_seconds())


def project(run_id: str, status: str, events, now: datetime | None = None) -> dict:
    """History events → the run as the console reads it.

    Pure, so it can be exercised against a real history without a server — which
    is how it was checked against the runs' own results.
    """
    now = now or datetime.now(timezone.utc)
    goal = requested_by = ""
    started_at: datetime | None = None
    result = failure_message = None
    work_seconds = 0.0

    # Activities, keyed by their scheduled event id: one entry per activity task,
    # carrying whichever outcome won (a retried activity has several). Attempt
    # start times are keyed separately, by started event id, so the work clock can
    # be summed per *attempt*.
    acts: dict[int, dict] = {}
    attempt_started: dict[int, datetime] = {}

    for event in events:
        kind = _kind(event)
        if kind == "WORKFLOW_EXECUTION_STARTED":
            started_at = _when(event)
            payload = _decode(event.workflow_execution_started_event_attributes.input.payloads) or {}
            goal = payload.get("goal", "")
            requested_by = payload.get("requested_by", "")
        elif kind == "ACTIVITY_TASK_SCHEDULED":
            a = event.activity_task_scheduled_event_attributes
            acts[event.event_id] = {
                "name": a.activity_type.name,
                "at": _when(event), "started": None, "done": None,
                "result": None, "failed": None,
            }
        elif kind == "ACTIVITY_TASK_STARTED":
            a = event.activity_task_started_event_attributes
            attempt_started[event.event_id] = _when(event)
            rec = acts.get(a.scheduled_event_id)
            if rec is not None:
                rec["started"] = _when(event)
        elif kind == "ACTIVITY_TASK_COMPLETED":
            a = event.activity_task_completed_event_attributes
            rec = acts.get(a.scheduled_event_id)
            if rec is not None:
                rec["done"] = _when(event)
                rec["result"] = _decode(a.result.payloads)
            work_seconds += _attempt_seconds(attempt_started, a, event, acts)
        elif kind in ("ACTIVITY_TASK_FAILED", "ACTIVITY_TASK_TIMED_OUT"):
            a = (event.activity_task_failed_event_attributes if kind.endswith("FAILED")
                 else event.activity_task_timed_out_event_attributes)
            rec = acts.get(a.scheduled_event_id)
            # A failure whose retry state is IN_PROGRESS is not the last word:
            # another attempt is already coming, and the retry is invisible to
            # the transcript by design (T01 dec. 2).
            if rec is not None and a.retry_state != RetryState.RETRY_STATE_IN_PROGRESS:
                rec["done"] = _when(event)
                rec["failed"] = _failure_message(a)
            work_seconds += _attempt_seconds(attempt_started, a, event, acts)
        elif kind == "WORKFLOW_EXECUTION_COMPLETED":
            result = _decode(event.workflow_execution_completed_event_attributes.result.payloads)
        elif kind == "WORKFLOW_EXECUTION_FAILED":
            failure_message = _failure_message(event.workflow_execution_failed_event_attributes)

    # Walk the activities in order, turning each brain call into a step and
    # attaching the tool call it led to. Activity order *is* step order: the loop
    # is one brain call → one tool call → one observation.
    transcript: list[dict] = []
    promotion: dict | None = None

    for rec in (acts[i] for i in sorted(acts)):
        if rec["name"] in PLUMBING:
            continue
        if rec["name"] == BRAIN_ACTIVITY:
            entry = {
                "step": len(transcript) + 1,
                "at": (rec["done"] or rec["started"] or rec["at"]).isoformat(),
                "tool": None, "arguments": {}, "rationale": "", "observation": "",
                "producer": "", "ok": False, "kind": "pending", "pending": True,
            }
            decision = rec["result"]
            if decision:
                entry.update({
                    "pending": False,
                    "tool": decision.get("tool"),
                    "arguments": decision.get("arguments") or {},
                    "rationale": decision.get("rationale", ""),
                    "producer": decision.get("producer", "model"),
                    "ok": bool(decision.get("ok")),
                    "kind": decision.get("kind", "ok"),
                })
                if not decision.get("ok"):
                    entry["observation"] = (
                        f"no usable decision ({decision.get('kind')}): {decision.get('error', '')}"
                    )
            elif rec["failed"]:
                # The run died here — there is no ending to read, but the step
                # that killed it is in history.
                entry.update({"pending": False, "kind": "activity_failed", "observation": rec["failed"]})
            transcript.append(entry)
            continue

        # A tool call: it belongs to the step above it.
        if not transcript:
            continue
        entry = transcript[-1]
        entry["pending"] = False
        if rec["result"] is not None:
            tool_result = rec["result"]
            entry["observation"] = tool_result.get("digest", "")
            entry["ok"] = bool(tool_result.get("ok"))
            entry["kind"] = tool_result.get("kind", "ok")
            if rec["name"] == "propose_promotion" and tool_result.get("ok"):
                promotion = {
                    "workflow_id": tool_result.get("workflow_id", ""),
                    "version": tool_result.get("version", ""),
                    "filed_at": (rec["done"] or rec["at"]).isoformat(),
                    "outcome": None,
                }
            entry["at"] = (rec["done"] or rec["at"]).isoformat()
        elif rec["failed"]:
            entry.update({"observation": rec["failed"], "ok": False, "kind": "activity_failed"})
            entry["at"] = (rec["done"] or rec["at"]).isoformat()
        elif entry.get("tool") and entry["tool"] not in TOOL_ACTIVITIES:
            entry["observation"] = f"`{entry['tool']}` is not a tool the loop may call"
            entry["kind"] = "unknown_tool"
        elif entry.get("tool"):
            # The decision was usable but was never executed: the run stopped on
            # it (a `no_progress` ending, or the ending itself).
            entry["kind"] = "not_executed"

    # The ending: the loop's own terminal entry, or the platform's verdict.
    terminal: dict | None = None
    if result and isinstance(result.get("terminal"), dict):
        terminal = result["terminal"]
        if terminal.get("promotion"):
            # Merged, not replaced: the loop's ending carries the proposal's
            # pointer and its outcome, but only the history knows *when* it was
            # filed — which is what makes the waiting clock measurable at all.
            promotion = {**(promotion or {}), **terminal["promotion"]}
    elif failure_message:
        terminal = {"reason": "failed", "detail": failure_message}

    reason = (terminal or {}).get("reason")
    if status == "RUNNING":
        awaiting = bool(promotion) and not (terminal or {}).get("promotion")
        state = "awaiting-approval" if awaiting else "running"
    elif status == "COMPLETED":
        state = "failed" if reason == "failed" else "concluded"
    else:
        state = {"FAILED": "failed", "CANCELED": "cancelled", "TERMINATED": "terminated"}.get(
            status, status.lower()
        )

    # Two clocks, because they mean different things: time the agent worked, and
    # time it spent waiting for a human. Work is the sum of the activities' own
    # execution — not elapsed time, which also grows while the platform is down,
    # and not step spans, which would swallow an outage landing inside one.
    waiting_seconds = 0.0
    if promotion and promotion.get("filed_at"):
        filed = datetime.fromisoformat(promotion["filed_at"])
        end = now
        if terminal and terminal.get("at"):
            try:
                end = datetime.fromisoformat(terminal["at"])
            except ValueError:
                pass
        waiting_seconds = max(0.0, (end - filed).total_seconds())

    return {
        "run_id": run_id,
        "goal": goal,
        "requested_by": requested_by,
        "status": status,
        "state": state,
        "reason": reason,
        "started_at": started_at.isoformat() if started_at else None,
        "elapsed_seconds": max(0.0, (now - started_at).total_seconds()) if started_at else 0.0,
        "work_seconds": round(work_seconds, 1),
        "waiting_seconds": round(waiting_seconds, 1),
        "steps": transcript,
        "step_count": len([s for s in transcript if not s.get("pending")]),
        "promotion": promotion,
        "terminal": terminal,
        # Said out loud, because it is the claim the panel makes: this did not
        # come from the worker, and would have been readable if the worker were dead.
        "source": "temporal-history",
    }


async def load_run(run_id: str, now: datetime | None = None) -> dict:
    """One run, projected from the server's history."""
    if not run_id.startswith(AGENT_RUN_PREFIX):
        # Not a refusal for its own sake: without this, the endpoint would read
        # the history of *any* workflow in the namespace — a training run, or a
        # promotion awaiting approval — through a route that only claims to serve
        # investigations.
        raise RunNotFound(run_id)
    client = await temporal_client()
    handle = client.get_workflow_handle(run_id)
    try:
        desc = await handle.describe()
    except Exception as e:
        raise RunNotFound(run_id) from e
    history = await handle.fetch_history()
    return project(run_id, desc.status.name, history.events, now=now)


async def list_runs(limit: int = LIST_LIMIT, now: datetime | None = None) -> list[dict]:
    """The runs the console offers, newest first, without their transcripts."""
    client = await temporal_client()
    query = f'WorkflowId STARTS_WITH "{AGENT_RUN_PREFIX}"'
    ids: list[str] = []
    async for w in client.list_workflows(query, page_size=limit):
        ids.append(w.id)
        if len(ids) >= limit:
            break

    async def summary(run_id: str) -> dict | None:
        try:
            return await load_run(run_id, now=now)
        except RunNotFound:
            return None

    projected = await asyncio.gather(*(summary(i) for i in ids))
    runs = [r for r in projected if r]
    return [
        {k: r[k] for k in ("run_id", "goal", "state", "reason", "step_count",
                           "started_at", "elapsed_seconds", "work_seconds",
                           "waiting_seconds", "promotion")}
        for r in runs
    ]

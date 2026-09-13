---
id: B04
title: Project the transcript from Temporal history
labels: [wayfinder:build]
status: closed
assignee: ""
blocked-by: [B01]
---

## Scope

The read path: the API projects a run's transcript from the **Temporal server's** history — never from a query, which needs a live worker and fails in exactly the window the demo needs. Activity events in order, brain and tool activities distinguishable by name or by a marker in the result payload, projected into entries of decision + observation, plus the run's state, its two clocks (work, and waiting on the human) and its terminal reason.

**Done when:** with the worker stopped, the run's endpoint still returns every completed step — that is the demo's climax, so it is the acceptance test.

**Read with:** T04 (transcript store), T06 (clocks and endings), T07 (what the panel then shows).

## Outcome

`services/api/app/agent_read.py` holds the projection — a pure `project(run_id, status, events)` over history events, plus `load_run` / `list_runs` — and the two read routes live in `agent_routes.py`: `GET /api/agent/runs` and `GET /api/agent/runs/{run_id}`. Everything comes from `describe` + `fetch_history` on the Temporal **server**: no query anywhere, because a query is answered by the worker and would fail in precisely the window this exists for.

**The acceptance test, run as written** — worker SIGKILLed mid-run, then the endpoint called over HTTPS:

> `status=RUNNING state=running source=temporal-history`, clocks `work=17.0s`, and steps 1–3 returned in full **plus step 4 marked `PENDING (deciding…)`** — the brain call that was in flight when the worker died.

That pending step is a bonus the ticket did not ask for and the panel needs: history shows an activity that started and never finished, so the dead window renders as "deciding…" rather than as nothing happening. The list endpoint works with the worker dead too.

**Checked against the loops themselves.** Five runs, and for each the projected steps were compared field by field (`tool`, `arguments`, `rationale`, `observation`, `ok`, `kind`) with the transcript the workflow itself returned: **5/5 exact matches**, including the run that survived a kill and the run that went through the approval gate. That is the strongest check available — it is not "the shape looks right", it is "the projection reconstructs what the loop recorded, from history alone".

**The work clock had the same bug as the ceiling, and this is the same lesson twice.** First cut summed each step's *span*, so the pre-fix outage run reported `work=652.4s` — a ten-minute dead window counted as the agent working. It now sums each activity attempt's own execution: that run reports **26.3s**, and an attempt that never finished contributes nothing while its retry contributes only its own honest duration. The waiting clock is separate (13.0s on the run that waited on the operator, with `promoted=true`), and the two are reported independently because "the agent is slow" and "the human has not answered" are different facts.

**Scoped on purpose:** `{run_id}` must start with `agent-`, otherwise the route would read the history of *any* workflow in the namespace — a training run, or a promotion awaiting approval — through an endpoint that only claims to serve investigations. A `train-…` id returns 404.

**What the acceptance test found, and it was worth the ticket on its own: an unlimited `schedule_to_start` is a hang.** The projection made the failure legible — a step that stays `pending` and never resolves — but the cause was in the loop: Temporal's default `schedule_to_start_timeout` is unlimited, so an activity task delivered to a worker that dies before acknowledging it is never re-delivered, and no timeout fires because `start_to_close` only begins once a task has started. A kill landing in that window stalls a run for ever, with the worker back up and healthy. Every earlier kill had resumed only because its activity had already started. Every agent activity now carries an explicit bound; the full reasoning is the third amendment in [Lock the run semantics](T06-lock-the-run-semantics.md), and the demo-script consequences are in [Script the kill and the resume](B06-script-the-kill-and-the-resume.md).

**Not demonstrated live:** the `failed` ending. It is projected from `WORKFLOW_EXECUTION_FAILED` when a run dies without a terminal entry (the brain unreachable, or a promotion that dies after approval), but no run has failed yet, so it is written from the shape of the events rather than from a screenshot.

**One divergence, deliberate and documented in the module:** the projection shows what *history* shows, so it includes a decision the workflow refused to execute, the decision that triggered a `no_progress` ending, and a step still in flight. The loop's own transcript records only the steps it acted on. Both readings are true; the console shows history, and the panel should say so rather than imply the two are the same thing.

**For [Build the console panel](B05-build-the-console-panel.md)** — what the read path returns:

- Run: `{run_id, goal, requested_by, status, state, reason, started_at, elapsed_seconds, work_seconds, waiting_seconds, steps[], step_count, promotion, terminal, source}`.
- `state` is the coarse set (`running` / `awaiting-approval` / `concluded` / `failed` / `cancelled` / `terminated`); `reason` is the loop's precise ending (`concluded` / `budget_exhausted` / `no_progress` / `failed`) and is what should be shown, with `budget_exhausted` and `no_progress` rendered as real endings rather than as errors.
- A step is `{step, at, tool, arguments, rationale, observation, producer, ok, kind, pending}`; `tool` is `null` when the decision never became a call, and `producer` distinguishes the model from the labelled fallback.
- `promotion` is the pointer plus the outcome: `{workflow_id, version, filed_at, outcome}`, where `outcome` is populated only once the operator has decided — so the approval card and the run's ending read from the same object.
- `GET /api/agent/runs/{run_id}` still needs auth: it is a read route, so any signed-in user, same as `/api/models`.

---
id: T06
title: Lock the run semantics
labels: [wayfinder:grilling]
status: closed
assignee: "dsh session"
blocked-by: [T01]
---

## Question

What are the operational rules of a run — what must survive what, how long may it take, and what happens when a piece fails?

Settle:

- **What durability must survive.** The demo moment is a **worker kill mid-investigation**; decide exactly what that must demonstrate (the run resuming from its transcript, not re-calling the brain for steps already done). Then decide the rest deliberately: an API restart, an ollama restart, a Temporal server restart, an MLflow restart. They are different, and only the worker one is required — but the others should be *known*, not discovered live.
- **The step and latency budget.** Host-ollama reasoning models take seconds per call, and a step may include training a candidate (~10–20 s). Decide the step cap and a wall-clock ceiling that keeps the demo watchable, and what the operator sees when the budget runs out.
- **Retry policy.** Activities get retries; decide per tool. A failed `train_candidate` should probably retry once; a refused `propose_promotion` **must not** retry (it is a 409 verdict, not a transient error — the worker already raises `ApplicationError(non_retryable=True)` for this reason).
- **Runaway protection.** The step cap is the main one; decide whether identical consecutive tool calls or a repeating observation should also terminate the run.
- **The scripted fallback.** Decide how the brain activity selects it (ollama unreachable? explicit flag?) and what the transcript says so a viewer can tell the fallback ran instead of the model — the demo must not silently pretend.
- **Where the operator sees run state** — running / awaiting-approval / concluded / failed — and how that maps onto the console's existing polling.

## Prior evidence (from the research branch) — read before choosing the demo's kill point

[Research how production durable-agent frameworks structure their loops](T09-research-durable-agent-loop-patterns.md) closed with findings on a throwaway branch — read with `git show research/durable-agent-loop-patterns:docs/research/durable-agent-loop-patterns.md` (§2, §3, §5). Its most important practical caveat lands squarely on this ticket:

- **The demo has an at-least-once hole.** A worker death re-runs the *in-flight* activity from the top, and a failed attempt's effects are not rolled back (Temporal's own LangGraph integration states this outright). The workflow's position is durable; the tool's side effect is not. Killing during `train_and_register` therefore risks **training twice**. Decide explicitly: kill the worker while the loop is *between* steps (easiest, and honest if narrated), or give the training tool heartbeats and/or idempotency before claiming durability across it.
- **Recovery latency is floored by `start_to_close_timeout`, not by worker restart speed.** The Server cannot detect a dead worker — Start-To-Close is what forces the retry. With `promote_stage` at 30 s, the run can look "stuck" for that long after the worker is already back. Choose the timeout knowing it is also the length of the demo's dead window.
- **Set retry policies explicitly.** The default is infinite attempts with no non-retryable errors — wrong for a tool that shells out to a trainer, and already handled deliberately in `promote_stage`.
- **Name the step unit** (see [Lock the agent loop contract](T01-lock-the-agent-loop-contract.md)), and decide whether the transcript needs a Continue-As-New bound rather than relying on the demo staying short.
- **Narrate it correctly**: "the run resumes where it was and the interrupted activity runs again" — never "nothing runs twice".

## Partly settled by the loop contract

[Lock the agent loop contract](T01-lock-the-agent-loop-contract.md) settled the **step cap and its unit** — the cap counts brain calls and sits at 8, activity retries do not consume it, and a malformed decision does (so a confused brain self-terminates). It also settled the **three endings** (`conclude`, `budget_exhausted`, hard failure) as typed terminal entries. Do not re-decide those here. What remains on this ticket: the wall-clock ceiling, per-tool retry policies, what must survive which restarts, the scripted-fallback selection, and where run state is surfaced.

**Measured input for the budget** (from [Choose the brain model & structured tool-call output](T08-choose-the-brain-model-and-tool-call-output.md), 2026-09-13): the chosen brain returns one decision in **2.9 s p50, 3.1 s worst case** at a realistic ~700-token step-6 prompt, so an 8-step run is roughly **25 s of model time** before any tool time. *(Superseded the same day: the operator's chosen brain is now `deepseek-v4.1-flash:cloud` at **12.9 s p50 / 36.5 s worst** — do not size anything on the 2.9 s figure. See the amendment at the end of this ticket.)* Two requirements come attached: a **generous `num_predict`** (4096 measured — a 512 cap truncated mid-thinking and silently returned no tool call at all), and treating `done_reason == "length"` as a typed `truncated` failure rather than an empty decision.

## Resolution

Grilled one question at a time. Six decisions.

**1. The kill lands between steps, and training is idempotent as a safety net.** The demo action is to watch until an observation is recorded, then stop the worker — a repeatable moment that shows the thing that actually matters: the run resumes with its scratchpad intact and does **not** re-call the brain for steps already done. Because the in-flight window is only ~1–3 s (or ~20 s inside a training call), a mistimed kill is a live risk, so `train_and_register` gains an **idempotency lookup**: it already logs `data_hash` and its hyperparameters, so the activity first checks for an existing version trained on the same data with the same knobs and returns that instead of training again. A mistimed kill then costs a retry, not a duplicate version.

**2. Only the worker kill is a must-have.** The other restarts are recorded as behaviour to *verify*, not to design around: Temporal persists history server-side, so a run survives a Temporal restart; an API restart drops in-memory sessions so the operator logs in again (already true today); an ollama restart costs one failed brain call, which retries; an MLflow restart fails one tool call, which retries. Designing for all five would expand the build well past the destination.

**3. Six minutes of work, measured on the workflow clock, excluding the human gate.** A healthy run is model time plus tool time (training at most twice, ~20 s each), so the ceiling never fires in a good demo — it exists to stop a wedged activity. **The approval wait is excluded**: the gate is a human and unbounded by design, and counting it would kill a run that is correctly waiting on the operator.
  *Amended from three minutes, 2026-09-13 — see the amendment at the end.* The three-minute figure was computed for a brain at 2.9 s per call. The operator then chose `deepseek-v4.1-flash:cloud`, measured at **12.9 s p50 / 36.5 s worst** per call, so eight steps is ~103 s at the median and ~4.9 min at the tail *before* any tool time — three minutes would have ended slow draws as `budget_exhausted` before the agent could file its proposal.
  *Correction carried back to [Lock the agent loop contract](T01-lock-the-agent-loop-contract.md):* the time source is `workflow.now()` / `workflow.time()`, the SDK's deterministic workflow-perspective clock. T01's replay rule said "no `workflow.now()`", which was over-strict — the banned call is `datetime.now()`. Fixed there; the rule now reads *the workflow clock, never the stdlib clock*.

**4. A consecutive identical call terminates the run as `no_progress`.** Same tool, same arguments, twice in a row — provably wasted, since nothing happened in between, so it cannot produce a false positive. Deliberately narrower than banning repeats outright: re-reading the registry *after* a training is legitimate, because the state changed. This is a **fourth terminal reason**, recorded in T01 alongside the other three so the build session sees one list.

**5. The fallback engages automatically and on demand, and always announces itself.** An unreachable ollama engages it automatically, so a mid-demo outage degrades rather than fails; an explicit flag forces it, so the demo can prove the loop works with no model at all. Every fallback decision is **labelled in the transcript** — the map's standing preference is that the demo never silently pretends, so a viewer can always tell which producer decided. It stays a deterministic policy engine (per the map) sharing the brain's output contract (per [Choose the brain model & structured tool-call output](T08-choose-the-brain-model-and-tool-call-output.md)).

**6. Retry counts, per tool** (following [Define the agent's tool surface & schemas](T02-define-the-agent-tool-surface-and-schemas.md) decision 5, where retries apply only to infrastructure failures): **reads and `evaluate_version` 3 attempts, `train_candidate` 2, `propose_promotion` 1 — never retried.** Training is the only expensive call and it is now idempotent, so one retry suffices; a verdict is never retried; cheap reads can afford three attempts because a retry there is invisible to the transcript. The framework default is *infinite* attempts with no non-retryable errors, so every tool states this explicitly — as `promote_stage` already does.

**Run state** is the loop's terminal entry (T01) plus Temporal's own workflow status: running / awaiting-approval / concluded / failed, with `budget_exhausted` and `no_progress` distinguishable from a hard failure.

**Deliberately not adopted: Continue-As-New.** At cap 8 with bounded digests the history is nowhere near the 51,200-event or 50 MB ceilings, so no transcript bound is needed to reach the destination. It stays the sanctioned remedy if runs ever get longer.

## Amendment — 2026-09-13: the ceiling moves from three minutes to six

Six minutes covers the measured worst case with the operator's chosen brain — eight steps × 36.5 s ≈ 4.9 min, plus tool time (one or two trainings at ~20 s) ≈ **5.4 min** — and leaves the step cap of 8 exactly where it was, so one thing changed and not two.

What did **not** change: the ceiling is still measured on the workflow clock, still excludes the approval wait, and the four terminal reasons are untouched. `budget_exhausted` remains a real ending; six minutes is a stop for a wedged activity, not a target to fill.

Recorded because the alternative was worse in a way that matters to this map: leaving three minutes would mean accepting that a slow draw ends the run early — a demo of *durability* failing for a reason that has nothing to do with durability. The latency is a measurement, not an estimate: 5 runs of the step-6 scenario, **5/5 valid tool calls, p50 12.9 s, max 36.5 s** (see the amendment in [Choose the brain model & structured tool-call output](T08-choose-the-brain-model-and-tool-call-output.md)).

**One consequence left deliberately unaddressed:** the brain activity's own timeout stays at 60 s. That is ~1.6× the worst call observed, and a call that overruns it falls back to the scripted policy — a labelled degradation, which is the designed behaviour rather than a failure. Raising the timeout instead would let a single slow call eat a quarter of the run's budget.

## Amendment — 2026-09-13 (second): the ceiling charges *step* time, not elapsed time

Found by the build's own verification, on the first real kill. The worker was SIGKILLed 35 s into a run; the run then sat frozen for **ten minutes** while nothing was running; the worker came back and the run resumed correctly from its five recorded steps — and immediately ended `budget_exhausted`, because the ten-minute outage had been charged to the agent as work.

That is the demo's centrepiece failing *because of* the demo's centrepiece: a run whose whole point is surviving a kill would die of the kill. Worse, it fails in the one place an audience is watching, and it fails only when the outage is long enough — so a rehearsal would have passed and the live demo might not.

**What changed:** the ceiling now charges each step its own duration, capped at two minutes per step, and subtracts the operator wait. Elapsed time is no longer the unit, because elapsed time also grows while the platform is *not running*, and that is not the agent working.

**What that preserves:** the ceiling's stated purpose — stopping a wedged activity. A wedged step charges its two-minute cap rather than vanishing, so two of them still exceed six minutes and end the run. Nothing else moved: still the workflow clock, still the approval wait excluded, still the four terminal reasons.

Also found by the same kill, and worth keeping: the in-flight activity was a `train_candidate`. It had **already registered v7** when the worker died, and the retry returned *"v7 already exists for exactly these hyperparameters and this data — reused, no new version registered."* Decision 1's idempotency lookup is therefore proven under a real SIGKILL rather than a manual double-call, which is the version of that evidence that counts.

## Amendment — 2026-09-13 (third): an unlimited schedule-to-start is a hang

Found by B04's acceptance test, and the most dangerous thing found so far, because its symptom is *nothing at all*. Temporal's default `schedule_to_start_timeout` is **unlimited**, and for an activity task that is delivered to a worker which dies before acknowledging it, nothing re-delivers it: `start_to_close` never begins, so no timeout ever fires, and the task stays leased to nobody.

Observed, not reasoned: a run was killed 8 s after step 4's brain call was *scheduled*, and that run was still stalled minutes later with the worker back up and healthy. It would have stayed stalled for ever. Every other kill tested resumed cleanly, and the reason is now clear — in those, the activity had already **started**, so that activity's own `start_to_close` (180 s for a brain call) rescued it.

This is not a theoretical hole in a demo that kills the worker on purpose: a kill landing in that window turns the climax into a run that never moves again, on stage, with no error to explain it.

**What changed:** every agent activity now carries `schedule_to_start_timeout`, set to **ten minutes**. Verified as written into history on a fresh run. The *rescue itself* was not reproduced, because it needs a kill in the window between a task being scheduled and a worker acknowledging it: it is recorded as a bound that exists, not as a crash survived.

Getting the number right took a correction, and the correction is the interesting part. The first version of this bound was 60 s, on the reasoning that it only had to be longer than any queueing the demo creates. That was wrong in the way that matters most here: **a schedule-to-start timeout counts as a failed attempt**, so a 60 s bound against a brain call's two attempts means a worker that is down for two minutes does not leave the run waiting — it *kills* it. A demo about surviving an outage would have been built on a loop that dies in one. Ten minutes is longer than any outage the demo shows, so being down costs a run nothing but time (it waits, and resumes when a worker returns, which is the story the demo is telling), while a task stranded on a dead worker is still re-delivered rather than never.

Decision 6's retry counts are unchanged, with one addition: `conclude` takes 3 attempts rather than 1. It is a pure function of its arguments, so retrying it is free, and it is the single step whose loss costs the run its ending.


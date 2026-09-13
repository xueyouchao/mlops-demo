---
id: MAP
title: mlops-demo Agent Wayfinder Map
labels: [wayfinder:map]
---

## Destination

A live console demo of a **durable agent** inside the mlops-demo ops console: the operator gives the agent a goal, watches it work the real platform through tools, and approves the promotion it proposes. Reaching the destination means that demo runs end to end in the console — including the durability moment, where the worker is killed mid-investigation and the agent resumes with its scratchpad intact instead of restarting or losing the run.

Pinned by the human during charting: **no** architecture write-up or ADR, **no** eval harness, **no** cost accounting. The demo (and the engineering honesty behind it) is the deliverable.

**Execution is carried into this map** (see Notes): the destination is met when the demo actually runs, not when the decisions are decided.

## Notes

- **Domain**: a demo of an end-to-end ML model lifecycle platform. DDD bounded contexts (`context_modelregistry` / `context_serving` / `context_lifecycle`), Temporal durable orchestration with a human approval gate, MLflow as registry of record, Sentry for errors, and — since this session's work — real training and real inference.
- **Where the agent attaches**: a new Temporal workflow (the loop) plus activities (the tools), an API route pair to start/read an investigation, and a console panel. It reuses the *existing* `PromotionWorkflow` for its proposal, so the approval gate stays exactly as it is.
- **Existing surface to build on** (verified by reading the code, not assumed):
  - Activities: `promote_stage`, `rollback_stage`, `train_and_register` in `services/worker/activities.py`.
  - Workflows: `TrainingWorkflow`, `PromotionWorkflow`, `RollbackWorkflow` in `services/worker/workflows.py`, registered in `services/worker/main.py`.
  - Gate: `POST /api/models/{id}/promote` starts `PromotionWorkflow` (id `promote-<model>-<version>`) which waits for a signal; the console's Approve button sends it. Promotion now refuses a version whose artifact is unreadable (`_assert_servable` → 409) and archives its predecessor.
- **Brain facts** (verified during charting on this host — re-verify if stale): ollama runs on the **host**, reachable from containers at the bridge gateway `172.23.0.1:11434`; `host.docker.internal` is *not* wired up. `deepseek-v4-flash:cloud`, `glm-5.2:cloud`, `kimi-k2.7-code:cloud` and `minimax-m3:cloud` all complete requests with no external credentials. `bge-m3` gives local 1024-dim embeddings. They are **reasoning** models: a response carries both `content` and `thinking`, so a small `num_predict` is consumed entirely by thinking and returns *empty* content — the trap that made the first probe look broken.
- **Tracker conventions**: [wayfinder/TRACKER.md](TRACKER.md). Expect concurrent sessions — claim before work, refer to tickets by name.
- **Skills every session should consult**: `/grilling` + `/domain-modeling` for grilling tickets; `/research` for the research ticket's conventions; `/prototype` for the prototype ticket. When build tickets graduate: `incremental-implementation`, `api-and-interface-design`, `source-driven-development`.
- **Standing preferences (settled by the human during charting)**:
  - **Autonomy boundary**: the agent may diagnose, evaluate versions, train candidates, and *file* promotion requests. It may **not** approve (that stays human) and may **not** roll back production.
  - **Brain**: host ollama by default, behind an activity, with a deterministic scripted-policy fallback so the demo still runs when ollama is down. The loop stays real either way — only the decision-making degrades.
  - **The durability story must be real, not narrated**: the brain call is an activity (so its output is in event history and replay is deterministic), and the transcript is the workflow's own state.
  - **Word the durability claim exactly**, and never overclaim: "the run resumes where it was and the interrupted activity runs again" — *not* "nothing ever runs twice". No first-party source supports the stronger phrasing, and the demo would be asserting something false about its own tool side effects. See [Research how production durable-agent frameworks structure their loops](tickets/T09-research-durable-agent-loop-patterns.md).
- **Execution carried into the map** (pinned by the human): this effort **overrides wayfinder's planning-only default**. The destination is a *running* demo, so the map does not end when the decisions are decided — the destination is met when the demo runs. Once the decision tickets close, build tickets graduate (from fog, or from the resolution of [Prototype the console's agent panel](tickets/T07-prototype-the-console-agent-panel.md)) until the demo runs end to end in the console, including the killed-worker resume.

## Decisions so far

<!-- one line per closed ticket: enough to judge relevance, then zoom the link for detail -->

- [Decide how an investigation starts](tickets/T03-decide-how-an-investigation-starts.md) — a free-text goal with presets filling the same field, fixed as workflow input; an impossible goal is carried by `conclude` rather than a new tool or reason; the existing operator/admin gate applies
- [Decide where the agent transcript lives](tickets/T04-decide-where-the-agent-transcript-lives.md) — read from the Temporal server's history, always: one path that works while the worker is dead, which is what makes the killed-worker moment readable; a query was rejected because it needs a live worker, and no duplicate store is created
- [Lock the run semantics](tickets/T06-lock-the-run-semantics.md) — the demo kills the worker *between* steps and training is made idempotent so a mistimed kill cannot duplicate a version; only the worker kill is a must-have; three minutes of work on the workflow clock, excluding the human-gate wait; a repeated identical call ends the run as `no_progress`; the fallback engages automatically or on demand and every fallback decision is labelled
- [Define the agent's tool surface & schemas](tickets/T02-define-the-agent-tool-surface-and-schemas.md) — exactly six tools, returning bounded digests; `evaluate_version` reuses the trainer's split so candidates are comparable; `propose_promotion` starts the real approval gate after a servability pre-check, so no human is asked about an unreadable artifact; training capped at 2 per run; verdicts return typed envelopes while infrastructure failures raise so retries still apply
- [Choose the brain model & structured tool-call output](tickets/T08-choose-the-brain-model-and-tool-call-output.md) — default brain is `deepseek-v4-flash:cloud` (10/10 valid tool calls, 2.9 s p50, 3× faster than the next); native `tools` works on all eight candidates while `format` is accepted but never enforced; and a tight `num_predict` silently eats the tool call, so the budget must be generous and `done_reason=length` treated as a typed failure
- [Lock the agent loop contract](tickets/T01-lock-the-agent-loop-contract.md) — flat ReAct (one step = one brain call → one tool → one observation); cap 8, retries free; the brain is stateless and the transcript is the memory, recording the rationale but never the raw thinking; bad output becomes an observation that burns a step; three endings, and "no better candidate" is a legitimate result rather than an error
- [Research how production durable-agent frameworks structure their loops](tickets/T09-research-durable-agent-loop-patterns.md) — our shape *is* Temporal's shipped pattern (loop in the workflow, model call as an activity, transcript in workflow state); Temporal ships no step bound, so ours is ours alone to define; and the demo carries an at-least-once hole — a retried activity restarts from the top with its failed attempt unrolled-back, so a kill during training risks training twice

## Not yet specified

<!-- the fog: in-scope, not yet sharp enough to ticket -->

- **Mid-run human steering** — nudging, pausing, or interrupting a running investigation. Sharpen once [Lock the agent loop contract](tickets/T01-lock-the-agent-loop-contract.md) and [Lock the run semantics](tickets/T06-lock-the-run-semantics.md) have settled what the loop can accept mid-flight.
- **How the killed-worker resume is *shown*** — the mechanics of the demo moment itself: what the operator sees in the console while the worker is down and after it returns. The research sharpened this (the read path must work during the outage, which constrains the store — now written into [Decide where the agent transcript lives](tickets/T04-decide-where-the-agent-transcript-lives.md)), but what the panel actually renders during the dead window is still unspecified. Depends on T04 and [Lock the run semantics](tickets/T06-lock-the-run-semantics.md).
- **Concurrent investigations** — two agents at once, or an agent investigating while an operator promotes. Sharpen when [Define the agent's tool surface & schemas](tickets/T02-define-the-agent-tool-surface-and-schemas.md) lands, since the answer is largely about which writes need a claim.
- **Post-demo: multi-agent fan-out** — parallel investigations that compare candidates. The loop contract may make this cheap; it is not needed for the destination.

## Out of scope

- **Semantic recall over the audit trail / lineage** (embeddings via `bge-m3`) — a retrieval subsystem that demonstrates nothing about durability. Ruled out by the human during charting; returns as a fresh effort if wanted.
- **Autonomous rollback of production** — the agent proposing to *undo* a release spends the safety story the destination deliberately keeps.
- **Agent eval harness and token/cost accounting** — excluded by the destination the human pinned.
- **Investigations triggered by external signals** (a Sentry issue, a drift alert) rather than by an operator — the destination is operator-started.
- **Multi-model genericity** — the platform serves one model (`breast-cancer-classifier`); generality is not needed to reach the destination.

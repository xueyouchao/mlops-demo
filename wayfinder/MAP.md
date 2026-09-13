---
id: MAP
title: mlops-demo Agent Wayfinder Map
labels: [wayfinder:map]
---

## Destination

A live console demo of a **durable agent** inside the mlops-demo ops console: the operator gives the agent a goal, watches it work the real platform through tools, and approves the promotion it proposes. Reaching the destination means that demo runs end to end in the console — including the durability moment, where the worker is killed mid-investigation and the agent resumes with its scratchpad intact instead of restarting or losing the run.

Pinned by the human during charting: **no** architecture write-up or ADR, **no** eval harness, **no** cost accounting. The demo (and the engineering honesty behind it) is the deliverable.

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

## Decisions so far

<!-- one line per closed ticket: enough to judge relevance, then zoom the link for detail -->

## Not yet specified

<!-- the fog: in-scope, not yet sharp enough to ticket -->

- **Mid-run human steering** — nudging, pausing, or interrupting a running investigation. Sharpen once [Lock the agent loop contract](tickets/T01-lock-the-agent-loop-contract.md) and [Lock the run semantics](tickets/T06-lock-the-run-semantics.md) have settled what the loop can accept mid-flight.
- **How the killed-worker resume is *shown*** — the mechanics of the demo moment itself: what the operator sees in the console while the worker is down and after it returns. Depends on [Decide where the agent transcript lives](tickets/T04-decide-where-the-agent-transcript-lives.md).
- **Concurrent investigations** — two agents at once, or an agent investigating while an operator promotes. Sharpen when [Define the agent's tool surface & schemas](tickets/T02-define-the-agent-tool-surface-and-schemas.md) lands, since the answer is largely about which writes need a claim.
- **Post-demo: multi-agent fan-out** — parallel investigations that compare candidates. The loop contract may make this cheap; it is not needed for the destination.

## Out of scope

- **Semantic recall over the audit trail / lineage** (embeddings via `bge-m3`) — a retrieval subsystem that demonstrates nothing about durability. Ruled out by the human during charting; returns as a fresh effort if wanted.
- **Autonomous rollback of production** — the agent proposing to *undo* a release spends the safety story the destination deliberately keeps.
- **Agent eval harness and token/cost accounting** — excluded by the destination the human pinned.
- **Investigations triggered by external signals** (a Sentry issue, a drift alert) rather than by an operator — the destination is operator-started.
- **Multi-model genericity** — the platform serves one model (`breast-cancer-classifier`); generality is not needed to reach the destination.

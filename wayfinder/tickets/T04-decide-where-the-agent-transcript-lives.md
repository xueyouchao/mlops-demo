---
id: T04
title: Decide where the agent transcript lives
labels: [wayfinder:grilling]
status: open
assignee: ""
blocked-by: [T01]
---

## Question

Where does each step of an investigation live, and how does the console read it while the run is in flight?

Settle:

- **The store.** Candidates: the existing domain-event outbox (`state.py`'s in-memory `outbox`, which already backs the console's audit panel), a Temporal query over the workflow's transcript state, or a dedicated read model. Weigh each against the one non-negotiable: the transcript must be readable *live* while the worker is running, and must still be readable after a worker restart.
- **Read path.** The console already polls (`refresh()` every few seconds). Decide whether the transcript rides an existing endpoint, a new polling endpoint, or a streaming one — and whether the existing optimistic in-memory pattern in the API is acceptable here.
- **Granularity and volume.** One entry per tool call, per brain thought, or both? The demo's punch is reading the reasoning, but an unbounded transcript in event history has a size cost — decide what is trimmed.
- **Survival across restarts.** The API's read model is in-memory and rehydrates from MLflow on read; a transcript has no such source of truth unless it is deliberately given one. Decide what survives an API restart versus a worker restart — they are different problems and the demo only *requires* the worker one.

Blocks [Prototype the console's agent panel](T07-prototype-the-console-agent-panel.md).

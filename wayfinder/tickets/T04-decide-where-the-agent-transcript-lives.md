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

## Prior evidence (from the research branch) — this adds a third requirement

[Research how production durable-agent frameworks structure their loops](T09-research-durable-agent-loop-patterns.md) closed with findings on a throwaway branch — read with `git show research/durable-agent-loop-patterns:docs/research/durable-agent-loop-patterns.md` (§2, §5). Read that section before weighing the store, because it invalidates the obvious answer:

- **The read path must survive the worker being *dead* — not merely restarting.** A Temporal **query** is answered by the worker, so during the outage the console's poll gets an `RPCError` / `FAILED_PRECONDITION`. That is exactly the window the demo wants to show something in. Two paths do survive: reading **event history from the Temporal Server**, or having activities append to the API's existing **domain-event outbox**.
- **Trimming is a payload-size decision, not an event-count one.** History caps at 51,200 events / 50 MB, warning at 10,240 / 10 MB — but one agent step costs only a handful of events, so at demo scale the binding constraint is **bytes**. Decide which brain fields reach history verbatim, which are digested, and which are dropped. Note the side effect: activity results are visible in the Temporal Web UI, so anything recorded is effectively published.
- **Continue-As-New is the sanctioned remedy** for a growing history, gated on `is_continue_as_new_suggested()` plus `all_handlers_finished()`, and never called from inside a signal or update handler.
- **Signal delivery is unaffected by the outage** — the client does not wait for the signal to be delivered — so starting or steering a run while the worker is dead is safe (relevant to the fog item on mid-run steering).

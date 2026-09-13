---
id: T04
title: Decide where the agent transcript lives
labels: [wayfinder:grilling]
status: closed
assignee: "dsh session"
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

## Partly settled by the loop contract

[Lock the agent loop contract](T01-lock-the-agent-loop-contract.md) fixed the transcript's **shape**: an append-only list of typed entries in workflow instance state, each step recording the brain's short rationale and the tool's observation, with the raw `thinking` field deliberately never recorded (it is large, and activity results are visible in the Temporal Web UI). So the per-field decision above is half-made: reasoning traces are out. What remains here is the **store** (which of the two outage-surviving paths), the **read path**, and any further trimming of tool observations.

## Resolution

**The transcript's source of truth is Temporal history, and the console reads it from the *server* — always.** One code path, and it works whether the worker is up, restarting, or dead.

Why not the obvious alternatives:

- **A Temporal query is rejected outright.** Queries are answered by the worker, so during the outage they return `FAILED_PRECONDITION` — in exactly the window this demo wants to show something.
- **A domain-event outbox write from each activity** would keep the console's current polling shape, but the worker would call the API, the API's memory would become a cache that dies on restart, and the same facts would be recorded twice — once in history, once in the outbox.
- **A dedicated read model** is a new store that duplicates history and can drift from it.

The consequences are worth stating, because they are what the demo is buying:

- **The killed-worker moment is readable by construction.** History lives on the Temporal service, not in the worker, so the console can show every completed step while the worker is dead — which is the demo's climax.
- **An API restart loses nothing.** Today's read model is in-memory and rehydrates from MLflow; the transcript needs no such rescue, because it is not stored there.
- **The existing audit outbox is untouched.** Only the agent transcript comes from Temporal, so nothing is duplicated.

**Read path and shape.** The console keeps its existing polling; the API projects history into transcript entries. Fetching only activity events keeps it cheap, and an 8-step transcript is a few KB — nowhere near the 51,200-event / 50 MB ceilings, which is why [Lock the run semantics](T06-lock-the-run-semantics.md) did not adopt Continue-As-New. The entry shape is the one [Lock the agent loop contract](T01-lock-the-agent-loop-contract.md) fixed: per step, the decision (tool, arguments, rationale) and the observation digest, with the raw `thinking` never recorded. The per-field trimming question that opened this ticket is therefore half-moot — reasoning traces are out by decision, and the remaining observations are already bounded digests by [Define the agent's tool surface & schemas](T02-define-the-agent-tool-surface-and-schemas.md).

**Build note:** the projection walks `ActivityTaskCompleted` events in order, so brain and tool activities must be distinguishable by name or by a marker in the result payload. Decide that when implementing, not here.

**What the console renders during the dead window** is [Prototype the console's agent panel](T07-prototype-the-console-agent-panel.md)'s question; this ticket only guarantees the data is readable then.

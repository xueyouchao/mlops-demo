---
id: T06
title: Lock the run semantics
labels: [wayfinder:grilling]
status: open
assignee: ""
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


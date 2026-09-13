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


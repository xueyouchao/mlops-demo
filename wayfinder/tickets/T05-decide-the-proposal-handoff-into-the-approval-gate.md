---
id: T05
title: Decide the proposal handoff into the approval gate
labels: [wayfinder:grilling]
status: closed
assignee: "dsh session"
blocked-by: [T02]
---

## Question

How does the agent's recommendation become something the operator can *approve* — and what evidence travels with it?

The destination says the operator approves the promotion the agent proposes, so this is the seam where the agent stops and the human starts. Settle:

- **The mechanism.** The agent calls the existing promote path, which starts `PromotionWorkflow` (id `promote-<model>-<version>`) and waits for a signal; the console's Approve button sends it. Confirm that the agent's proposal is exactly this — a *pending* promotion — rather than a separate notion of "proposal" the console would have to learn.
- **The evidence.** What the operator sees before pressing Approve: the candidate version, its metrics against the incumbent (accuracy / ROC AUC on the same split), the hyperparameters, the rationale, and the cost paid to get there. Decide what is mandatory versus nice.
- **The refusal path.** The promote route already returns `409` when a version's artifact is unreadable, and the worker's activity independently refuses it. Decide what the operator (and the agent) sees when the guard fires — and make sure the agent can observe it rather than crashing.
- **Whether the agent may propose more than one candidate** in a run, and what the console does with two pending promotions for the same model.
- **What happens if the operator never approves** — the workflow waits durably; decide whether it expires.

Note the existing quirk this inherits: the API confirms approval optimistically (`wait_for_approval` returns `True`) because the durable wait is Temporal's. Decide whether that is acceptable given the agent now depends on the outcome.

## Partly settled by the tool surface

[Define the agent's tool surface & schemas](T02-define-the-agent-tool-surface-and-schemas.md) settled the **mechanism**: the agent's proposal *is* a real pending `PromotionWorkflow`, started by an activity through the Temporal client on the same `promote-<model>-<version>` id convention, after a servability pre-check that refuses an unreadable artifact before any human is asked. So the seam is fixed and the console needs no new concept of "proposal". What remains here: **what evidence travels with it**, how it is presented, what the operator sees when the guard fires, whether one run may leave two pending promotions for the same model, and what happens if the operator never approves.

## Resolution

Four decisions, one of which was a fork nothing had decided.

**1. The run stays alive while the operator decides, and its ending records the outcome.** [Lock the run semantics](T06-lock-the-run-semantics.md) had already listed `awaiting-approval` as a run state and excluded the human-gate wait from its three-minute ceiling — both only make sense if the run is still alive — but no ticket had actually settled it. Now it is explicit, and the demo's arc closes: goal → investigate → propose → the console shows awaiting-approval → the operator approves → the promotion runs → the run's terminal entry records what was decided. The wait is a durable hold and costs nothing. The decision appears **in the ending, not as a step**, because a step is a brain call ([Lock the agent loop contract](T01-lock-the-agent-loop-contract.md)); inventing one for the human would corrupt the loop's meaning.

**2. A proposal carries a pointer, not a duplicate.** The promotion's input/memo carries the **agent run id**, the candidate version, the incumbent's metrics for comparison on the same split, and a one-line rationale. The full reasoning stays in the transcript — one click away and durable in history ([Decide where the agent transcript lives](T04-decide-where-the-agent-transcript-lives.md)). Mandatory: version, metrics against the incumbent, rationale. Carried because it is nearly free: the cost paid (steps used, trainings run). Nothing is copied, so nothing can drift out of agreement with the transcript.

**3. At most one pending promotion per model.** A second proposal is **refused as an observation** rather than filed, so the console always holds one pending decision per model instead of a queue to triage — and re-running the demo cannot stack up stale pending promotions. The agent adapts to the refusal by concluding on the proposal already filed. Reuses the existing duplicate detection.

**4. The optimistic approval response stays, and the agent does not trust it.** The API's `wait_for_approval` returning `True` acknowledges the decision; the durable truth was never the HTTP response's job. But because the run now depends on the outcome, the agent reads the **real** result from Temporal — the promotion's own workflow outcome — and records that. A promotion that fails *after* approval is therefore recorded as failed rather than reported as success. That was the one place the old quirk could have become a false claim inside the transcript, and it is closed.

**Also settled here:**

- **The refusal path.** Already fixed by [Define the agent's tool surface & schemas](T02-define-the-agent-tool-surface-and-schemas.md): the servability pre-check means an unreadable artifact never reaches a human at all. The operator sees nothing; the agent receives an observation and concludes on it.
- **If the operator never decides.** The run waits, indefinitely and visibly — that is what a durable human gate is. No expiry: a deadline on a human's judgement is a policy nobody asked for. The escape is cancelling the run, and whether the console offers that control is [Prototype the console's agent panel](T07-prototype-the-console-agent-panel.md)'s rendering question.

**Feeds the panel prototype:** the approval card shows the candidate version, its metrics against the incumbent, the rationale and the cost paid, with a way through to the transcript, and it must decide whether the operator can cancel an awaiting run.

---
id: T05
title: Decide the proposal handoff into the approval gate
labels: [wayfinder:grilling]
status: open
assignee: ""
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

---
id: B03
title: Build the six tool activities
labels: [wayfinder:build]
status: closed
assignee: ""
blocked-by: []
---

## Scope

The six tools as activities, per [Define the agent's tool surface & schemas](T02-define-the-agent-tool-surface-and-schemas.md), each returning a **bounded digest** rather than a raw payload: `read_registry` (versions, stages, artifact presence, **and the serving routing**), `read_run_metrics`, `evaluate_version` (reusing the trainer's split — `test_size 0.2`, `random_state 42`), `train_candidate` (reuses `train_and_register`, gains the **idempotency lookup** so a retried kill cannot duplicate a version, capped at 2 per run), `propose_promotion` (servability pre-check first, then starts `PromotionWorkflow` on the existing `promote-<model>-<version>` id convention) and `conclude`.

Expected verdicts return typed envelopes — a guard refusal, an unknown version, an already-pending promotion; infrastructure failures raise so the retry policy applies (reads 3 attempts, train 2, propose 1).

**Done when:** an unreadable artifact is refused as an observation without a human ever being asked, and a mistimed kill during training produces a retry rather than a second version.

**Read with:** T02 (tool surface), T05 (handoff), T06 (retry counts, idempotency).

## Outcome

Built as `services/worker/tools.py` — the six tools as activities, registered on the worker — plus optional proposal fields on `PromotionWfInput`, so a filed promotion carries its pointer rather than a copy of the reasoning.

**Done-when, both verified against the live stack rather than reasoned about:**

- *an unreadable artifact is refused as an observation without a human ever being asked* — `propose_promotion(v1)` returns `artifact_problem` — *"refusing to ask the operator about v1: its artifact directory is missing from the registry. It cannot serve traffic, so there is nothing to decide."* — and **no workflow is started**, so the operator is never handed a decision that cannot work.
- *a mistimed kill during training produces a retry rather than a second version* — `train_candidate` called twice with identical hyperparameters returned **the same v6** with `resumed: true`. The lookup keys on the run's own logged `data_hash` plus the three hyperparameters, which `train_and_register` writes before it registers anything.

The happy path is proven as well: `propose_promotion(v6)` started `promote-breast-cancer-classifier-6`, and its recorded input already carries the pointer the operator's card needs — `agent_run_id`, `rationale`, and `candidate_metrics` beside `incumbent_metrics`.

**Three things found by running it, not by reading it:**

1. **`artifact_problem` collapses "no such version" into "cannot be read."** That is deliberate and correct for a promotion guard, but as a *tool result* it sent the brain hunting a broken registry when it had simply invented a version. Both `evaluate_version` and `propose_promotion` now check existence first and return `unknown_version`.
2. **The one-pending-per-model guard immediately caught a real wedge.** A promotion for v4 had been RUNNING since 03:15 that morning (~14 h, left by earlier UI testing). It could not be approved safely either — v4 is Archived, so approving it would have promoted it over the serving v5 — and while it lived, *no* new proposal could be filed. Terminated, with the reason attached. This is exactly the stale-pending hazard T05 decision 3 exists to prevent, caught before the agent ever ran.
3. **`slice_size` was dropped from `evaluate_version`.** T02 listed it as optional; it would let the agent compare a candidate scored on a smaller slice against an incumbent scored on the full one, quietly destroying the comparability rule (T02 decision 2) that the tool exists to uphold.

**Verified how:** every tool called for real inside the worker container against the live stack — registry, serving router, Temporal. `read_registry` returned all five versions with stages, training accuracy, artifact-MISSING flags and `serving routing v5:100%`; `evaluate_version(v5)` returned **0.9386** on the held-out split, matching the number the training run itself recorded — the comparability claim demonstrated rather than asserted.

**Not covered here:** the workflow that calls these tools (B01) and the console that renders them (B05). The `MAX_TRAININGS_PER_RUN` check in this module is only a last line of defence for a direct call; the run-level counter belongs to the workflow (T06).

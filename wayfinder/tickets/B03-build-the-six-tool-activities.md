---
id: B03
title: Build the six tool activities
labels: [wayfinder:build]
status: open
assignee: ""
blocked-by: []
---

## Scope

The six tools as activities, per [Define the agent's tool surface & schemas](T02-define-the-agent-tool-surface-and-schemas.md), each returning a **bounded digest** rather than a raw payload: `read_registry` (versions, stages, artifact presence, **and the serving routing**), `read_run_metrics`, `evaluate_version` (reusing the trainer's split — `test_size 0.2`, `random_state 42`), `train_candidate` (reuses `train_and_register`, gains the **idempotency lookup** so a retried kill cannot duplicate a version, capped at 2 per run), `propose_promotion` (servability pre-check first, then starts `PromotionWorkflow` on the existing `promote-<model>-<version>` id convention) and `conclude`.

Expected verdicts return typed envelopes — a guard refusal, an unknown version, an already-pending promotion; infrastructure failures raise so the retry policy applies (reads 3 attempts, train 2, propose 1).

**Done when:** an unreadable artifact is refused as an observation without a human ever being asked, and a mistimed kill during training produces a retry rather than a second version.

**Read with:** T02 (tool surface), T05 (handoff), T06 (retry counts, idempotency).

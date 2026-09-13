---
id: T02
title: Define the agent's tool surface & schemas
labels: [wayfinder:grilling]
status: closed
assignee: "dsh session"
blocked-by: [T01]
---

## Question

What is the exact, allow-listed set of tools the agent may call — their names, arguments, and result shapes — and which of them are new code versus reuse of what exists?

The working set to confirm, cut, or extend:

- `read_registry` — versions, stages, metrics, artifact reachability (the read model already hydrates from MLflow via `services/api/app/registry_sync.py`).
- `read_run_metrics` — params/metrics for a run id, from MLflow.
- `evaluate_version` — load a version's artifact and score a held-out slice; must reuse the trainer's split (`TEST_SIZE = 0.2`, `RANDOM_STATE = 42`) so numbers are comparable across versions. Decide the metrics returned.
- `train_candidate` — reuse the existing `train_and_register` activity as-is, or wrap it?
- `propose_promotion` — reuses the existing promote path, so the servability guard and the approval gate both apply.
- `conclude` — terminal; the agent's answer and its evidence.

Also settle:

- **How tool failures reach the brain.** A refused promotion returns `409 version N cannot be promoted: its artifact directory is missing from the registry` — the agent must *observe* that as a result and adapt, not crash the run. Same for a `409 already in progress`.
- **Cost and blast radius of each tool.** `train_candidate` registers a version and occupies the worker's single activity slot (`max_workers` is effectively 4); decide whether the agent is trusted with it unbounded.
- **What the tools may read but never write** — the boundary is already fixed by the autonomy decision in the map's Notes.

Feeds [Decide the proposal handoff into the approval gate](T05-decide-the-proposal-handoff-into-the-approval-gate.md).

Constrained by [Lock the agent loop contract](T01-lock-the-agent-loop-contract.md): exactly **one** tool call per decision (flat ReAct), `conclude` is the terminal tool, and the workflow validates the tool name against this allow-list (the activity only parses).

## Resolution

Grilled one question at a time. Four decisions, plus the schemas they imply.

**1. The allow-list is exactly six tools** — the minimal set that supports diagnose → train → propose. They are the same six schemas already exercised for real in [Choose the brain model & structured tool-call output](T08-choose-the-brain-model-and-tool-call-output.md), where deepseek-v4-flash selected an allow-listed tool 10/10. Nothing here is speculative. Results are **bounded digests, never raw payloads** (see [Decide where the agent transcript lives](T04-decide-where-the-agent-transcript-lives.md) — history size is the constraint).

| tool | arguments | returns |
| --- | --- | --- |
| `read_registry` | none | the version table (version, stage, accuracy, roc_auc, artifact present/missing) **plus the serving routing**, so one call establishes what is actually live |
| `read_run_metrics` | `run_id` | params (n_estimators, max_depth, learning_rate, random_state, test_size), metrics, duration — the incumbent's hyperparameters, which is what makes a candidate deliberate rather than random |
| `evaluate_version` | `version`, optional `slice_size` | accuracy / roc_auc / precision / recall on a held-out slice |
| `train_candidate` | `n_estimators`, `max_depth`, `learning_rate` | the new version id, its stage (Staging), metrics, artifact present, run id |
| `propose_promotion` | `version`, `rationale` | the pending promotion's workflow id, or a refusal |
| `conclude` | `answer`, `evidence` | terminal — ends the run |

**2. Comparability rule for `evaluate_version`.** It must reuse the trainer's split — `TEST_SIZE = 0.2`, `RANDOM_STATE = 42` — so a candidate's number is comparable with the incumbent's. Without that the agent compares figures taken from different slices and the demo's central claim ("this candidate is better") is unfounded.

**3. `propose_promotion` is a new activity that starts the existing gate.** It first runs the servability guard the worker already imports (`artifact_problem`), so an unreadable artifact is refused as an observation **before a human is ever asked** — otherwise the operator approves and only then watches it fail. On success it starts `PromotionWorkflow` through the Temporal client using the **same `promote-<model>-<version>` id convention** the API uses, so the console's existing discovery and its Approve button work untouched. A duplicate proposal surfaces as `already in progress` rather than an exception.

**4. Training is capped at 2 per run.** The agent may write to the registry, so the blast radius is bounded explicitly: two trainings allow probe-then-refine without leaving a junk drawer of unpromotable versions behind every demo run. Hitting the cap is an observation, not an error — the brain adapts by proposing or concluding instead. `train_candidate` reuses the existing `train_and_register` activity unchanged.

**5. Verdicts versus failures.** The activity catches **expected verdicts** — a guard refusal, an unknown version, an already-pending promotion — and returns a typed envelope (`ok` / `error` / `kind`). Unexpected errors raise, so the retry policy applies to genuine infrastructure failures. A verdict must never be retried; a blip must be. This is what keeps the brain seeing refusals as evidence rather than as crashes.

**Read-only boundary, unchanged from the map:** the agent has no tool that approves a promotion and none that rolls back production.

Feeds [Decide the proposal handoff into the approval gate](T05-decide-the-proposal-handoff-into-the-approval-gate.md) (the pending workflow id and the rationale are the handoff's raw material) and [Lock the run semantics](T06-lock-the-run-semantics.md) (per-tool retry policies follow from decision 5, and the training cap is a run-level counter in workflow state).

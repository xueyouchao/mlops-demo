---
id: T02
title: Define the agent's tool surface & schemas
labels: [wayfinder:grilling]
status: open
assignee: ""
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

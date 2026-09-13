---
id: B01
title: Build the agent loop workflow
labels: [wayfinder:build]
status: open
assignee: ""
blocked-by: [B02, B03]
---

## Scope

The ReAct loop as a Temporal workflow in `services/worker/`, exactly as [Lock the agent loop contract](T01-lock-the-agent-loop-contract.md) fixed it: the goal as workflow input, one step = one brain call → one tool call → one observation, cap 8, the transcript as workflow instance state, a three-minute ceiling measured on the **workflow clock** and excluding the human-gate wait, and the four terminal reasons (`concluded` / `budget_exhausted` / `no_progress` / `failed`).

Also the API's start route: role-gated like the promote route, the goal and `requested_by` as input, the run id returned.

**Done when:** a run can be started through the API, its steps are visible in event history, and killing the worker between steps resumes without re-calling the brain for a recorded step.

**Read with:** T01 (loop contract), T06 (run semantics), T04 (the read path needs the activity names to be distinguishable).

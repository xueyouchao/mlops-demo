---
id: B05
title: Build the console panel
labels: [wayfinder:build]
status: open
assignee: ""
blocked-by: [B04]
---

## Scope

The agreed panel in `ui/src/App.jsx`, in the console's own conventions: its **own sidebar entry**, the goal composer with presets (frozen as workflow input once a run starts), and the **timeline spine** — a rail that *breaks* at the worker's death and shows the resume, a `deciding…` node with a running clock while a step is in flight, labelled fallbacks, separate work and gate clocks, the four terminal reasons, and the approval card (candidate vs incumbent on the same split, rationale, cost paid) with **Abandon run** visually separated from Approve and Decline.

**Done when:** the panel renders every state from the projection alone, including with the worker dead.

**Design source:** T07's resolution. The variant exploration is the primary source and lives on the local branch `prototype/agent-panel-variants`.

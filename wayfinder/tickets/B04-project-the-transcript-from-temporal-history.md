---
id: B04
title: Project the transcript from Temporal history
labels: [wayfinder:build]
status: open
assignee: ""
blocked-by: [B01]
---

## Scope

The read path: the API projects a run's transcript from the **Temporal server's** history — never from a query, which needs a live worker and fails in exactly the window the demo needs. Activity events in order, brain and tool activities distinguishable by name or by a marker in the result payload, projected into entries of decision + observation, plus the run's state, its two clocks (work, and waiting on the human) and its terminal reason.

**Done when:** with the worker stopped, the run's endpoint still returns every completed step — that is the demo's climax, so it is the acceptance test.

**Read with:** T04 (transcript store), T06 (clocks and endings), T07 (what the panel then shows).

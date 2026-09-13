---
id: T03
title: Decide how an investigation starts
labels: [wayfinder:grilling]
status: open
assignee: ""
blocked-by: [T01]
---

## Question

What does the operator actually do to start an investigation, and what exactly reaches the workflow?

Settle:

- **Free-text goal versus preset prompts** — or both, with presets as one-click shortcuts over the same mechanism. A typed goal demos better; a preset is what you fall back on when a live audience is watching and the reasoning model has opinions.
- **What the operator types**, concretely, for the demo to land: a goal phrased in the platform's own vocabulary (e.g. "production is v5 — is there a better candidate?") rather than a prompt-engineering exercise. Decide whether the console shows an example goal.
- **How the goal reaches the workflow** — it is workflow input, so it is fixed at start; confirm that an investigation is started, not edited.
- **What happens with an ambiguous or impossible goal** — the agent should be able to say "this needs a human" rather than burn the step budget. Decide whether that is a tool, a termination reason, or prose.
- **Who may start one** — reuse the existing role gate (`operator` / `admin`) like the promote route does.

Blocks [Prototype the console's agent panel](T07-prototype-the-console-agent-panel.md), which needs to know what the operator types.

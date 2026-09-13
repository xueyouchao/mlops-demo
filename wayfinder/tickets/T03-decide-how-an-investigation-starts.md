---
id: T03
title: Decide how an investigation starts
labels: [wayfinder:grilling]
status: closed
assignee: "dsh session"
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

## Resolution

Grilled as a pair with [Decide where the agent transcript lives](T04-decide-where-the-agent-transcript-lives.md). Three decisions.

**1. One field, two ways to fill it.** The console offers a **free-text goal** plus **one-click presets** that populate the same input. A typed goal proves the agent handles language; a preset is what you fall back on when an audience is watching and you would rather not stake the run on how you happened to phrase things. Both reach the workflow identically — the goal is **workflow input**, so an investigation is *started*, not edited. The presets double as the worked example, phrased in the platform's own vocabulary (e.g. "production is v5 — is there a better candidate?").

**2. `conclude` carries an impossible goal.** When the goal is ambiguous or cannot be acted on, the agent ends with `conclude` and a human-readable verdict — "cannot proceed, and here's why" — reusing the terminal tool and the four reasons that already exist. No seventh tool, no fifth reason. The closely-related case is already handled: if the goal implies promoting a version that cannot serve, [Define the agent's tool surface & schemas](T02-define-the-agent-tool-surface-and-schemas.md) has the guard refuse it as an observation, and the agent concludes on that evidence.

**3. Who may start one.** Reuses the existing role gate (`operator` / `admin`), consistent with the promote route: starting a run spends model tokens and can train candidates, so it is not anonymous work.

**What reaches the workflow:** the goal string and who asked (`requested_by`) — the transcript's first entry, and the audit trail's record that the run happened.

---
id: T07
title: Prototype the console's agent panel
labels: [wayfinder:prototype]
status: open
assignee: ""
blocked-by: [T03, T04]
---

## Question

What does the agent panel actually look like and read like, live, while a run is in flight?

This is a **prototype** ticket: build the cheapest rough artifact that lets the human react — a static mock in the console's own style (`ui/src/App.jsx` + `style.css` conventions: `<section>`, `.row`, `.hint`, `.err`) with fake transcript data is enough. Do not wire it to a real workflow.

What the human needs to judge:

- **How the transcript reads.** Thought / tool call / observation as rows, a chat, or a timeline? The demo's punch is watching the reasoning, so legibility at a glance matters more than density.
- **The durability moment.** What the panel shows while the worker is dead (stale? "worker down, run durable"?), and what it shows when the run resumes — the resume has to be *visible*, or the demo's climax happens off-screen.
- **The proposal**, presented with the evidence [Decide the proposal handoff into the approval gate](T05-decide-the-proposal-handoff-into-the-approval-gate.md) settles, and the existing Approve button as the only way it goes live.
- **Budget and state visibility** — steps used, elapsed time, and whether the scripted fallback is in play.
- **Where the panel lives** — a new sidebar entry alongside the existing inline console, a section of it, or a tab. The console is a single-origin harness with a sidebar (`/diagrams/`, `/temporal/`, `/mlflow/` are frame/link-out tabs).

Deliverable: a throwaway mock the human reviews. Its resolution records what was accepted, and the build work later graduates from it.

## Three rendering requirements inherited from the run semantics

[Lock the run semantics](T06-lock-the-run-semantics.md) settled things the panel must show honestly:

- **Elapsed work time apart from time spent waiting on the human gate.** The three-minute ceiling excludes the approval wait, so a single combined clock would misrepresent a run that is correctly waiting on the operator — the mock must show the two separately.
- **Which of the four terminal reasons ended a run**: `concluded`, `budget_exhausted`, `no_progress`, `failed`.
- **Which producer made each decision.** Every fallback decision is labelled, because the map's standing preference is that the demo never silently pretends.

## Inherited from how a run starts and where the transcript comes from

[Decide how an investigation starts](T03-decide-how-an-investigation-starts.md) and [Decide where the agent transcript lives](T04-decide-where-the-agent-transcript-lives.md) settled two things the mock should already assume:

- The start affordance is a **goal field with one-click presets** filling the same input, plus who is asking.
- The transcript is **projected from Temporal history**, so the panel is showing exactly what the console can see when history is all it has — including while the worker is dead.

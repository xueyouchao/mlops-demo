---
id: T01
title: Lock the agent loop contract
labels: [wayfinder:grilling]
status: open
assignee: ""
blocked-by: []
---

## Question

How is the agent's reason → act → observe cycle expressed as a Temporal workflow, such that a **nondeterministic brain still yields a deterministic, replayable, resumable run**?

Settle at least:

- **Where the brain sits.** It must be an activity, never workflow code: the LLM SDK must not be imported into the workflow sandbox (same discipline the existing workflows use by referring to activities by string name). Confirm the call shape and what the activity returns.
- **What the workflow holds.** The transcript (goal, each tool call, each observation, the final answer) is workflow state, and therefore event history — which is what makes the killed-worker resume work. Decide its shape and what is *not* kept.
- **How the next tool is chosen**, and how a malformed or unparseable brain response is handled (retry? repair prompt? fail the run?).
- **Termination**: the step cap, what counts as done, and whether a run may legitimately end without proposing anything (e.g. "no candidate beats production").
- **Determinism**: anything the brain returns must reach history before it is acted on, so a replay makes the same decisions. State explicitly what would break replay.

Constraints from the map: the brain is host ollama behind an activity with a scripted-policy fallback; the agent may train and propose but never approve or roll back.

Feeds [Define the agent's tool surface & schemas](T02-define-the-agent-tool-surface-and-schemas.md), [Decide how an investigation starts](T03-decide-how-an-investigation-starts.md), [Decide where the agent transcript lives](T04-decide-where-the-agent-transcript-lives.md), [Lock the run semantics](T06-lock-the-run-semantics.md). Informed by [Research how production durable-agent frameworks structure their loops](T09-research-durable-agent-loop-patterns.md).

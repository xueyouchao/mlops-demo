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

## Prior evidence (from the research branch)

[Research how production durable-agent frameworks structure their loops](T09-research-durable-agent-loop-patterns.md) closed with findings on a throwaway branch — read with `git show research/durable-agent-loop-patterns:docs/research/durable-agent-loop-patterns.md` (§1.1, §5). It **narrows this ticket rather than settling it**, and corrects two premises:

- **The shape is already endorsed, so copy it deliberately**: Temporal's own OpenAI Agents SDK integration runs the agent loop in the workflow, model calls as activities, and keeps the transcript in workflow state because that state is replay-safe. Cite that pattern; do not present it as our invention.
- **Correction — "the LLM SDK must not be imported into the workflow sandbox" is stricter than the documented rule.** Temporal's rule is about *calls*; its own cookbook imports the SDK behind the sandbox's pass-through hatch. Our string-name discipline (`services/worker/workflows.py`) is deliberate hardening: keep it, but record it as a choice, not as the rule.
- **State the replay rule precisely**: the tool *choice* must be derived only from values already recorded (goal + transcript) — never from anything sampled inside workflow code. That, not the activity boundary, is what makes replay deterministic.
- **The step cap is ours alone** (Temporal ships none — its own recipe is an unbounded loop). Fix the *unit* as well as the number: does an activity retry, or a repair round-trip, consume a step? The unstated unit is where these designs surprise their authors. [Lock the run semantics](T06-lock-the-run-semantics.md) owns the bound itself.
- **Record the divergence consciously**: every-tool-an-activity is stricter than Temporal's guidance, which leaves deterministic tools inline. Defensible here — every tool is I/O against the platform — but say why rather than leaving it implicit.
- The human gate as signal + `wait_condition` is validated by the same evidence; `PromotionWorkflow` already does exactly this.

Feeds [Define the agent's tool surface & schemas](T02-define-the-agent-tool-surface-and-schemas.md), [Decide how an investigation starts](T03-decide-how-an-investigation-starts.md), [Decide where the agent transcript lives](T04-decide-where-the-agent-transcript-lives.md), [Lock the run semantics](T06-lock-the-run-semantics.md). Informed by [Research how production durable-agent frameworks structure their loops](T09-research-durable-agent-loop-patterns.md).

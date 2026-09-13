---
id: T09
title: Research how production durable-agent frameworks structure their loops
labels: [wayfinder:research]
status: closed
assignee: "research subagent 8799941c"
blocked-by: []
---

## Question

How do production-grade durable-agent frameworks structure the agent loop — and what does that imply for expressing ours as a Temporal workflow?

Investigate against **primary sources** (official docs, source code, specs — not blog summaries):

- **Temporal's own guidance for AI/agent workloads** — durable execution of LLM calls, why the model call belongs in an activity, context/state handling across replays, and any first-party agent SDK or sample.
- **OpenAI Agents SDK** — the loop shape (turn, tool call, handoff, guardrail), where state lives, and how it terminates.
- **LangGraph** (and comparable durable-graph runtimes) — checkpointing and resumption semantics, how they achieve "resume without re-running completed steps", and how they bound loops.
- Any first-party guidance on **structured tool-call schemas** and **termination conditions** for tool-using agents.

Answer specifically:

1. What is the standard shape of the loop, and where does our design (deterministic workflow + nondeterministic brain activity + transcript in history) *match* versus deliberately diverge?
2. How do these frameworks handle a **worker dying mid-run** — is resumption automatic, and what state must be durable for it?
3. What do they do about **runaway loops, step budgets, and tool-error feedback to the model**?
4. What is the accepted way to get **reliable tool calls** out of a model that may or may not support native tool-calling?

**Deliverable**: findings on a throwaway branch — `git show research/durable-agent-loop-patterns:docs/research/durable-agent-loop-patterns.md` — with every claim cited to its primary source. Findings are never pasted into this ticket; the resolution points at the branch.

Feeds [Lock the agent loop contract](T01-lock-the-agent-loop-contract.md) and [Lock the run semantics](T06-lock-the-run-semantics.md).

## Resolution

Resolved by a background research subagent (`8799941c`). Findings are **not** reproduced here, per the tracker's rule — they live on a throwaway branch, read with:

```
git show research/durable-agent-loop-patterns:docs/research/durable-agent-loop-patterns.md
```

811 lines, 54 citations, primary sources only: Temporal's docs and source, the OpenAI Agents SDK, LangGraph, ollama, and Anthropic's tool-use protocol. Vendor blog prose is labelled as such and never treated as specification.

**Answer.** Our shape is not an invention — it is Temporal's *shipped* pattern: its own OpenAI Agents SDK integration runs the agent loop in the workflow, model calls as activities, and keeps the transcript in workflow state precisely because that state is replay-safe. Temporal ships **no step bound of its own** (its agentic-loop cookbook is an unbounded `while True:`), so the cap is ours alone to define — and OpenAI's `DEFAULT_MAX_TURNS = 10` versus LangGraph's `recursion_limit = 1000` shows the unit is framework-specific, which means we have to name ours. Making every tool an activity is stricter than Temporal's guidance but is the default in Strands and Deep Agents, and is defensible here since all our tools are I/O against the platform.

**Three corrections reached the map** — applied to the tickets themselves, not recorded here: [Lock the agent loop contract](T01-lock-the-agent-loop-contract.md) (the no-SDK-import rule is our hardening, not the documented rule), [Decide where the agent transcript lives](T04-decide-where-the-agent-transcript-lives.md) (the console's read path must survive the worker being *dead*, which a Temporal query cannot), and [Lock the run semantics](T06-lock-the-run-semantics.md) (the demo has an at-least-once hole — a retried activity restarts from the top and its failed attempt is not rolled back, so a kill during training risks training twice). The last is the note's single most important practical caveat.

**Confidence, stated by the note itself.** `web_search` was unavailable in the researcher's session, so discovery was URL-directed rather than breadth-first and an unlinked first-party page may be missing. Nothing was measured: no worker killed, no model called. The ollama claims — that the `:cloud` models honour `tools`, and that ollama Cloud refuses schema-constrained `format` — remain vendor statements plus a capability tag, and [Choose the brain model & structured tool-call output](T08-choose-the-brain-model-and-tool-call-output.md) owns measuring them.

---
id: T09
title: Research how production durable-agent frameworks structure their loops
labels: [wayfinder:research]
status: open
assignee: ""
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

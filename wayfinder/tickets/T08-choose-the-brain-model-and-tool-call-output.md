---
id: T08
title: Choose the brain model & structured tool-call output
labels: [wayfinder:task]
status: open
assignee: ""
blocked-by: []
---

## Question

Which model makes the agent's decisions, and how are tool calls reliably obtained from it?

An AFK measurement task, then a decision. Host ollama already serves `deepseek-v4-flash:cloud`, `glm-5.2:cloud`, `kimi-k2.7-code:cloud`, `minimax-m3:cloud`, `deepseek-v4-pro:cloud`, `glm-5.1:cloud`, `minimax-m2.7:cloud`, `kimi-k2.6:cloud` and local `bge-m3`. Measure, don't assume:

1. **Native tool-calling support.** Do these models accept ollama's `tools` parameter, and do they return `tool_calls`? If yes, that is the contract. If not, the fallback is prompt-for-JSON plus a parse/repair step — and the JSON reliability rate has to be measured for each candidate.
2. **Latency**, per model, for a realistic agent prompt (~1–2k tokens in, one tool call out). This sets the step budget in [Lock the run semantics](T06-lock-the-run-semantics.md) and decides whether a 6-step demo is watchable.
3. **Instruction-following under a schema.** Feed each model the same tool schema and a small scenario, and count valid, well-formed, *sensible* tool calls across ~10 runs.

Record the numbers in the resolution — they are the evidence for the choice, and they expire, so date them.

**Known trap, verified during charting**: these are reasoning models whose response carries both `content` and `thinking`. A small `num_predict` is consumed entirely by thinking tokens and returns an *empty* `content`, which looks exactly like a broken model. Measure with generation limits that account for this.

Also decide: which model is the *default* for the demo, whether it is configurable by env, and whether the scripted fallback is a separate model or a policy engine (see the map's Notes).

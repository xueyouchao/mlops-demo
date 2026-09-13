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

## Prior evidence (from the research branch) — a claim to test, not to trust

[Research how production durable-agent frameworks structure their loops](T09-research-durable-agent-loop-patterns.md) closed with findings on a throwaway branch — read with `git show research/durable-agent-loop-patterns:docs/research/durable-agent-loop-patterns.md` (§4, §5). Two things it could **not** verify, which is exactly why this ticket exists:

- **ollama's docs state that Cloud models do not support structured outputs** — and every brain candidate is a `:cloud` model. Meanwhile all of them carry ollama's `tools` capability tag. Both are vendor statements and neither is a measurement, so **test both**: does a `:cloud` model return `tool_calls` when handed `tools`, and does it accept a `format` schema? The answer decides whether the primary path or the fallback is the primary path.
- **Validate the tool call whatever the provider claims.** Vendors headline "no need to validate" and then document exceptions on the same page; OpenAI's strict mode can silently degrade to best-effort function calling. So the brain activity must validate the returned call and distinguish **unparseable** from **unknown tool** from **nonsensical arguments**, returning each as an observation the model can react to rather than as an exception. (Feeding tool errors back as observations *is* the norm — OpenAI's own default error function does precisely that.)
- **If the prompt-for-JSON fallback is needed, reuse the known four-part shape** rather than inventing one: a JSON blob in the prompt with a sentinel, a tolerant parse, a typed parse error, and a bounded repair call carrying the error text. It is legacy in LangChain and absent from the OpenAI Agents SDK, so there is nothing to copy wholesale — but the shape is documented.
- **Give the scripted-policy fallback the same output contract** as the model activity, so two producers feed one parsing path.

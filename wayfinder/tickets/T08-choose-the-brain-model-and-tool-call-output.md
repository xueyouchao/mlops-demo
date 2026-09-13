---
id: T08
title: Choose the brain model & structured tool-call output
labels: [wayfinder:task]
status: closed
assignee: "dsh session"
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

## Resolution

Measured against the host's ollama **0.32.15** at `localhost:11434` on **2026-09-13 04:52 UTC**. These numbers expire — re-measure if the daemon or the model tags move.

**1. Native `tools` works, on every candidate.** All eight `:cloud` models returned a well-formed `tool_calls` for a supplied tool schema, with the correct tool name, in 0.8–3.1 s (minimax-m3 0.8, kimi-k2.7-code 0.9, deepseek-v4-pro 1.0, minimax-m2.7 1.6, glm-5.2 1.9, glm-5.1 2.0, deepseek-v4-flash 2.8, kimi-k2.6 3.1). The research's unverified claim resolves in the affirmative: **native tool-calling is the primary path**, and the prompt-for-JSON fallback is not needed for the models on this host.

**2. `format` (structured outputs) does not constrain output — measured, not assumed.** Every model *accepts* a `format` schema and answers HTTP 200, but the schema is not enforced: with a generous budget, deepseek-v4-flash returned `{"tool": "search_models"}` (missing a required key), glm-5.2 and minimax-m3 returned markdown-fenced JSON, and only kimi-k2.7-code happened to conform. There is no error to detect — the request simply is not honoured, which corroborates ollama's documented Cloud limitation and settles it here: **do not build the output contract on `format`.** Use `tools` and validate the call regardless of provider.

**3. The trap at realistic size: a tight generation budget silently destroys the tool call.** These are reasoning models and the tool call is emitted *after* the thinking. At `num_predict=512` against a ~700-token step-6 prompt, glm-5.2 and minimax-m3 returned `done_reason=length`, `eval_count=512`, ~1,900–2,000 characters of thinking — and **empty content with no tool call**. That first read as three models being incompetent (0/5); raising the budget to 4096 on the identical prompt produced clean calls from both. deepseek-v4-flash is the least verbose reasoner (~730 characters of thinking versus 1,900–3,500), which is why it tolerated the tight budget and looked strong in that invalid comparison.
  Consequence for the build: set a **generous `num_predict` (4096 measured)**, and have the brain activity treat `done_reason == "length"` as a typed failure — `truncated` — rather than returning an empty decision. That feeds straight into [Lock the agent loop contract](T01-lock-the-agent-loop-contract.md) decision 4: a bad decision is an observation that burns a step, and this is one of its real cases.

**4. Reliability and latency at an adequate budget** — realistic ~700-token step-6 prompt, 10 runs each, `num_predict=4096`:

| model | valid calls | latency p50 | latency max | choices |
| --- | --- | --- | --- | --- |
| **deepseek-v4-flash:cloud** | **10/10** | **2.9 s** | 3.1 s | propose_promotion ×9, train_candidate ×1 |
| glm-5.2:cloud | 10/10 | 8.9 s | 14.5 s | train_candidate ×5, propose_promotion ×3, conclude ×2 |
| minimax-m3:cloud | 10/10 | 14.6 s | 25.2 s | conclude ×4, propose_promotion ×4, train_candidate ×2 |
| kimi-k2.7-code:cloud | 8/10 | 9.8 s | 28.2 s | propose_promotion ×7, conclude ×1 |

Every returned call named an allow-listed tool with parseable arguments — no unknown tools and no malformed arguments across the pass.

**Decision — the default brain is `deepseek-v4-flash:cloud`.** It was 100 % valid, **3× faster than the next candidate** (2.9 s p50 and 3.1 s worst case, versus 8.9 s and 14.5–28.2 s), and the most decisive: it recognised that version 6 had beaten version 5 on the identical slice and proposed accordingly. Latency decides a live demo — at ~3 s per step an 8-step run spends ~25 s in the model, leaving room for the tool calls. The model name is configurable by env; the other three stay valid fallbacks, and the scripted-policy fallback shares this output contract so every producer feeds one parsing path.

**Not verified here:** whether these models hold up across the *full* 8-step transcript (this measured a step-6 prompt), and whether `:cloud` availability or latency drifts with daemon load. Both are worth a glance on the loop's first end-to-end run.

## Amendment — 2026-09-13: the operator's model overrides the latency pick

The decision above was made on measurement. The operator has chosen a different model, so **the demo's brain is `deepseek-v4.1-flash:cloud`** — the model DSH itself runs on. Recorded rather than quietly swapped, because the evidence above still stands and the basis of the override is not a number:

- **Re-measured on the same step-6 scenario, 5 runs each.** `deepseek-v4.1-flash:cloud`: **5/5 valid, allow-listed tool calls** (4× `propose_promotion`, 1× a redundant `evaluate_version`) at **p50 12.9 s, max 36.5 s**. `deepseek-v4-flash:cloud`: 5/5, p50 2.0 s, max 2.4 s. So the model works — the tool-calling contract holds — but it is **~6× slower at the median and ~15× at the tail**.
- **That latency is paid for deliberately, not ignored.** The run's work ceiling was set while a 2-second model was assumed; at 12.9 s per step a slow draw ends the run as `budget_exhausted` before the proposal is ever filed. The ceiling was raised with this change — see the amendment in [Lock the run semantics](T06-lock-the-run-semantics.md).
- **Transport, verified rather than assumed.** DSH reaches this model at `https://ollama.com/v1` with `OLLAMA_API_KEY` (from `~/.dsh/settings.yaml`), but the demo needs no key: the host daemon proxies the same cloud model by name. Confirmed **from inside the worker container** over the bridge address — `tools` honoured, 2.6 s on a trivial prompt. `ollama pull deepseek-v4.1-flash:cloud` registers it as a 326-byte metadata pull, so a fresh host reproduces the setup.
- **Sighted in passing:** that account can also serve `glm-5.3:cloud`, `glm-5.3-flash:cloud` and `kimi-k3:cloud`, none registered on this daemon. Worth remembering as faster candidates if the demo ever needs one.

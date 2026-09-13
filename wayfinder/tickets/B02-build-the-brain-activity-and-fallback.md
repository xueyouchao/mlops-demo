---
id: B02
title: Build the brain activity and the fallback
labels: [wayfinder:build]
status: open
assignee: ""
blocked-by: []
---

## Scope

The brain activity: ollama `/api/chat` with the six tool schemas as native `tools`, `num_predict` **4096**, `done_reason == "length"` treated as a typed `truncated` failure rather than an empty decision, and the model name configurable by env (default `deepseek-v4-flash:cloud`).

The deterministic scripted-policy fallback, sharing the brain's output contract, engaged automatically when ollama is unreachable and forced by an explicit flag, with **every fallback decision labelled** so a viewer can always tell which producer decided.

**Done when:** the brain returns one allow-listed tool call per call at a realistic prompt size, and the fallback produces the same shape carrying its label.

**Read with:** T08 (measured model behaviour — including the `num_predict` trap that invalidated a whole first measurement pass).

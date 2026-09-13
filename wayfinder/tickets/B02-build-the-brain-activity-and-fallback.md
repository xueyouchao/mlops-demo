---
id: B02
title: Build the brain activity and the fallback
labels: [wayfinder:build]
status: closed
assignee: ""
blocked-by: []
---

## Scope

The brain activity: ollama `/api/chat` with the six tool schemas as native `tools`, `num_predict` **4096**, `done_reason == "length"` treated as a typed `truncated` failure rather than an empty decision, and the model name configurable by env (default `deepseek-v4.1-flash:cloud` — the operator's choice, 2026-09-13; see the amendment in T08).

The deterministic scripted-policy fallback, sharing the brain's output contract, engaged automatically when ollama is unreachable and forced by an explicit flag, with **every fallback decision labelled** so a viewer can always tell which producer decided.

**Done when:** the brain returns one allow-listed tool call per call at a realistic prompt size, and the fallback produces the same shape carrying its label.

**Read with:** T08 (measured model behaviour — including the `num_predict` trap that invalidated a whole first measurement pass).

## Outcome

Built as `services/worker/brain.py` — stdlib only, so the parsing and the policy are testable on the host without the worker image — wrapped by the `brain_decide` activity in `activities.py`, registered on the worker and copied into the image.

**Done-when, verified rather than asserted:**
- *one allow-listed tool call per call at a realistic prompt size* — 5/5 on the step-6 scenario, and additionally called **from inside the worker container over the bridge address**, which is the only place that proves the container can reach the host daemon at all (2.6 s trivial, 4.7 s full);
- *the fallback produces the same shape and carries its label* — forced (`AGENT_FALLBACK=on`), automatic (unreachable, labelled with the failure it absorbed) and refusing (`off` returns a typed `unreachable` failure rather than degrading in silence).

Both producers feed one parser, so a scripted decision and a model decision are read by the same code — checked directly.

**Two changes the build forced, both recorded elsewhere:** every tool gained a required `why` argument (amendment in T02) because the chosen model fills arguments 5/5 and prose 0/5; and the run's work ceiling moved from three minutes to six (amendment in T06) because that model is ~6× slower at the median.

**A bug found by testing, worth remembering:** the first version retried a failed call at a 120 s timeout, so a dead ollama cost **four minutes for a single brain call** — more than the run's entire ceiling. A failure that took longer than 5 s is now not retried, and a per-process breaker stops every later step paying it again.

**Not covered here:** the loop that calls this (B01), the tools it names (B03), and any judgement of whether the decisions are *good* beyond one scenario. `services/worker/test_brain.py` — 34 checks, runnable on the host — covers parsing, the prompt, the scripted policy, producer selection and one live model call.

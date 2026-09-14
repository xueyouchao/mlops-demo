"""Checks for brain.py. Plain asserts, no pytest — run it anywhere python3 runs.

    python3 services/worker/test_brain.py

The pure parts (parsing, prompt, scripted policy) run with stdlib only. The
last check talks to the host's real ollama and is skipped if it is not there.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import brain  # noqa: E402

PASSED, FAILED = [], []


def check(name: str, condition: bool, detail: str = ""):
    (PASSED if condition else FAILED).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}{'' if condition else f'  <- {detail}'}")


def raises_kind(kind: str, response: dict) -> bool:
    try:
        brain.parse_response(response)
    except brain.BrainError as e:
        return e.kind == kind
    return False


# --------------------------------------------------------------------------
print("\nparsing a model response")
check("a normal tool call parses",
      brain.parse_response({"message": {"content": "why", "tool_calls": [
          {"function": {"name": "read_registry", "arguments": {}}}]}})["tool"] == "read_registry")

check("arguments as a JSON string are decoded",
      brain.parse_response({"message": {"tool_calls": [
          {"function": {"name": "evaluate_version", "arguments": '{"version": "5"}'}}]}}
      )["arguments"] == {"version": "5"})

check("missing tool_calls -> no_tool_call",
      raises_kind("no_tool_call", {"message": {"content": "I will think about it"}}))

check("done_reason=length -> truncated",
      raises_kind("truncated", {"done_reason": "length", "eval_count": 4096,
                                "message": {"content": "", "tool_calls": []}}))

check("unparseable arguments -> bad_arguments",
      raises_kind("bad_arguments", {"message": {"tool_calls": [
          {"function": {"name": "conclude", "arguments": "{not json"}}]}}))

check("a tool call with no name -> no_tool_call",
      raises_kind("no_tool_call", {"message": {"tool_calls": [{"function": {"arguments": {}}}]}}))

check("raw thinking is never carried into the rationale",
      brain.parse_response({"message": {"content": "the rationale", "thinking": "SECRET",
                                        "tool_calls": [{"function": {"name": "conclude", "arguments": {}}}]}}
                           )["rationale"] == "the rationale")

check("the `why` argument becomes the rationale when prose is absent",
      brain.parse_response({"message": {"content": "", "tool_calls": [
          {"function": {"name": "evaluate_version", "arguments": {"version": "5", "why": "score the incumbent"}}}]}}
      )["rationale"] == "score the incumbent")

check("and is lifted out of the arguments the workflow sees",
      brain.parse_response({"message": {"tool_calls": [
          {"function": {"name": "evaluate_version", "arguments": {"version": "5", "why": "score the incumbent"}}}]}}
      )["arguments"] == {"version": "5"})

check("prose still wins when the model volunteers it",
      brain.parse_response({"message": {"content": "prose reason", "tool_calls": [
          {"function": {"name": "conclude", "arguments": {"why": "argument reason"}}}]}}
      )["rationale"] == "prose reason")

check("every tool requires a `why`",
      all("why" in t["function"]["parameters"]["required"] for t in brain.TOOL_SCHEMAS))

# --------------------------------------------------------------------------
print("\nthe prompt")
entries = [{"step": 1, "tool": "read_registry", "arguments": {}, "rationale": "because",
            "observation": "v5 Production", "producer": "model"}]
msgs = brain.build_messages("is there a better candidate?", entries)
check("the goal reaches the prompt", "is there a better candidate?" in msgs[1]["content"])
check("the rationale reaches the prompt", "because" in msgs[1]["content"])
check("an empty transcript says so", "first step" in brain.render_transcript([]))
check("a fallback step is disclosed to the model",
      "scripted policy" in brain.render_transcript([{"step": 1, "tool": "read_registry",
                                                      "producer": "scripted-policy", "observation": "x"}]))

# --------------------------------------------------------------------------
print("\nthe scripted policy")
good = [
    {"step": 1, "tool": "read_registry", "arguments": {}, "rationale": "", "observation": "5 versions · v5 Production (acc .842)", "producer": "model"},
    {"step": 2, "tool": "evaluate_version", "arguments": {"version": "5"}, "rationale": "", "observation": "accuracy 0.842 · roc_auc 0.871", "producer": "model"},
    {"step": 3, "tool": "train_candidate", "arguments": {"n_estimators": 300}, "rationale": "", "observation": "registered v6 (Staging) · accuracy 0.878", "producer": "model"},
    {"step": 4, "tool": "evaluate_version", "arguments": {"version": "6"}, "rationale": "", "observation": "accuracy 0.878 · roc_auc 0.904", "producer": "model"},
]
d = brain.scripted_decision("goal", [])
check("an empty transcript starts by reading the registry", d["tool"] == "read_registry")
check("the producer is the scripted policy", d["producer"] == "scripted-policy")

d = brain.scripted_decision("goal", good[:1])
check("it evaluates the incumbent next",
      d["tool"] == "evaluate_version" and d["arguments"]["version"] == "5", str(d))

d = brain.scripted_decision("goal", good[:2])
check("it trains a candidate next", d["tool"] == "train_candidate", str(d))

d = brain.scripted_decision("goal", good[:3])
check("it evaluates the candidate next",
      d["tool"] == "evaluate_version" and d["arguments"]["version"] == "6", str(d))

d = brain.scripted_decision("goal", good)
check("a better candidate gets proposed",
      d["tool"] == "propose_promotion" and d["arguments"]["version"] == "6", str(d))

worse = good[:3] + [{"step": 4, "tool": "evaluate_version", "arguments": {"version": "6"},
                     "rationale": "", "observation": "accuracy 0.800 · roc_auc 0.810", "producer": "model"}]
d = brain.scripted_decision("goal", worse)
check("a worse candidate is concluded on, not proposed",
      d["tool"] == "conclude" and "No better candidate" in d["arguments"]["answer"], str(d))

d = brain.scripted_decision("goal", [{"step": 1, "tool": "read_registry", "arguments": {},
                                      "observation": "no versions at all", "producer": "model"}])
check("an unreadable incumbent does not become a guess", d["tool"] == "conclude", str(d))

check("every scripted decision is a real tool",
      all(brain.scripted_decision("g", good[:i])["tool"] in brain.TOOL_NAMES for i in range(len(good))))

check("both producers hand the workflow clean arguments (no `why` key)",
      all("why" not in brain.scripted_decision("g", good[:i])["arguments"] for i in range(len(good))))

# --------------------------------------------------------------------------
print("\nproducer selection")
os.environ["AGENT_FALLBACK"] = "on"
d = brain.decide("goal", [])
check("AGENT_FALLBACK=on forces the policy", d["producer"] == "scripted-policy" and d["ok"])
check("and says why it fell back", "AGENT_FALLBACK=on" in (d.get("fallback_reason") or ""))
check("and reports its latency", isinstance(d.get("latency_ms"), int))

os.environ["AGENT_FALLBACK"] = "auto"
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:1"   # nothing listens here
d = brain.decide("goal", [])
check("auto falls back when ollama is unreachable",
      d["producer"] == "scripted-policy" and d.get("fallback_reason"), str(d))
check("the fallback names the failure it absorbed", "unreachable" in (d.get("fallback_reason") or ""), str(d))

import time as _time  # noqa: E402
t0 = _time.monotonic()
d2 = brain.decide("goal", [])
elapsed = _time.monotonic() - t0
check("the breaker stops every step paying the timeout",
      elapsed < 0.5 and "known unreachable" in (d2.get("fallback_reason") or ""),
      f"{elapsed:.2f}s, reason={d2.get('fallback_reason')!r}")

os.environ["AGENT_FALLBACK"] = "off"
d = brain.decide("goal", [])
check("off refuses to fall back", d["ok"] is False and d["kind"] == "unreachable", str(d))

# --------------------------------------------------------------------------
print("\nthe model call's Sentry span")
# Sentry is stood in for here: what matters is what brain.py *asks* it for, and
# that is checkable without a DSN, a network, or the real SDK's version quirks.
# The reply is a real ollama-shaped response, so the token counts are the ones
# the model would actually report.


class FakeSpan:
    def __init__(self, op=None, name=None):
        self.op, self.name = op, name
        self.data, self.children = {}, []
        self.finished = False

    def set_data(self, key, value):
        self.data[key] = value

    def finish(self):
        self.finished = True

    def start_child(self, op=None, name=None):
        child = FakeSpan(op, name)
        self.children.append(child)
        return child


class FakeSentry:
    def __init__(self):
        self.transactions = []

    def start_transaction(self, op=None, name=None):
        t = FakeSpan(op, name)
        self.transactions.append(t)
        return t


class RudeSpan:
    """A Sentry that fails at everything, to prove telemetry cannot break a run."""

    def set_data(self, key, value):
        raise RuntimeError("telemetry is broken")

    def finish(self):
        raise RuntimeError("telemetry is broken")

    def start_child(self, **kwargs):
        return RudeSpan()


class RudeSentry:
    def start_transaction(self, **kwargs):
        raise RuntimeError("telemetry is broken")


class RudeChildSentry:
    def start_transaction(self, **kwargs):
        return RudeSpan()


OLLAMA_REPLY = {
    "model": "deepseek-v4.1-flash:cloud", "done_reason": "stop",
    "prompt_eval_count": 812, "eval_count": 64,
    "message": {"tool_calls": [
        {"function": {"name": "read_registry", "arguments": {"why": "start from the registry"}}}]},
}
DECIDE_CONFIG = {"model": "deepseek-v4.1-flash:cloud", "base_url": "http://ollama",
                 "num_predict": 4096, "fallback": "auto", "timeout_s": 60}

real_post_json = brain._post_json
real_sentry = brain.sentry_sdk
brain._post_json = lambda url, payload, timeout_s, attempts=2: OLLAMA_REPLY
brain.reset_model_breaker()   # the unreachable checks above tripped it

fake = FakeSentry()
brain.sentry_sdk = fake
d = brain.decide("goal", [], DECIDE_CONFIG)
spans = [s for t in fake.transactions for s in t.children]

check("a model call opens exactly one gen_ai span", len(spans) == 1 and spans[0].op == "gen_ai.chat",
      str([(t.op, [s.op for s in t.children]) for t in fake.transactions]))
check("the span is named for the operation and the model",
      spans and spans[0].name == f"chat {DECIDE_CONFIG['model']}", str(spans and spans[0].name))
check("it names the operation, the provider and the requested model",
      spans and (spans[0].data.get("gen_ai.operation.name"),
                 spans[0].data.get("gen_ai.provider.name"),
                 spans[0].data.get("gen_ai.request.model")) == ("chat", "ollama", DECIDE_CONFIG["model"]),
      str(spans and spans[0].data))
check("token usage is recorded when the response reports it",
      spans and (spans[0].data.get("gen_ai.usage.input_tokens"),
                 spans[0].data.get("gen_ai.usage.output_tokens")) == (812, 64),
      str(spans and spans[0].data))
check("the container span claims no gen_ai operation of its own",
      all(t.op == "function" for t in fake.transactions), str([t.op for t in fake.transactions]))
check("both spans are finished (an unfinished span is dropped)",
      spans and spans[0].finished and all(t.finished for t in fake.transactions))

fakeless = FakeSentry()
brain.sentry_sdk = fakeless
brain.decide("goal", [], dict(DECIDE_CONFIG, fallback="on"))
check("the scripted fallback emits no LLM span at all (it is not a model call)",
      fakeless.transactions == [], str([t.op for t in fakeless.transactions]))

brain.sentry_sdk = RudeSentry()
d2 = brain.decide("goal", [], DECIDE_CONFIG)
check("a Sentry that raises cannot fail the run", d2.get("ok") and d2.get("producer") == "model", str(d2))

brain.sentry_sdk = RudeChildSentry()
d3 = brain.decide("goal", [], DECIDE_CONFIG)
check("nor can a span that refuses every attribute",
      d3.get("ok") and d3.get("producer") == "model", str(d3))

brain._post_json = real_post_json
brain.sentry_sdk = real_sentry

# --------------------------------------------------------------------------
print("\nthe real model (host ollama)")
os.environ["AGENT_FALLBACK"] = "auto"
# NB: brain.DEFAULT_BASE_URL is the *container's* view of the host. Run this
# test on the host and it must use the loopback address instead — pointing it at
# the bridge address from the host hangs (the SYN is dropped), which is how the
# timeout bug above was found.
os.environ["OLLAMA_BASE_URL"] = os.getenv("OLLAMA_HOST_URL", "http://localhost:11434")
brain.reset_model_breaker()   # the unreachable checks above tripped it
real = [{"step": i + 1, "tool": e["tool"], "arguments": e["arguments"], "rationale": e["rationale"],
         "observation": e["observation"], "producer": "model"} for i, e in enumerate(good)]
d = brain.decide("Production is v5 — is there a better candidate?", real)
if d["ok"] and d["producer"] == "model":
    check(f"the model returned an allow-listed tool call ({d['tool']}, {d['latency_ms']} ms)",
          d["tool"] in brain.TOOL_NAMES, str(d))
    check("and it can be read by the scripted policy's own parser (one contract)",
          isinstance(d["arguments"], dict))
else:
    print(f"  SKIP  host ollama not answering as expected: {d}")

# --------------------------------------------------------------------------
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
sys.exit(1 if FAILED else 0)

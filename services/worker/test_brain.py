"""Checks for brain.py. Plain asserts, no pytest — run it anywhere python3 runs.

    python3 services/worker/test_brain.py

The pure parts (parsing, prompt, scripted policy) run with stdlib only. The
last check talks to the host's real ollama and is skipped if it is not there.
"""
from __future__ import annotations

import json
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
print("\nthe Sentry shape of one step")
# Sentry is stood in for here: what matters is what brain.py *asks* it for, and
# that is checkable without a DSN, a network, or the real SDK's version quirks.
# The reply is a real ollama-shaped response, so the token counts are the ones
# the model would actually report.
#
# The fake mirrors the two SDK behaviours the shape depends on: `new_scope()`
# forks a scope and `ai.set_conversation_id` writes onto the current (forked)
# one; and `ai.set_data_normalized` unpacks a one-element list, which is how
# `["stop"]` becomes the string the real SDK sends.


class FakeSpan:
    def __init__(self, op=None, name=None):
        self.op = op
        self.description = name
        self.name = name
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


class FakeScope:
    def __init__(self, sentry):
        self.sentry = sentry
        self.conversation_id = None
        self.exited = False

    def __enter__(self):
        self.sentry.scopes.append(self)
        return self

    def __exit__(self, *exc):
        self.exited = True
        self.sentry.scopes.pop()
        return None


class FakeAi:
    def __init__(self, sentry):
        self.sentry = sentry

    def set_conversation_id(self, conversation_id):
        if not self.sentry.scopes:
            raise RuntimeError("set_conversation_id outside a scope")
        self.sentry.scopes[-1].conversation_id = conversation_id

    def set_data_normalized(self, span, key, value):
        span.set_data(key, value[0] if isinstance(value, list) and len(value) == 1
                      else json.dumps(value))


class FakeSentry:
    def __init__(self):
        self.transactions = []
        self.scopes = []          # the open scope stack
        self.scopes_created = []  # every fork, kept so it can be inspected after exit
        self.ai = FakeAi(self)

    def start_transaction(self, op=None, name=None):
        t = FakeSpan(op, name)
        self.transactions.append(t)
        return t

    def new_scope(self):
        scope = FakeScope(self)
        self.scopes_created.append(scope)
        return scope


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

    def new_scope(self, **kwargs):
        raise RuntimeError("telemetry is broken")


class RudeChildSentry:
    def start_transaction(self, **kwargs):
        return RudeSpan()

    def new_scope(self, **kwargs):
        return FakeScope(FakeSentry())


OLLAMA_REPLY = {
    "model": "deepseek-v4.1-flash", "done_reason": "stop",
    "prompt_eval_count": 812, "eval_count": 64,
    "message": {"tool_calls": [
        {"function": {"name": "read_registry", "arguments": {"why": "start from the registry"}}}]},
}
DECIDE_CONFIG = {"model": "deepseek-v4.1-flash:cloud", "base_url": "http://ollama",
                 "num_predict": 4096, "fallback": "auto", "timeout_s": 60}
RUN_ID = "agent-1f4c9a2b"

real_post_json = brain._post_json
real_sentry = brain.sentry_sdk
real_sdk_ai = brain.sdk_ai
brain._post_json = lambda url, payload, timeout_s, attempts=2: OLLAMA_REPLY
brain.reset_model_breaker()   # the unreachable checks above tripped it

check("a workflow id is already a safe conversation id",
      brain.conversation_id_for(RUN_ID) == RUN_ID, brain.conversation_id_for(RUN_ID))
check("one that is not is made safe (Sentry uses it as a URL path segment)",
      "/" not in brain.conversation_id_for("agent/../x y")
      and brain.conversation_id_for("agent/../x y").strip("-") != "",
      brain.conversation_id_for("agent/../x y"))
check("no run id means no conversation id, rather than a made-up one",
      brain.conversation_id_for(None) == "" and brain.conversation_id_for("") == "")

fake = FakeSentry()
brain.sentry_sdk = fake
brain.sdk_ai = fake.ai
d = brain.decide("goal", [], DECIDE_CONFIG, run_id=RUN_ID)
txns = fake.transactions
agent_spans = [c for t in txns for c in t.children]
model_spans = [c for a in agent_spans for c in a.children]

check("one step opens one container span, and it claims no gen_ai operation",
      len(txns) == 1 and txns[0].op == "function"
      and not any(k.startswith("gen_ai.") for k in txns[0].data),
      str([(t.op, sorted(t.data)) for t in txns]))
check("the agent span is an invoke_agent span, one per step",
      len(agent_spans) == 1 and agent_spans[0].op == "gen_ai.invoke_agent",
      str([(a.op, a.description) for a in agent_spans]))
check("named for the operation and the agent, so a run reads as an agent invocation",
      agent_spans and agent_spans[0].description == f"invoke_agent {brain.AGENT_NAME}",
      str(agent_spans and agent_spans[0].description))
check("it names the operation and the agent",
      agent_spans and (agent_spans[0].data.get("gen_ai.operation.name"),
                       agent_spans[0].data.get("gen_ai.agent.name"))
      == ("invoke_agent", brain.AGENT_NAME),
      str(agent_spans and agent_spans[0].data))
check("and carries the run's conversation id",
      agent_spans and agent_spans[0].data.get("gen_ai.conversation.id") == RUN_ID,
      str(agent_spans and agent_spans[0].data))
check("a model call is one gen_ai.chat span, beneath the agent span",
      len(model_spans) == 1 and model_spans[0].op == "gen_ai.chat",
      str([(m.op, m.description) for m in model_spans]))
check("named for the operation and the model",
      model_spans and model_spans[0].description == f"chat {DECIDE_CONFIG['model']}",
      str(model_spans and model_spans[0].description))
check("it names the provider, the requested model and the served one",
      model_spans and (model_spans[0].data.get("gen_ai.provider.name"),
                       model_spans[0].data.get("gen_ai.request.model"),
                       model_spans[0].data.get("gen_ai.response.model"))
      == ("ollama", DECIDE_CONFIG["model"], "deepseek-v4.1-flash"),
      str(model_spans and model_spans[0].data))
check("it records the finish reason the way the SDK's own integrations do",
      model_spans and model_spans[0].data.get("gen_ai.response.finish_reasons") == "stop",
      str(model_spans and model_spans[0].data))
check("token usage is recorded when the response reports it, the total included",
      model_spans and (model_spans[0].data.get("gen_ai.usage.input_tokens"),
                       model_spans[0].data.get("gen_ai.usage.output_tokens"),
                       model_spans[0].data.get("gen_ai.usage.total_tokens")) == (812, 64, 876),
      str(model_spans and model_spans[0].data))
check("the model span is in the same conversation as its agent span",
      model_spans and model_spans[0].data.get("gen_ai.conversation.id") == RUN_ID,
      str(model_spans and model_spans[0].data))
check("every span is finished (an unfinished span is dropped)",
      all(t.finished for t in txns) and all(a.finished for a in agent_spans)
      and all(m.finished for m in model_spans))
check("the decision still carries the model's answer, unchanged",
      d.get("ok") and d.get("tool") == "read_registry" and d.get("producer") == "model", str(d))

# The scope fork is what stops a run's conversation id leaking onto the next run
# that lands on this thread: activities share a long-lived thread pool.
leak = FakeSentry()
brain.sentry_sdk = leak
brain.sdk_ai = leak.ai
brain.decide("goal", [], DECIDE_CONFIG, run_id="agent-first")
brain.decide("goal", [], DECIDE_CONFIG, run_id="agent-second")
check("the conversation id is set through the SDK's own API, on a forked scope",
      [s.conversation_id for s in leak.scopes_created] == ["agent-first", "agent-second"],
      str([s.conversation_id for s in leak.scopes_created]))
check("and every fork is closed again, so nothing is left on the thread's scope",
      not leak.scopes and all(s.exited for s in leak.scopes_created),
      f"open scopes: {leak.scopes}")
check("and a second run does not inherit the first one's conversation id",
      [t.children[0].data.get("gen_ai.conversation.id") for t in leak.transactions]
      == ["agent-first", "agent-second"],
      str([t.children[0].data.get("gen_ai.conversation.id") for t in leak.transactions]))

fakeless = FakeSentry()
brain.sentry_sdk = fakeless
brain.sdk_ai = fakeless.ai
brain.decide("goal", [], dict(DECIDE_CONFIG, fallback="on"), run_id=RUN_ID)
labelled = [c for t in fakeless.transactions for c in t.children]
check("the scripted fallback emits no model span at all (it is not a model call)",
      labelled and not any(m.op == "gen_ai.chat" for a in labelled for m in a.children),
      str([(a.op, [m.op for m in a.children]) for a in labelled]))
check("and its agent span says, in its name, that a policy decided",
      labelled and labelled[0].description ==
      f"invoke_agent {brain.AGENT_NAME} [scripted policy, no model call]",
      str(labelled and labelled[0].description))
check("with the producer and the reason as attributes to filter on",
      labelled and (labelled[0].data.get("agent.producer"),
                    labelled[0].data.get("agent.fallback_reason"))
      == ("scripted-policy", "AGENT_FALLBACK=on"),
      str(labelled and labelled[0].data))
check("and it never claims a model was asked anything",
      labelled and not any(k.startswith("gen_ai.request.") or k == "gen_ai.provider.name"
                           for k in labelled[0].data),
      str(labelled and labelled[0].data))

# `off` fails rather than falling back, so its agent span must not claim a policy
# decided — the label is what an operator filters on.
off_case = FakeSentry()
brain.sentry_sdk = off_case
brain.sdk_ai = off_case.ai
real_post = brain._post_json
def _unreachable(*a, **kw):
    raise brain.BrainError("unreachable", "connection refused")
brain._post_json = _unreachable
brain.reset_model_breaker()
d_off = brain.decide("goal", [], dict(DECIDE_CONFIG, fallback="off", base_url="http://127.0.0.1:1"), run_id=RUN_ID)
brain._post_json = real_post
brain.reset_model_breaker()
check("a failed run with fallback=off is not labelled as the policy",
      d_off.get("ok") is False and off_case.transactions
      and "[scripted policy" not in (off_case.transactions[0].children[0].description or ""),
      str((d_off, off_case.transactions and off_case.transactions[0].children[0].description)))

ungrouped = FakeSentry()
brain.sentry_sdk = ungrouped
brain.sdk_ai = ungrouped.ai
d = brain.decide("goal", [], DECIDE_CONFIG)   # no run id: an ungrouped step
check("without a run id the spans are still emitted, just ungrouped",
      ungrouped.transactions and ungrouped.transactions[0].children
      and "gen_ai.conversation.id" not in ungrouped.transactions[0].children[0].data, str(d))

brain.sentry_sdk = RudeSentry()
brain.sdk_ai = None
d2 = brain.decide("goal", [], DECIDE_CONFIG, run_id=RUN_ID)
check("a Sentry that raises cannot fail the run", d2.get("ok") and d2.get("producer") == "model", str(d2))

brain.sentry_sdk = RudeChildSentry()
d3 = brain.decide("goal", [], DECIDE_CONFIG, run_id=RUN_ID)
check("nor can a span that refuses every attribute",
      d3.get("ok") and d3.get("producer") == "model", str(d3))

check("and the conversation API being absent still leaves a usable run",
      brain.sdk_ai is None and d3.get("ok"), str(d3))

brain._post_json = real_post_json
brain.sentry_sdk = real_sentry
brain.sdk_ai = real_sdk_ai

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

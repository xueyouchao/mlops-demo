"""The agent's brain — how exactly one decision gets produced.

One step of the loop is one brain call, so this module has a single job: turn
(goal + transcript) into one decision — which tool to call, with what arguments,
and why — or into a *typed* failure the loop can record as an observation.

Split of responsibilities, per the loop contract:

  * this module **parses tolerantly** and reports what it got;
  * the workflow **validates** the tool name against its allow-list.

So an unknown tool name is deliberately *not* rejected here. Anything that could
not be parsed at all comes back as a typed failure (`truncated`, `no_tool_call`,
`bad_arguments`, `unreachable`, `http_error`, `bad_response`) and never as an
exception the workflow would have to catch.

Stdlib only — no `requests`, no temporalio — so the parsing and the scripted
policy can be exercised on the host without the worker image. The activity
wrapper that needs temporalio lives in `activities.py`.

Two producers share one output contract, by design:

  * `model`            — ollama, native `tools` (measured: T08)
  * `scripted-policy`  — deterministic, used when ollama is unreachable, or
                         forced with AGENT_FALLBACK=on so the fallback can be
                         demonstrated deliberately

Every decision carries its producer, and every fallback decision carries the
reason it fell back, because the demo must never quietly pretend a policy is a
model.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

# The operator's choice (2026-09-13), overriding T08's latency-based pick: it is
# the model DSH itself runs on. Re-measured on the step-6 scenario, 5 runs:
# 5/5 valid tool calls, but p50 12.9 s and max 36.5 s — against
# deepseek-v4-flash:cloud at 5/5, p50 2.0 s, max 2.4 s. It works; it is ~6x
# slower at the median, which is why the run's work ceiling was raised with it
# rather than left where a 2-second model put it. Env-configurable.
DEFAULT_MODEL = "deepseek-v4.1-flash:cloud"

# The host's ollama, reached from containers over the bridge gateway.
# `host.docker.internal` is NOT wired up on this host.
DEFAULT_BASE_URL = "http://172.23.0.1:11434"

# Measured trap (T08): these are reasoning models and the tool call is emitted
# *after* the thinking, so a tight budget is consumed entirely by thinking and
# returns an empty message that looks exactly like an incompetent model.
DEFAULT_NUM_PREDICT = 4096

DEFAULT_TIMEOUT_S = 60

# A failure that took this long already spent the budget; retrying it would
# spend it twice. A refused connection fails in milliseconds and *is* worth one
# retry. Measured on this host: ollama answering is ~0.5–3 s, while a dropped
# SYN (the bridge address from the wrong side) hangs for the whole timeout.
FAST_FAILURE_S = 5.0


# --------------------------------------------------------------------------
# The tool surface. Exactly six, per the tool-surface decision. The brain is
# told about these; the workflow is the thing that enforces them.
# --------------------------------------------------------------------------
def _fn(name: str, description: str, properties: dict | None = None, required: list | None = None) -> dict:
    """One tool schema, with a required `why` on every tool.

    The `why` is not decoration. Measured on the operator's chosen model
    (2026-09-13): it called tools correctly **5/5 times while filling prose
    `content` 0/5 times** — its reasoning goes to `thinking`, which the contract
    deliberately does not record. So a rationale asked for in prose is simply
    absent, and the console shows a reason on every step. Asked for as an
    *argument*, the same model filled it **5/5**. The brain lifts it back out of
    the arguments before the workflow sees them, so the six-tool surface the
    workflow validates against is unchanged.
    """
    props = dict(properties or {})
    props["why"] = {"type": "string", "description": "One sentence: why this call, right now."}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": list(required or []) + ["why"],
            },
        },
    }


TOOL_SCHEMAS = [
    _fn("read_registry",
        "The version table and the serving routing: which versions exist, their stages, whether "
        "each artifact is present, and which version is actually taking traffic."),
    _fn("read_run_metrics",
        "The parameters and metrics of one training run, by run id.",
        {"run_id": {"type": "string", "description": "MLflow run id"}},
        ["run_id"]),
    _fn("evaluate_version",
        "Score one registered version on the held-out split. Always the same split as training, "
        "so numbers from different versions are comparable.",
        {"version": {"type": "string", "description": "model version number"}},
        ["version"]),
    _fn("train_candidate",
        "Train and register a NEW version in Staging from these hyperparameters. Costs about 20 "
        "seconds and one registry entry; an existing version is never modified.",
        {"n_estimators": {"type": "integer"},
         "max_depth": {"type": "integer"},
         "learning_rate": {"type": "number"}},
        ["n_estimators", "max_depth", "learning_rate"]),
    _fn("propose_promotion",
        "File a promotion request for a version. This does NOT promote anything: it asks the "
        "operator, who decides. Only one promotion may be pending per model.",
        {"version": {"type": "string", "description": "model version number"},
         "rationale": {"type": "string", "description": "why this version should serve traffic"}},
        ["version", "rationale"]),
    _fn("conclude",
        "End the investigation with an answer. Use this when the evidence is in, including when "
        "the answer is that no better candidate was found.",
        {"answer": {"type": "string"}, "evidence": {"type": "string"}},
        ["answer", "evidence"]),
]

TOOL_NAMES = [t["function"]["name"] for t in TOOL_SCHEMAS]

SYSTEM_PROMPT = """You are the investigation agent inside an ML model lifecycle platform.

You work one step at a time. On each step you call exactly ONE tool and say why you are calling it.

Rules:
- You have at most 8 steps in total. Spend them deliberately.
- You may read the registry, read a run's metrics, evaluate a version, train one candidate, and file a promotion request.
- You may NOT approve a promotion and you may NOT roll back production. Those decisions belong to the operator.
- Exactly one promotion may be pending per model, so propose once.
- Never call the same tool with the same arguments twice in a row: the run is ended as no_progress if you do.
- Tool arguments must match the schema exactly, with no extra keys. Version arguments are bare numbers: write 6, not v6.
- When the evidence is in, call conclude. Concluding with "no better candidate" is a legitimate, expected result — say so rather than inventing one.
- Every call carries a `why` argument: one sentence on why this call, right now. That is where your reasoning goes — not in prose around the call, and not in private thinking.
- Your reply must be the tool call itself."""


class BrainError(Exception):
    """A decision could not be produced. `kind` is what the loop records."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind

    def as_result(self, **extra) -> dict:
        return {"ok": False, "kind": self.kind, "error": str(self), **extra}


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
def brain_config() -> dict:
    """Everything the brain needs, from the environment with sane defaults."""
    fallback = os.getenv("AGENT_FALLBACK", "auto").strip().lower()
    if fallback not in ("auto", "on", "off"):
        fallback = "auto"
    return {
        "model": os.getenv("AGENT_BRAIN_MODEL", DEFAULT_MODEL),
        "base_url": os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "num_predict": int(os.getenv("AGENT_NUM_PREDICT", str(DEFAULT_NUM_PREDICT))),
        "fallback": fallback,
        "timeout_s": float(os.getenv("AGENT_TIMEOUT_S", str(DEFAULT_TIMEOUT_S))),
    }


# --------------------------------------------------------------------------
# Prompt rendering
# --------------------------------------------------------------------------
def render_transcript(entries: list) -> str:
    """The transcript as the brain sees it. Rationale yes, raw thinking never."""
    if not entries:
        return "(nothing yet — this is your first step)"
    lines = []
    for e in entries:
        args = e.get("arguments") or {}
        arg_text = ", ".join(f"{k}={v!r}" for k, v in args.items())
        lines.append(f"step {e.get('step', '?')} — {e.get('tool', '?')}({arg_text})")
        rationale = (e.get("rationale") or "").strip()
        if rationale:
            lines.append(f"  why: {rationale}")
        observation = (e.get("observation") or "").strip()
        lines.append(f"  observation: {observation or '(none)'}")
        if e.get("producer") == "scripted-policy":
            lines.append("  note: this step was decided by the scripted policy, not by you")
    return "\n".join(lines)


def build_messages(goal: str, entries: list) -> list:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Operator goal: {goal}\n\n"
            f"What has happened so far:\n{render_transcript(entries)}\n\n"
            "Choose the next step."
        )},
    ]


# --------------------------------------------------------------------------
# Tolerant parsing
# --------------------------------------------------------------------------
def parse_response(response: dict) -> dict:
    """Turn one ollama response into a decision, or raise BrainError.

    Tolerant on purpose: a model may return the arguments as a dict, as a JSON
    string, or (occasionally) as nothing at all. All three are handled.
    """
    if response.get("done_reason") == "length":
        # The measured trap: thinking ate the whole budget, so the tool call was
        # never emitted. This is a typed failure, never an empty decision.
        raise BrainError(
            "truncated",
            "the model hit its generation limit before emitting a tool call "
            f"(eval_count={response.get('eval_count')})",
        )

    message = response.get("message") or {}
    calls = message.get("tool_calls") or []
    if not calls:
        raise BrainError("no_tool_call", "the model returned no tool call")

    call = calls[0] or {}
    fn = call.get("function") or {}
    name = fn.get("name")
    if not name:
        raise BrainError("no_tool_call", "the tool call had no function name")

    raw_args = fn.get("arguments")
    if raw_args is None:
        args = {}
    elif isinstance(raw_args, dict):
        args = raw_args
    elif isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError as e:
            raise BrainError("bad_arguments", f"tool arguments were not JSON: {e}") from e
    else:
        raise BrainError("bad_arguments", f"unexpected arguments type: {type(raw_args).__name__}")
    if not isinstance(args, dict):
        raise BrainError("bad_arguments", "tool arguments were not an object")

    args = dict(args)
    # The reason arrives as a required argument; lift it out so the workflow only
    # ever sees the tool's own schema. `thinking` is deliberately never recorded,
    # and prose `content` is used only when the model volunteers it.
    why = str(args.pop("why", "") or "").strip()
    return {
        "ok": True,
        "tool": name,
        "arguments": args,
        "rationale": (message.get("content") or "").strip() or why,
    }


# --------------------------------------------------------------------------
# The model producer
# --------------------------------------------------------------------------
def _post_json(url: str, payload: dict, timeout_s: float, attempts: int = 2) -> dict:
    """POST, retrying only a *fast* failure.

    The rule matters more than it looks. A three-minute run cannot afford to
    repeat a timed-out call: two 60 s attempts per step would blow the whole
    ceiling on the first two steps and the demo would end as budget_exhausted
    with the fallback never exercised.
    """
    body = json.dumps(payload).encode("utf-8")
    last: Exception | None = None
    for attempt in range(attempts):
        started = time.monotonic()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            # A 4xx will not fix itself; a 5xx might.
            if 400 <= e.code < 500:
                raise BrainError("http_error", f"ollama returned HTTP {e.code}: {detail}") from e
            last = BrainError("http_error", f"ollama returned HTTP {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = BrainError("unreachable", f"could not reach ollama: {e}")
        if time.monotonic() - started > FAST_FAILURE_S or attempt + 1 >= attempts:
            break
        time.sleep(0.5)
    raise last if last else BrainError("unreachable", "could not reach ollama")


def ask_model(goal: str, entries: list, config: dict) -> dict:
    """One call to ollama with the six tool schemas. Returns a decision dict."""
    payload = {
        "model": config["model"],
        "messages": build_messages(goal, entries),
        "tools": TOOL_SCHEMAS,
        "stream": False,
        "options": {"num_predict": config["num_predict"]},
    }
    raw = _post_json(f"{config['base_url']}/api/chat", payload, config["timeout_s"])
    decision = parse_response(raw)
    decision["producer"] = "model"
    decision["model"] = config["model"]
    return decision


# --------------------------------------------------------------------------
# The scripted policy producer
# --------------------------------------------------------------------------
# Deterministic, and deliberately small: it exists so the loop still runs when
# ollama is down, not to be clever. It reads only what the transcript already
# shows, and if it cannot read enough to act it concludes honestly rather than
# guessing.
#
# Interface note: this policy reads the *observation digests* to find the
# production version and the accuracy numbers, so those digests must keep
# naming the stage ("Production") and the metrics ("accuracy", "roc_auc").
SCRIPTED_PROBE = {"n_estimators": 300, "max_depth": 6, "learning_rate": 0.05}
_ACCURACY_RE = re.compile(r"accuracy\s*[:=]?\s*([0-9]*\.?[0-9]+)", re.I)
_VERSION_RE = re.compile(r"\bv?(\d+)\b")


def _called(entries: list, tool: str) -> list:
    return [e for e in entries if e.get("tool") == tool]


def _accuracy_of(entries: list, version: str | None = None) -> float | None:
    """Best-effort accuracy from an evaluate_version observation."""
    for e in reversed(_called(entries, "evaluate_version")):
        if version is not None and str((e.get("arguments") or {}).get("version")) != str(version):
            continue
        m = _ACCURACY_RE.search(e.get("observation") or "")
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def _production_version(entries: list) -> str | None:
    """The version currently serving, as named in a read_registry observation."""
    for e in reversed(_called(entries, "read_registry")):
        obs = e.get("observation") or ""
        m = re.search(r"v?(\d+)\s*[:·]?\s*Production", obs, re.I)
        if m:
            return m.group(1)
    return None


def _trained_version(entries: list) -> str | None:
    for e in reversed(_called(entries, "train_candidate")):
        obs = e.get("observation") or ""
        m = re.search(r"\bv?(\d+)\b", obs)
        if m:
            return m.group(1)
    return None


def scripted_decision(goal: str, entries: list) -> dict:
    """A deterministic decision of exactly the same shape as the model's."""
    def out(tool: str, arguments: dict, rationale: str) -> dict:
        return {
            "ok": True, "tool": tool, "arguments": arguments, "rationale": rationale,
            "producer": "scripted-policy", "model": None,
        }

    if not _called(entries, "read_registry"):
        return out("read_registry", {},
                   "Start from what is actually serving traffic, so nothing is judged against a guess.")

    production = _production_version(entries)
    if production is None:
        return out("conclude", {
            "answer": "Cannot proceed: the registry read did not name a version in Production.",
            "evidence": "The scripted policy could not identify the incumbent, so it will not propose a change to it.",
        }, "Without a known incumbent there is nothing to compare against.")

    if not [e for e in _called(entries, "evaluate_version")
            if str((e.get("arguments") or {}).get("version")) == str(production)]:
        return out("evaluate_version", {"version": production},
                   f"Score the incumbent (v{production}) on the same split a candidate would be judged on.")

    if not _called(entries, "train_candidate"):
        return out("train_candidate", dict(SCRIPTED_PROBE),
                   f"The incumbent (v{production}) is the only thing measured so far, so probe one "
                   "deeper candidate with a slower learning rate.")

    candidate = _trained_version(entries)
    if candidate is None:
        return out("conclude", {
            "answer": "Cannot proceed: a candidate was trained but its version is not readable from the transcript.",
            "evidence": "The scripted policy will not propose a version it cannot name.",
        }, "The trained version could not be identified, so nothing can be proposed safely.")

    if _accuracy_of(entries, candidate) is None:
        return out("evaluate_version", {"version": candidate},
                   f"Measure the candidate (v{candidate}) before proposing it.")

    incumbent_acc = _accuracy_of(entries, production)
    candidate_acc = _accuracy_of(entries, candidate)
    if incumbent_acc is not None and candidate_acc is not None and candidate_acc > incumbent_acc:
        return out("propose_promotion", {
            "version": candidate,
            "rationale": f"v{candidate} scored {candidate_acc} against the incumbent v{production} at "
                         f"{incumbent_acc} on the same held-out split.",
        }, f"v{candidate} beats v{production} on the same split, so it is worth the operator's attention.")

    return out("conclude", {
        "answer": "No better candidate found.",
        "evidence": f"Candidate v{candidate} ({candidate_acc}) did not beat the incumbent "
                    f"v{production} ({incumbent_acc}) on the same held-out split.",
    }, "The candidate did not improve on what is already serving, so nothing should be promoted.")


# --------------------------------------------------------------------------
# The one entry point the activity uses
# --------------------------------------------------------------------------
# Per-process breaker: once ollama has been found unreachable, stop paying the
# timeout on every step. Without it a dead daemon costs ~60 s *per step*, the
# run ceiling fires after three steps, and the fallback — the thing that is
# supposed to keep the loop alive — never gets to carry it. Recording the
# outcome in history is what keeps this replay-safe: the workflow never sees the
# breaker, only the decision it produced.
_MODEL_DOWN_UNTIL = 0.0


def _mark_model_down() -> None:
    global _MODEL_DOWN_UNTIL
    _MODEL_DOWN_UNTIL = time.monotonic() + float(os.getenv("AGENT_CIRCUIT_S", "60"))


def _model_down_for() -> float:
    return max(0.0, _MODEL_DOWN_UNTIL - time.monotonic())


def reset_model_breaker() -> None:
    """Clear the breaker, so the next call tries the model again.

    A worker that runs for days should not stay degraded forever, and tests need
    a clean slate after deliberately unreachable checks.
    """
    global _MODEL_DOWN_UNTIL
    _MODEL_DOWN_UNTIL = 0.0


def decide(goal: str, entries: list, config: dict | None = None) -> dict:
    """Produce one decision from (goal + transcript). Never raises for a verdict.

    Order of operations:
      AGENT_FALLBACK=on   -> the scripted policy, always (how the fallback is demoed)
      AGENT_FALLBACK=auto -> the model, falling back when ollama cannot be reached
      AGENT_FALLBACK=off  -> the model only; being unreachable fails the run
    """
    config = config or brain_config()
    started = time.monotonic()

    def finish(result: dict, **extra) -> dict:
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        result.update(extra)
        return result

    if config["fallback"] == "on":
        return finish(scripted_decision(goal, entries),
                      fallback_reason="AGENT_FALLBACK=on")

    if config["fallback"] == "auto":
        down_for = _model_down_for()
        if down_for > 0:
            return finish(scripted_decision(goal, entries),
                          fallback_reason=f"model known unreachable, retrying in {int(down_for)}s")

    try:
        return finish(ask_model(goal, entries, config))
    except BrainError as e:
        # A truncated or unparseable answer is a verdict about the model, not an
        # infrastructure failure: the loop records it and spends a step.
        if e.kind not in ("unreachable", "http_error"):
            return finish(e.as_result(producer="model", model=config["model"]))
        if e.kind == "unreachable":
            _mark_model_down()
        if config["fallback"] == "off":
            return finish(e.as_result(producer="model", model=config["model"]))
        return finish(scripted_decision(goal, entries),
                      fallback_reason=f"{e.kind}: {e}", model=config["model"])

"""The estimator kinds the trainer offers — one vocabulary, in one place.

Why this module exists: `train_candidate` used to *be* one estimator with three
fixed numbers, and that shape — not the estimator — was what stopped a second
family being added. The kinds, their parameters, their bounds and their
construction live here, so the brain's tool schema, the tool's validation, the
trainer's build *and* the api's request boundary all read one source and cannot
drift apart.

Why it lives in the shared package rather than in `services/worker/`: choosing a
family became something a **human** does too, and the console must not be handed a
second copy of these numbers. A panel that hardcodes three knobs *is* the asymmetry
this module closes — the agent could pick a family, the operator could not — and a
panel whose bounds drifted from the trainer's would offer inputs the trainer
refuses. `services/api/app/routes.py` imports this both to validate a `TrainRequest`
and to *generate* the panel's inputs, so both images ship it: `packages/ml_platform`
is already copied into the api, worker and serving images, beside
`registry_health.py`, the other cross-service module. Nothing here is api-specific
and nothing here is worker-specific — it is the trainer's vocabulary.

**Stdlib only at import time** (scikit-learn is imported inside `build`), for two
reasons now: `brain.py` imports this to *describe* the kinds to the model and must
stay runnable on the host without the worker image, and the api image does not
install scikit-learn at all. It is the same reason `brain.py` carries no
third-party imports of its own.

Two kinds, deliberately different inductive bias:

  * `gradient_boosting` — the trainer's original estimator: boosted trees, which
    can split and interact features, and whose three numbers are the knobs the
    console's Train panel sent before it could name a family at all.
  * `logistic_regression` — a linear model on **standardized** features. It cannot
    represent a split or an interaction at all, so agreeing with the trees is
    evidence about the data rather than about a re-tuned copy of the same model.
    The scaler is not decoration: on these raw features (areas in the thousands
    beside smoothness in the hundredths) lbfgs needs ~1000 iterations and still
    reports non-convergence, while the same fit on scaled features converges in
    ~19 — measured on this dataset, 2026-09-14.

Adding a kind means adding one entry here: the tool schema, the per-kind
validation, the trainer's build, the api's request validation and the console
panel's inputs all follow from it.
"""
from __future__ import annotations

import json
import math

# Parameter specs: `type`/`json_type` say what the model must send, `min`/`max`
# are the honest bounds validation enforces (not documentation), and `default` is
# what an omitted parameter becomes. The gradient-boosting defaults are the
# trainer's original ones, unchanged, so an unqualified training call behaves
# exactly as it did before this module existed.
KINDS: dict[str, dict] = {
    "gradient_boosting": {
        "summary": "boosted decision trees — the trainer's original estimator; can split "
                   "and interact features, slower to train than the linear model",
        "params": {
            "n_estimators": {
                "type": "integer", "json_type": "integer", "default": 120,
                "min": 10, "max": 1000,
                "description": "number of boosting stages (more is slower, not always better)",
            },
            "max_depth": {
                "type": "integer", "json_type": "integer", "default": 3,
                "min": 1, "max": 10,
                "description": "depth of each tree, i.e. the interaction order it can learn",
            },
            "learning_rate": {
                "type": "number", "json_type": "number", "default": 0.08,
                "min": 0.0, "max": 1.0, "exclusive_min": True,
                "description": "shrinkage applied to each stage",
            },
        },
    },
    "logistic_regression": {
        "summary": "a linear model on standardized features — cannot split or interact "
                   "features, which is the point of having it beside the trees; trains "
                   "in milliseconds",
        "params": {
            "C": {
                "type": "number", "json_type": "number", "default": 1.0,
                "min": 0.001, "max": 1000.0,
                "description": "inverse regularization strength: smaller is more regularized",
            },
            "max_iter": {
                "type": "integer", "json_type": "integer", "default": 200,
                "min": 10, "max": 2000,
                "description": "solver iterations — the features are scaled, so this is generous",
            },
        },
    },
}

# The kind an unqualified call means: the one this trainer has always been.
DEFAULT_KIND = "gradient_boosting"


def kind_names() -> list[str]:
    return list(KINDS)


def spec(kind: str) -> dict | None:
    return KINDS.get((kind or "").strip())


def is_known(kind: str) -> bool:
    return spec(kind) is not None


def param_names(kind: str) -> list[str]:
    """The parameter names of one kind — for logging, digests and the run lookup."""
    found = spec(kind)
    return list(found["params"]) if found else []


def default_params(kind: str) -> dict:
    found = spec(kind)
    if not found:
        return {}
    return {name: p["default"] for name, p in found["params"].items()}


def _allowed(pspec: dict) -> str:
    lo, hi = pspec.get("min"), pspec.get("max")
    if pspec.get("exclusive_min"):
        return f"greater than {lo} and at most {hi}"
    if lo is not None and hi is not None:
        return f"between {lo} and {hi}"
    return "any number"


def _one(kind: str, name: str, pspec: dict, value) -> tuple[object | None, str | None]:
    """Coerce and bound one parameter, or say plainly why it cannot be used."""
    if isinstance(value, bool):  # bool is an int in Python; a flag is not a number here
        return None, f"{name} for {kind} must be a number, got a boolean"
    if pspec["type"] == "integer":
        # 200, "200" and 200.0 are the same instruction; 3.7 and "many" are not.
        if isinstance(value, int):
            number = value
        else:
            try:
                as_float = float(str(value).strip())
            except Exception:
                return None, f"{name} for {kind} must be a whole number, got {value!r}"
            if not as_float.is_integer():
                return None, f"{name} for {kind} must be a whole number, got {value!r}"
            number = int(as_float)
    else:
        try:
            number = float(value)
        except Exception:
            return None, f"{name} for {kind} must be a number, got {value!r}"
        if not math.isfinite(number):  # nan passes every comparison below
            return None, f"{name} for {kind} must be a finite number, got {value!r}"
    lo, hi = pspec.get("min"), pspec.get("max")
    if pspec.get("exclusive_min"):
        if not number > lo:
            return None, f"{name} for {kind} must be {_allowed(pspec)}, got {value!r}"
    else:
        if (lo is not None and number < lo) or (hi is not None and number > hi):
            return None, f"{name} for {kind} must be {_allowed(pspec)}, got {value!r}"
    return number, None


def coerce(kind: str | None, raw) -> tuple[dict | None, str | None]:
    """Validate a `model_kind` and its parameters, or return why they cannot be used.

    Returns `(params, None)` — every parameter the kind takes, coerced, in spec
    order — or `(None, message)`. The message is written to be *read by the
    model*: an unseen call is an observation it can correct in one step, so it
    names the kind's real parameters rather than saying "invalid arguments".

    Tolerant where tolerance teaches nothing: an omitted parameter takes its
    default, and `params` may arrive as a JSON string, because tool-calling models
    nested objects through a string often enough that punishing the notation would
    be a trap with extra steps (the same reason `version` tolerates a `v` prefix).
    """
    found = spec(kind or "")
    if found is None:
        if not (kind or "").strip():
            return None, (f"needs a model_kind — one of {', '.join(kind_names())}, "
                          f"with that kind's parameters in `params`")
        return None, f"unknown model_kind {kind!r} — this trainer has {', '.join(kind_names())}"
    kind = (kind or "").strip()
    names = ", ".join(found["params"])

    if raw is None or raw == "":
        raw = {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None, (f"params for {kind} arrived as text that is not JSON "
                          f"({raw[:60]!r}) — send it as an object of its parameters ({names})")
    if not isinstance(raw, dict):
        return None, (f"params for {kind} must be an object of its parameters ({names}), "
                      f"got {type(raw).__name__}")
    unknown = sorted(k for k in raw if k not in found["params"])
    if unknown:
        return None, (f"{kind} has no parameter {', '.join(unknown)} — it takes {names} "
                      f"(another kind's parameters are not silently ignored)")

    out: dict = {}
    for name, pspec in found["params"].items():
        value, problem = _one(kind, name, pspec, raw.get(name, pspec["default"]))
        if problem:
            return None, problem
        out[name] = value
    return out, None


def resolve_request(kind: str | None, params: dict | None = None,
                    knobs: dict | None = None) -> tuple[str, dict | None, str | None]:
    """Resolve a request in either shape — the console's, old or new — into one call.

    Returns `(kind, params, None)`, or `(kind, None, message)` saying why it cannot
    be trained. This is `coerce` plus the one merge rule that keeps the pre-kind
    request working, which is why it lives here rather than in the api: the rule is
    about the trainer's vocabulary — "a knob that was sent is that kind's
    parameter, and one that was not sent is *absent*, not a value to overwrite
    with" — and the api, the seed of a future caller, and the tests all read it
    from one place.

    `knobs` is the trainer's original top-level shape: `n_estimators`, `max_depth`
    and `learning_rate` sent as three numbers, which is what every caller written
    before a kind could be chosen still sends. Passing them is not a second code
    path: they are `gradient_boosting`'s parameters, so they merge into `params`
    and are validated, defaulted and refused exactly like any other call.

    A `params` that is not an object (a JSON string, say) is handed to `coerce`
    unchanged, which is what the *agent's* calls rely on; the knobs then do not
    apply, which cannot happen through the api — its `TrainRequest` types `params`
    as an object, so the two shapes cannot both arrive malformed.
    """
    name = (kind or "").strip() or DEFAULT_KIND
    merged = params
    if merged is None or isinstance(merged, dict):
        merged = dict(merged or {})
        for knob, value in (knobs or {}).items():
            if value is not None:  # an omitted knob takes the kind's default, as before
                merged[knob] = value
    resolved, problem = coerce(name, merged)
    return name, resolved, problem


def catalog() -> dict:
    """The kinds as JSON-ready data, for a console that has to show the truth.

    The Train panel is *generated* from this rather than carrying its own copy of
    the parameters, bounds and defaults: what it shows is then, by construction,
    what the trainer accepts. That is the whole point of the panel — before this,
    the three inputs were a hardcoded copy of one kind's knobs, so a human could
    not even *name* the second family, let alone parameterize it.

    Every key of every parameter spec is represented (`type` excepted: it is the
    Python-side name of `json_type`, and the console sends JSON), and the test
    suite checks that — a spec key that stopped being carried here would be a
    parameter the panel silently stopped offering.
    """
    return {
        "default_kind": DEFAULT_KIND,
        "kinds": [
            {
                "kind": kind,
                "summary": KINDS[kind]["summary"],
                "params": [
                    {
                        "name": name,
                        "json_type": pspec["json_type"],
                        "default": pspec["default"],
                        "min": pspec.get("min"),
                        "max": pspec.get("max"),
                        "exclusive_min": bool(pspec.get("exclusive_min", False)),
                        "description": pspec["description"],
                    }
                    for name, pspec in KINDS[kind]["params"].items()
                ],
            }
            for kind in kind_names()
        ],
    }


def build(kind: str, params: dict, random_state: int):
    """The estimator for one (kind, params) pair. scikit-learn is imported here, lazily.

    The seed comes from the trainer, not from this module: the split and the seed
    are the trainer's own constants, and comparability of every number in the
    registry depends on them being one thing in one place.
    """
    if kind == "gradient_boosting":
        from sklearn.ensemble import GradientBoostingClassifier

        return GradientBoostingClassifier(
            n_estimators=params["n_estimators"],
            max_depth=params["max_depth"],
            learning_rate=params["learning_rate"],
            random_state=random_state,
        )
    if kind == "logistic_regression":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        return Pipeline([
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(
                C=params["C"], max_iter=params["max_iter"], random_state=random_state,
            )),
        ])
    raise ValueError(f"unknown model_kind {kind!r} — cannot build an estimator")


def describe() -> str:
    """The kinds in one paragraph, for the brain's tool description.

    Generated rather than written out, so a parameter added here is a parameter the
    model is told about — the failure this prevents is silent: a kind the tool
    accepts but the description never mentions is a kind the agent will not use.
    """
    parts = []
    for kind in kind_names():
        found = KINDS[kind]
        params = "; ".join(
            f"{name} ({_allowed(p)}, default {p['default']})"
            for name, p in found["params"].items()
        )
        parts.append(f'"{kind}" — {found["summary"]}. Parameters: {params}.')
    return " ".join(parts)


def params_schema() -> dict:
    """The `params` object as a JSON-schema property, for the model to fill in.

    The properties are the union of every kind's parameters, each labelled with the
    kind it belongs to; the description says outright that only the chosen kind's
    belong in one call. A refusal that names the right ones is a one-step
    correction, which is why validation is allowed to be strict here.
    """
    properties = {}
    for kind in kind_names():
        for name, pspec in KINDS[kind]["params"].items():
            properties[name] = {
                "type": pspec["json_type"],
                "description": (f"{name} for {kind}: {pspec['description']}; "
                                f"{_allowed(pspec)}, default {pspec['default']}"),
            }
    per_kind = " ".join(f"{kind} = {', '.join(found['params'])}"
                        for kind, found in KINDS.items())
    return {
        "type": "object",
        "description": ("Exactly the chosen model_kind's parameters and no others — "
                        f"{per_kind}. Omit one and it takes that kind's default."),
        "properties": properties,
    }

"""The agent's six tools, each an activity.

Every tool is an activity — the loop contract's deliberate divergence — so the
workflow never touches the registry, the serving router or the Temporal client
itself. Each returns a **bounded digest**: a short line the transcript and the
next prompt can carry. History is where the transcript lives, so its size is the
budget, and a raw payload has no business in it.

Two kinds of non-success, and the difference is the whole point (T02 decision 5):

  * a **verdict** — a refusal, an unknown version, a promotion already pending —
    comes back as a typed envelope, so the brain *observes* it and adapts;
  * an **infrastructure failure** raises, so the retry policy applies.

A verdict must never be retried and a blip must be, which is why they are
distinguishable here rather than collapsed into one error shape.

Read-only boundary: there is no tool that approves a promotion and none that
rolls back production. The agent can propose; only a human can promote.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.request

import mlflow
import mlflow.sklearn
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient
from temporalio import activity
from temporalio.client import Client as TemporalClient
from temporalio.exceptions import WorkflowAlreadyStartedError

from ml_platform.registry_health import artifact_problem

# The same constants and the same trainer, deliberately shared rather than
# re-stated: comparability of numbers depends on it, and `_data_hash` is what
# makes a retried training recognisable as the same training.
from activities import RANDOM_STATE, TEST_SIZE, _data_hash, train_and_register

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
SERVING_URL = os.getenv("SERVING_URL", "http://serving:8001").rstrip("/")
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "temporal")
TEMPORAL_PORT = int(os.getenv("TEMPORAL_PORT", "7233"))

# Matches the name the api's read model uses (`mr.Model("breast-cancer-classifier")`),
# so the agent and the console are looking at the same model.
MODEL_NAME = os.getenv("MODEL_NAME", "breast-cancer-classifier")

TASK_QUEUE = "ml-lifecycle"

# Training is capped per run (T02 decision 4). The workflow owns the counter and
# must enforce it — this is only the last line of defence for a direct call,
# mirroring how `promote_stage` re-checks servability the api already checked.
MAX_TRAININGS_PER_RUN = 2


def _client() -> MlflowClient:
    return MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)


def _version_arg(payload: dict) -> str:
    """The version the brain asked for, as a bare number.

    The digests write versions as `v6`, and the model faithfully passes `v6`
    straight back. Stripping the prefix is not laxness: the first real run spent
    a step on `there is no vv5`, and a tool that punishes the notation it taught
    is just a trap with extra steps.
    """
    return str(payload.get("version") or "").strip().lstrip("vV").strip()


def _verdict(kind: str, message: str, **extra) -> dict:
    """An expected refusal: the brain reads this and adapts. Never retried."""
    return {"ok": False, "kind": kind, "digest": message, "error": message, **extra}


def _ok(digest: str, **fields) -> dict:
    return {"ok": True, "kind": "ok", "digest": digest, **fields}


def _stage(mv) -> str:
    return (mv.current_stage or "None").strip() or "None"


def _run_metrics(client: MlflowClient, run_id: str) -> dict:
    """Metrics logged by the training run, or {} if the run cannot be read."""
    if not run_id:
        return {}
    try:
        return dict(client.get_run(run_id).data.metrics)
    except Exception:
        return {}


def _fmt(value) -> str:
    return f"{value:.4f}" if isinstance(value, float) else str(value)


def _serving_routing() -> dict:
    """What the serving router is *actually* doing, read from serving itself.

    Deliberately not from the api's in-memory policy: the question the agent is
    asking is what is live right now, and the serving process is the authority.
    """
    try:
        with urllib.request.urlopen(f"{SERVING_URL}/v1/routing", timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"unreadable": type(e).__name__}


# --------------------------------------------------------------------------
# read_registry
# --------------------------------------------------------------------------
@activity.defn
def read_registry(payload: dict | None = None) -> dict:
    """The version table plus the serving routing, so one call establishes what is live.

    Accuracy comes from each version's training run rather than by loading its
    artifact: it is the number the run recorded, it is cheap, and `evaluate_version`
    exists for the case where a comparable re-measurement is what matters.
    """
    client = _client()
    try:
        versions = sorted(
            client.search_model_versions(f"name='{MODEL_NAME}'"),
            key=lambda mv: int(mv.version) if str(mv.version).isdigit() else 0,
        )
    except MlflowException as e:
        raise RuntimeError(f"the registry is unreadable: {e}") from e

    rows = []
    for mv in versions:
        problem = artifact_problem(MLFLOW_TRACKING_URI, MODEL_NAME, str(mv.version))
        metrics = _run_metrics(client, mv.run_id)
        rows.append({
            "version": str(mv.version),
            "stage": _stage(mv),
            "run_id": mv.run_id or "",
            "accuracy": metrics.get("accuracy"),
            "roc_auc": metrics.get("roc_auc"),
            "artifact_problem": problem,
        })

    routing = _serving_routing()
    weights = routing.get("weights") or {}
    parts = [f"{len(rows)} versions of {MODEL_NAME}"]
    for r in rows:
        acc = f" acc {_fmt(r['accuracy'])}" if r["accuracy"] is not None else ""
        flag = " artifact-MISSING" if r["artifact_problem"] else ""
        parts.append(f"v{r['version']} {r['stage']}{acc}{flag}")
    if weights:
        parts.append("serving routing " + ", ".join(f"v{k}:{v}%" for k, v in sorted(weights.items())))
    elif routing.get("unreadable"):
        parts.append(f"serving routing unreadable ({routing['unreadable']})")
    else:
        parts.append("serving routing EMPTY — nothing is taking traffic")

    return _ok(" · ".join(parts), versions=rows, routing=routing)


# --------------------------------------------------------------------------
# read_run_metrics
# --------------------------------------------------------------------------
@activity.defn
def read_run_metrics(payload: dict) -> dict:
    """One run's parameters and metrics — the incumbent's hyperparameters, which
    is what makes a candidate deliberate rather than random."""
    run_id = str(payload.get("run_id") or "")
    if not run_id:
        return _verdict("bad_arguments", "read_run_metrics needs a run_id")
    client = _client()
    try:
        run = client.get_run(run_id)
    except MlflowException as e:
        return _verdict("unknown_run", f"no run {run_id} in the registry ({type(e).__name__})")

    params = dict(run.data.params)
    metrics = dict(run.data.metrics)
    duration_s = None
    if run.info.start_time and run.info.end_time:
        duration_s = round((run.info.end_time - run.info.start_time) / 1000, 1)

    wanted = ["n_estimators", "max_depth", "learning_rate", "random_state", "test_size", "data_hash", "requested_by"]
    param_text = " ".join(f"{k}={params[k]}" for k in wanted if k in params)
    metric_text = " ".join(f"{k}={_fmt(v)}" for k, v in sorted(metrics.items()))
    digest = f"run {run_id[:8]} ({run.data.tags.get('mlflow.runName', 'unnamed')}) · params {param_text} · metrics {metric_text}"
    if duration_s is not None:
        digest += f" · took {duration_s}s"
    return _ok(digest, run_id=run_id, params=params, metrics=metrics, duration_s=duration_s)


# --------------------------------------------------------------------------
# evaluate_version
# --------------------------------------------------------------------------
@activity.defn
def evaluate_version(payload: dict) -> dict:
    """Score a registered version on the held-out split the trainer used.

    Loading the model is safe *here* in a way it is not in the api: this image
    pins the same scikit-learn as the trainer (see requirements.txt), so
    unpickling cannot reject a good model over a dependency mismatch.

    The digest carries a four-decimal `accuracy <n>` because that is the figure
    the scripted policy parses out of the transcript when it compares a candidate
    against the incumbent.
    """
    version = _version_arg(payload)
    if not version:
        return _verdict("bad_arguments", "evaluate_version needs a version")

    # Existence is checked *before* reachability on purpose: `artifact_problem`
    # deliberately collapses "no such version" into "cannot be read" (its
    # docstring says so, and for a promotion guard that is the right answer).
    # Here the difference is evidence the brain acts on — a version it invented is
    # a different mistake from a version whose artifact is gone, and calling the
    # first one an artifact problem sends it hunting for a broken registry.
    try:
        _client().get_model_version(MODEL_NAME, version)
    except MlflowException:
        return _verdict("unknown_version", f"there is no v{version} of {MODEL_NAME}")

    problem = artifact_problem(MLFLOW_TRACKING_URI, MODEL_NAME, version)
    if problem:
        return _verdict("artifact_problem", f"v{version} cannot be evaluated: {problem}")

    try:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}/{version}")
    except Exception as e:
        message = str(e)
        if "not found" in message.lower() or "does not exist" in message.lower():
            return _verdict("unknown_version", f"there is no v{version} of {MODEL_NAME}")
        # Unreadable artifact under a successful reachability check: not this
        # tool's verdict to invent, so it raises and the retry policy applies.
        raise

    from sklearn.datasets import load_breast_cancer
    from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
    from sklearn.model_selection import train_test_split

    data = load_breast_cancer()
    X, y = data.data, data.target
    _, X_test, _, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    pred = model.predict(X_test)
    proba = model.predict_proba(X_test)[:, 1]
    metrics = {
        "accuracy": float(accuracy_score(y_test, pred)),
        "roc_auc": float(roc_auc_score(y_test, proba)),
        "precision": float(precision_score(y_test, pred)),
        "recall": float(recall_score(y_test, pred)),
    }
    digest = (
        f"v{version} · accuracy {metrics['accuracy']:.4f} · roc_auc {metrics['roc_auc']:.4f} · "
        f"precision {metrics['precision']:.4f} · recall {metrics['recall']:.4f} "
        f"(held-out split: test_size {TEST_SIZE}, random_state {RANDOM_STATE}, n={len(y_test)})"
    )
    return _ok(digest, version=version, metrics=metrics, n_test=int(len(y_test)))


# --------------------------------------------------------------------------
# train_candidate
# --------------------------------------------------------------------------
def _version_already_trained(client: MlflowClient, params: dict, data_hash: str) -> str | None:
    """The version this exact training already produced, if it exists.

    This is what makes a killed-and-retried step harmless. Training is the one
    expensive call, and an activity retry after a worker death re-runs it from
    the top — so without this lookup a mistimed kill leaves two versions where
    the demo claims one. The lookup is on the run's own logged parameters, which
    `train_and_register` writes before it registers anything.
    """
    experiment = client.get_experiment_by_name(MODEL_NAME)
    if experiment is None:
        return None
    clause = " and ".join([
        f"params.data_hash = '{data_hash}'",
        f"params.n_estimators = '{params['n_estimators']}'",
        f"params.max_depth = '{params['max_depth']}'",
        f"params.learning_rate = '{params['learning_rate']}'",
    ])
    try:
        runs = client.search_runs([experiment.experiment_id], filter_string=clause,
                                  order_by=["attributes.start_time DESC"], max_results=1)
    except MlflowException:
        return None
    if not runs:
        return None
    run_id = runs[0].info.run_id
    existing = client.search_model_versions(f"name='{MODEL_NAME}' and run_id='{run_id}'")
    return str(existing[0].version) if existing else None


@activity.defn
def train_candidate(payload: dict) -> dict:
    """Train and register a candidate in Staging, reusing the trainer unchanged.

    Idempotent on (data, hyperparameters): a retry of the same step returns the
    version the first attempt registered instead of registering a second one.
    """
    try:
        params = {
            "n_estimators": int(payload["n_estimators"]),
            "max_depth": int(payload["max_depth"]),
            "learning_rate": float(payload["learning_rate"]),
        }
    except (KeyError, TypeError, ValueError) as e:
        return _verdict("bad_arguments", f"train_candidate needs n_estimators, max_depth and learning_rate: {e}")

    attempt = int(payload.get("attempt") or 0)
    if attempt >= MAX_TRAININGS_PER_RUN:
        return _verdict(
            "training_cap_reached",
            f"this run has already trained {attempt} candidates (cap {MAX_TRAININGS_PER_RUN}); "
            "propose what you have or conclude",
        )

    from sklearn.datasets import load_breast_cancer
    data = load_breast_cancer()
    data_hash = _data_hash(data.data, data.target)

    client = _client()
    existing = _version_already_trained(client, params, data_hash)
    if existing:
        metrics = _run_metrics(client, client.get_model_version(MODEL_NAME, existing).run_id)
        return _ok(
            f"v{existing} already exists for exactly these hyperparameters and this data — "
            f"reused, no new version registered · accuracy {_fmt(metrics.get('accuracy'))}",
            version=existing, stage="Staging", resumed=True, metrics=metrics, params=params,
        )

    result = train_and_register({
        "model_name": MODEL_NAME,
        **params,
        "requested_by": payload.get("requested_by") or "agent",
    })
    digest = (
        f"v{result['version']} registered in Staging · accuracy {result['accuracy']} · "
        f"roc_auc {result['roc_auc']} · run {result['run_id'][:8]} · artifact present"
    )
    return _ok(digest, version=str(result["version"]), stage=result.get("stage", "Staging"),
               run_id=result["run_id"], metrics={"accuracy": result["accuracy"], "roc_auc": result["roc_auc"]},
               params=params, resumed=False)


# --------------------------------------------------------------------------
# propose_promotion
# --------------------------------------------------------------------------
class PromotionPending(RuntimeError):
    """A promotion for this model is already awaiting the operator."""


async def _pending_promotion_for_model(client: TemporalClient) -> str | None:
    """The id of any promotion of this model still awaiting a human (T05 dec. 3).

    Per *model*, not per version: the console should hold one pending decision,
    not a queue to triage, and re-running the demo must not stack up stale ones.
    """
    query = (
        f'WorkflowId STARTS_WITH "promote-{MODEL_NAME}-" '
        'AND ExecutionStatus = "Running"'
    )
    async for wf in client.list_workflows(query=query):
        return wf.id
    return None


async def _start_promotion(version: str, inp: dict) -> str:
    client = await TemporalClient.connect(f"{TEMPORAL_HOST}:{TEMPORAL_PORT}")
    pending = await _pending_promotion_for_model(client)
    if pending:
        raise PromotionPending(pending)
    handle = await client.start_workflow(
        "PromotionWorkflow",
        {
            "version_id": version,
            "model_name": MODEL_NAME,
            "requested_by": inp.get("requested_by") or "agent",
            "agent_run_id": inp.get("run_id") or "",
            "rationale": inp.get("rationale") or "",
            "candidate_metrics": inp.get("candidate_metrics"),
            "incumbent_metrics": inp.get("incumbent_metrics"),
        },
        # The API's convention, unchanged: the console's discovery and its
        # Approve button work off this id, and it doubles as a duplicate guard.
        id=f"promote-{MODEL_NAME}-{version}",
        task_queue=TASK_QUEUE,
    )
    return handle.id


@activity.defn
def propose_promotion(payload: dict) -> dict:
    """File a promotion request. This promotes nothing — it asks the operator.

    The servability pre-check runs *first*, so an unreadable artifact is refused
    as an observation and no human is ever asked to approve something that cannot
    work. That ordering is the whole point: otherwise the operator approves and
    only then watches it fail.
    """
    version = _version_arg(payload)
    rationale = (payload.get("rationale") or "").strip()
    if not version:
        return _verdict("bad_arguments", "propose_promotion needs a version")
    if not rationale:
        return _verdict("bad_arguments", "propose_promotion needs a rationale — the operator reads it")

    # Same existence-before-reachability ordering as evaluate_version, for the
    # same reason: "you invented v999" must not read as "the artifacts are broken".
    try:
        _client().get_model_version(MODEL_NAME, version)
    except MlflowException:
        return _verdict("unknown_version", f"there is no v{version} of {MODEL_NAME} to propose",
                        version=version)

    problem = artifact_problem(MLFLOW_TRACKING_URI, MODEL_NAME, version)
    if problem:
        return _verdict(
            "artifact_problem",
            f"refusing to ask the operator about v{version}: {problem}. "
            "It cannot serve traffic, so there is nothing to decide.",
            version=version,
        )

    try:
        workflow_id = asyncio.run(_start_promotion(version, payload))
    except PromotionPending as e:
        return _verdict(
            "already_pending",
            f"a promotion for {MODEL_NAME} is already awaiting the operator ({e}); "
            "conclude on that one instead of filing another",
            version=version,
        )
    except WorkflowAlreadyStartedError:
        return _verdict(
            "already_pending",
            f"a promotion for v{version} is already in progress",
            version=version,
        )

    return _ok(
        f"promotion of v{version} filed · now awaiting operator approval · workflow {workflow_id}",
        version=version, workflow_id=workflow_id, status="awaiting_approval",
    )


# --------------------------------------------------------------------------
# conclude
# --------------------------------------------------------------------------
@activity.defn
def conclude(payload: dict | None = None) -> dict:
    """Terminal. There is no I/O here; it is an activity only because the loop
    contract says every tool is one, so a step is always the same shape."""
    payload = payload or {}
    answer = (payload.get("answer") or "").strip()
    evidence = (payload.get("evidence") or "").strip()
    if not answer:
        return _verdict("bad_arguments", "conclude needs an answer")
    return _ok(f"concluded: {answer}" + (f" · evidence: {evidence}" if evidence else ""),
               answer=answer, evidence=evidence)


# --------------------------------------------------------------------------
# Loop plumbing — not a tool, and never offered to the brain
# --------------------------------------------------------------------------
@activity.defn
def promotion_outcome(payload: dict) -> dict:
    """How a promotion the agent filed actually ended, read from Temporal.

    The loop's fast path is the signal `PromotionWorkflow` sends when it finishes.
    This is the slow path, for a promotion that ended *without* signalling —
    terminated, or failed before it could. Without it a termined promotion leaves
    the agent run waiting forever for an approval that can never arrive, which is
    not hypothetical: it is what the wedged v4 promotion would have done.
    """
    workflow_id = str(payload.get("workflow_id") or "")
    if not workflow_id:
        return {"status": "UNKNOWN", "error": "no workflow_id"}

    async def probe() -> dict:
        client = await TemporalClient.connect(f"{TEMPORAL_HOST}:{TEMPORAL_PORT}")
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
        status = desc.status.name if desc.status is not None else "UNKNOWN"
        state: dict = {"workflow_id": workflow_id, "status": status}
        if status == "COMPLETED":
            state["outcome"] = await handle.result()
        return state

    try:
        return asyncio.run(probe())
    except Exception as e:
        return {"workflow_id": workflow_id, "status": "NOT_FOUND", "error": str(e)[:200]}

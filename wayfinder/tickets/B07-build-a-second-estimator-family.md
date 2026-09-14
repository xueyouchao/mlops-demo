---
id: B07
title: Build a second estimator family behind the train_candidate tool
labels: [wayfinder:build]
status: open
assignee: "dsh session"
blocked-by: [B03]
---

## Scope

A second estimator family behind the same tool, because the constraint was never the estimator and always the interface: `train_candidate` *was* one estimator with three fixed numbers, so "try a different kind of model" was not a call the agent could make and no version could say which family produced it.

- `model_kind` + a validated `params` object replace the three flat hyperparameters, with **per-kind validation** (unknown kinds, another kind's parameters, out-of-range values) returning a *verdict* the brain corrects in one step.
- Two kinds with deliberately different inductive bias: `gradient_boosting` (the trainer's original) and `logistic_regression` (a linear model on standardized features). A linear model cannot represent a split or an interaction, so agreeing with the trees says something about the data rather than about a re-tuned copy of the same model.
- The tool description is **generated from the kinds**, so a kind the trainer accepts is a kind the model is told about — the silent failure this prevents is a kind that exists but is never chosen.
- `read_run_metrics` reports an incumbent's kind and parameters, which is what lets the agent choose a family deliberately.

Invariants this build must not move: **one registry model name** (`breast-cancer-classifier` — both kinds log under it), **idempotency keyed on dataset + `model_kind` + params**, the **two-trainings-per-run cap**, and the **existing metrics** (`accuracy`, `roc_auc`) so the console and the agent's digest need no change.

**Done when:** both kinds train through the agent and register under the same model name, a repeat of identical parameters reuses the version rather than registering a second one, the cap still bites, the console reads both, and serving loads either artifact.

**Read with:** [Define the agent's tool surface & schemas](../tickets/T02-define-the-agent-tool-surface-and-schemas.md) (its second amendment is this build's interface), [Lock the run semantics](../tickets/T06-lock-the-run-semantics.md) (the cap and idempotency), [Build the six tool activities](../tickets/B03-build-the-six-tool-activities.md) (the trainer as built).

**Not** the map's out-of-scope *multi-model genericity*: there is still one model name, one registry, one promotion gate and one serving route. What varies is the estimator family behind the tool.

## Outcome

Built and verified live, 2026-09-14. Files: `services/worker/model_kinds.py` (new — the kinds, their parameters and bounds, `coerce` for validation, `build` for construction, `describe`/`params_schema` for the schema), `services/worker/activities.py` (`train_and_register` takes `model_kind` + `params`, logs the kind and each of its parameters, still logs `accuracy`/`roc_auc`), `services/worker/tools.py` (`train_candidate` validates per kind and returns verdicts; the idempotency lookup is keyed on data + kind + params; `read_run_metrics` reports the kind's parameters), `services/worker/workflows.py` (`TrainingWfInput` carries kind + params, the console's three knobs map onto that kind's parameters), `services/worker/brain.py` (tool schema and one prompt rule generated from the kinds; the scripted probe is a call in the new shape), `services/worker/Dockerfile` (COPY the new module), `services/worker/test_brain.py` (+26 checks, before/after below), `README.md`.

**Both kinds, through the agent, one model name.** Run `agent-52f3be65` (7 steps, 23.2 s, producer `model`) trained `gradient_boosting` (`n_estimators=250, max_depth=3, learning_rate=0.06`) → **v44** · accuracy 0.9561 · roc_auc 0.9914, then `logistic_regression` (`C=0.5, max_iter=300`) → **v45** · accuracy 0.9825 · roc_auc 0.9957, evaluated both plus the incumbent v18 (0.8860 / 0.9471) and proposed v45 with the kind named in its rationale: *"v45 (logistic_regression, C=0.5, max_iter=300) … beats current production v18 on the identical held-out split"*. MLflow shows both under `breast-cancer-classifier` with `model_kind` and that kind's parameters as run params (`runName` `retrain-agent:agent-52f3be65-gradient_boosting` / `…-logistic_regression`), and the same two metric keys as every older version.

**Idempotency, on the new key.** A second run (`agent-3c12b055`) repeating the identical two calls got *"v44 already exists for exactly this model_kind and these parameters on this data — reused, no new version registered"* and the same for v45 — no new versions, same ids. The migration case is covered by the same lookup: re-asking for **v43**'s parameters (trained before `model_kind` existed, so its run has no such param) reused v43, which is why a missing `model_kind` is read as `gradient_boosting` rather than as a mismatch.

**The cap, live, and what it counts.** Run `agent-110886fc` (5 steps, 20.6 s) made three training calls: `gradient_boosting` (`n_estimators=350, max_depth=5, learning_rate=0.07`) → **v47**, `logistic_regression` (`C=1.5, max_iter=400`) → **v48**, then the first call's parameters again — which came back **`training_cap_reached`** (*"this run has already trained 2 candidates (cap 2); propose what you have or conclude"*), refused **before** the idempotency lookup could have answered it with v47, and the run concluded instead. Worth recording, because it is pre-existing behaviour this build preserved rather than invented: the counter rises only for a training that **registered a new version** (`workflows.py`: a reuse "is not a second training, so it does not spend the second slot"), which run `agent-3c12b055` shows from the other side — its third call created v46 because the two calls before it were reuses.

**Serving loads either.** Traffic moved to v45 (`POST /api/models/rollback?to_version_id=45`) and `POST /v1/predict` returned `{"model_version":"45","predictions":[0],"routing":{"45":100}}`; inside the serving container `mlflow.sklearn.load_model` returned `sklearn.pipeline.Pipeline` (`steps=['StandardScaler','LogisticRegression']`) for v45 and `GradientBoostingClassifier` for v44 and v18. **The serving service was not modified** — its `load_model` path already handles both. Traffic was returned to v18 afterwards.

**Traces intact.** Fed run `agent-52f3be65`'s real transcript, the worker image's own SDK (sentry-sdk 2.69.1) produced one container transaction, one `gen_ai.invoke_agent` span and a child `gen_ai.chat` span, both carrying `gen_ai.conversation.id = agent-52f3be65`, with the prompt, the tool call, the finish reason and token usage recorded — and the system prompt captured on the wire contains the new rule about the two estimator families. (The envelopes were captured with a stand-in transport, which is the real payload for the real code path; sentry.io itself was not read — no API credentials exist in this environment.)

**Tests.** `python3 services/worker/test_brain.py`: **70 → 96 checks, 0 failed**, the new ones covering the schema generated from the kinds, per-kind defaults and validation (including nan and a parameter object arriving as a JSON string), the scripted probe being a call the trainer accepts, the scripted policy still training exactly one candidate, and a `train_candidate` decision surviving the Sentry span path with its nested `params` intact. `python3 -m unittest tests.test_domain -v`: 4 tests, OK — unchanged, because no domain type changed.

**The console's own train path still works, unmodified.** `POST /api/models/train` with the panel's three knobs (`n_estimators=150, max_depth=4, learning_rate=0.09` — the api's `TrainRequest` was not touched) ran a durable `TrainingWorkflow` to `COMPLETED` and returned `{"model_kind": "gradient_boosting", "params": {"n_estimators": 150, "max_depth": 4, "learning_rate": 0.09}, "accuracy": 0.9474, "roc_auc": 0.9874, "stage": "Staging"}`: the panel's knobs are mapped onto that kind's parameters inside the workflow, so a console with no kind selector keeps behaving exactly as before.

**Registry clutter, stated plainly:** the two verification runs added **v44–v46** (one per kind, plus the third call that showed reuses do not spend a cap slot), the cap proof added **v47–v48**, and the console-path check added **v49**; 43 → 49 versions. Nothing was promoted by hand and every promotion these runs filed was declined, so the demo is left with production serving **v18**, no promotion parked at the gate, and every workflow `Completed`. One detail to know when reading the console: after the temporary traffic moves to v45 and back, **v45 reads `staging` in the read model while MLflow has it `Archived`** — that is the displaced-version divergence [Script the kill and the resume](../tickets/B06-script-the-kill-and-the-resume.md) already recorded, not something this build introduced; an api restart re-hydrates the read model from the registry of record.

**Deliberately not changed:** the console (no kind selector — its three knobs map onto gradient boosting's parameters), `services/api/app/routes.py`'s `TrainRequest`, `scripts/train_and_register.py` (the standalone seed trainer), `services/serving` (proven, not touched), and the estimator itself for the original three numbers, whose defaults are byte-identical to what they were.

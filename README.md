# mlops-demo — End-to-End ML Lifecycle Platform

A runnable, `docker-compose` microservice that owns the **end-to-end model lifecycle** — a portfolio centerpiece for a scientific-data ML/MLOps role.

```
train → register (MLflow) → promote (Temporal, human-approval gate)
     → serve (canary / blue-green) → rollback → monitor (drift) → Sentry
```

**Dataset:** Breast Cancer Wisconsin (`sklearn.load_breast_cancer`, classification, 569×30) — canonical medical-ML data, zero domain knowledge needed, loads in one line.

---

## Microservice topology

```
[ui]       single-origin gateway + harness shell (React/Vite)   ── :8082
[api]      FastAPI: auth (JWT HttpOnly) + lifecycle facade       ── :8000
[serving]  FastAPI: canary/blue-green router + real model inference  ── :8001
[worker]   Temporal worker: promotion/training/investigation wf + activities
[mlflow]   model registry  (train → register → stage)
[temporal] durable orchestration (human-approval gate)
[postgres] Temporal's persistence store (workflow history + visibility)
```

### Single-origin gateway ("harness")

The `ui` service doubles as a **same-origin gateway**. After sign-in it renders a
left-sidebar tabbed shell that switches between the lifecycle console and the
embedded tools — all under one `:8082` origin, so the JWT HttpOnly cookie and the
frame/cookie policies just work:

| Tab (sidebar) | Served how |
|---|---|
| **Ops Console** | inline React (versions, stages, routing, **train/retrain**, **predict**, the gate's three buttons — *Start a promotion (goes to the gate)* / **Approve** / *Send traffic now (override)* — and the audit trail) |
| **Investigation Agent** | inline React (start a run, its transcript, the promotion it proposes at the same gate) |
| **Diagrams** (architecture / agent / workflow / lifecycle / sequence / dataflow) | static `diagrams/*.html` (Archify, `<meta animation="trace">`) |
| **Temporal UI** | reverse-proxied `/temporal/` (Temporal `publicPath=/temporal/`) |
| **MLflow UI** | reverse-proxied `/mlflow/` (prefix-strip; hash-routed app) |
| **API Docs** | FastAPI Swagger at `/docs` + `/openapi.json` |

Diagram HTMLs are bind-mounted from `./diagrams` into the container, so re-running
`archify deliver` doesn't require rebuilding the image.

---

## Quick start

```bash
docker compose up --build
```

Then:

| Service | URL |
|---|---|
| Ops console | http://localhost:8082 |
| API | http://localhost:8000 |
| Serving router | http://localhost:8001 |
| MLflow | http://localhost:5000 |
| Temporal UI | http://localhost:8233 |

**Seed login:** `operator / operator-pass` · `admin / admin-pass`

**To register a trained model version (first time):**
```bash
docker compose --profile tools run --rm trainer
```
This trains a GradientBoosting classifier on Breast Cancer Wisconsin, logs the
run + lineage (data hash, dataset, params) to MLflow, registers a version, and
auto-stages it (awaiting the human production gate).

**Or retrain from the console:** the **Ops Console** has a *Train a candidate*
panel — set `n_estimators` / `max_depth` / `learning_rate` and click
**Train & register**. That runs the same work as a durable `TrainingWorkflow` on
the worker (no `tools` profile, no shell), and the new version lands in
**Staging**. Training never edits an existing version — `ModelVersion` is
immutable by design, so a retrain is always a new version number.

**Two estimator families, one trainer.** The agent's `train_candidate` tool takes a
`model_kind` plus *that kind's* parameters, validated per kind:

| `model_kind` | parameters | why it exists |
|---|---|---|
| `gradient_boosting` | `n_estimators`, `max_depth`, `learning_rate` | the original estimator |
| `logistic_regression` | `C`, `max_iter` | a linear model on standardized features — a genuinely different inductive bias, and milliseconds to train |

Both kinds log under the **same registry name**, with the same `accuracy` / `roc_auc`
metrics, so promotion, serving, drift and the console need no new concept. Idempotency
is keyed on the **dataset, the kind and the parameters**, so repeating a training
reuses the version it already registered instead of adding a second one. The console's
Train panel is still the gradient-boosting one: its three knobs *are* that kind's
parameters, mapped in `TrainingWorkflow`.

**Flow to demo:**
1. Sign in to the console → you'll see the version staged as **Staging**.
2. Click **Start a promotion (goes to the gate)** → the Temporal workflow starts
   and *waits* for approval.
3. Click **Approve** → the version transitions to **Production** (identity recorded).
4. **Send traffic now (override)** moves 100% of traffic to the version in the box
   immediately: it bypasses the approval gate and is *not* recorded as a promotion.
   A version that cannot serve (its artifact is gone) is refused with 409, on this
   path as well as on promote.
5. Call **serving** (`POST /v1/predict`) to see canary weighting route to versions.
6. Retrain with different hyperparameters, promote the new version, and predict
   again — the served version and its output change, because serving loads the
   real artifact for the routed version.

**Calling serving:** `POST /v1/predict` takes a JSON array of **exactly 30**
feature values (the Breast Cancer Wisconsin width). `GET /v1/sample` returns one
real row to use, which the console's Predict panel has a button for. Predictions
are the model's real output: `{"model_version", "predictions", "probability_malignant", "routing"}`.

---

## DDD structure (shared domain core)

```
packages/ml_platform/
  context_modelregistry/   # the Model aggregate + immutable ModelVersion + Stage
    events.py              # audit-grade domain events (attributable, timestamped)
    model.py
  context_lifecycle/       # promotion / rollback orchestration (port + adapter)
    orchestrator.py
  context_serving/         # RoutingPolicy: canary weights, blue-green rollback
    routing.py
```

Bounded contexts communicate **only** through domain events — which double as the
**audit/lineage trail** (who/when/what), satisfying the reproducibility requirement.

---

## Key decisions (from the Wayfinder map)

- **Bar: C (Polish)** — fully working demo + real auth + tests + docs + clean UX.
- **Auth:** in-app users + JWT in an **HttpOnly SameSite=Lax cookie** (CSRF-mitigated),
  two roles (operator/admin). Promotion approval is role-gated and identity-carrying.
- **Promotion gate:** real **human approval** on staging→production — a durable
  **Temporal** workflow that waits on the approve signal; pipeline steps are auto.
- **Serving:** weight-based **canary + blue-green** router (A/B measurement is out of scope).
- **Sentry:** `sentry-sdk` wired across services, driven by `SENTRY_DSN` env
  (no-ops when empty; no self-hosted Sentry). The worker's agent loop also emits
  **agent traces**: see [What an investigation looks like in Sentry](#what-an-investigation-looks-like-in-sentry).
- **Investigation agent:** a durable ReAct loop on Temporal (8 steps, one tool call
  each, brain as an activity) that can investigate the registry, train a candidate and
  propose a promotion — then waits at the same human gate. Its transcript is its own
  event history. See the **Agent** tab in the console, and
  [`docs/demo-script.md`](docs/demo-script.md) for the demo that kills the worker on
  purpose.

---

## Run the demo

```bash
./scripts/demo-reset.sh     # clean state, then open the console and the Agent tab
```

The script, the narration and the numbers are in
[`docs/demo-script.md`](docs/demo-script.md). Run the reset before every rehearsal:
the demo's own state (a promotion parked at the gate, a staging version whose artifact
is gone) is the easiest thing to leave broken.

---

## Run the tests

```bash
python3 -m unittest tests.test_domain -v     # domain core: aggregate, routing, lifecycle
python3 services/worker/test_brain.py        # the agent's brain; the last group calls the
                                             # real model, so it needs ollama on the host
```

## What an investigation looks like in Sentry

One **investigation is one conversation**, and each of its steps is one agent
invocation with the model call beneath it:

```
transaction  op=function, "agent step agent-1f4c9a2b"   ← container; a Temporal worker
└── gen_ai.invoke_agent  "invoke_agent ml-lifecycle-investigator"   has no request to
    └── gen_ai.chat      "chat deepseek-v4.1-flash:cloud"           have started one
```

* The **conversation id is the Temporal workflow id** (`agent-<hex>`), so a run that
  is killed and resumed keeps writing into the same conversation — the run's own
  durable identity is what groups it.
* The conversation id is set with `sentry_sdk.ai.set_conversation_id`, which needs
  **`sentry-sdk>=2.64`**; the worker pins **2.69.1** for that reason (and for
  `stream_gen_ai_spans`, which is what sends `gen_ai` spans in the format the LLM
  views read). The api and serving images keep 2.19.2: they open no `gen_ai` spans.
* **The scripted fallback emits no model span** — it calls no model. Its agent span
  is named `invoke_agent ml-lifecycle-investigator [scripted policy, no model call]`
  and carries `agent.producer=scripted-policy`, so a policy can never be mistaken
  for a model in the dashboard.
* Agent spans are opened **in the activity, never in the workflow**: the Temporal
  workflow sandbox forbids importing `sentry_sdk`, so no span may be opened for a
  whole run from `workflows.py`. The longest-lived span an activity can honestly own
  is one step, and the conversation is what ties the steps together.

To see it: **Explore → Traces**, query `op:gen_ai.invoke_agent` (or
`gen_ai.conversation.id:agent-<hex>` for one run), environment `development`.
**Explore → Conversations** groups the same spans by conversation, but it
reconstructs the chat from the `gen_ai.input.messages` / `gen_ai.output.messages`
attributes, so it renders empty without content capture — off in the code, on for
this demo's worker (below).

### Content capture (prompts and answers)

The **code** default is off: `services/worker/main.py` reads
`SENTRY_SEND_DEFAULT_PII=0` unless told otherwise, so a deployment that configures
nothing captures no content. **This demo's worker turns it on** in
`docker-compose.yml` (`SENTRY_SEND_DEFAULT_PII: ${SENTRY_SEND_DEFAULT_PII:-1}`)
because the Conversations timeline is empty without it.

What is captured here: the operator's goal, the transcript digests the agent read
(registry stages and metrics, evaluation results), and the model's answer —
recorded as `gen_ai.system_instructions`, `gen_ai.input.messages` and
`gen_ai.output.messages` on the `gen_ai.chat` span. This demo has no end-user
content to leak; a deployment that handles real user data should decide
deliberately rather than inherit this. Environment: `development`.

Turn it off for the worker with one line:

```bash
SENTRY_SEND_DEFAULT_PII=0 docker compose up -d worker
```

Grouping is unaffected either way: conversations are keyed by
`gen_ai.conversation.id`, which every span carries regardless of this setting.

## Environment variables

| Var | Default | Note |
|---|---|---|
| `SENTRY_DSN` | *(empty)* | Set a real DSN to enable Sentry capture |
| `SENTRY_TRACES_SAMPLE_RATE` | `1.0` | Worker only: sample rate for the agent's agent+LLM spans (the api keeps its own `0.25`) |
| `SENTRY_SEND_DEFAULT_PII` | `0` in code, `1` for this demo's worker | Capture prompts/outputs (`gen_ai.input.messages` etc). Needed for the Conversations view; the code default stays off so a silent deployment captures nothing |
| `JWT_SECRET` | `change-me-in-prod` | **Set this.** Signs the auth JWT |
| `SEED_OPERATOR_PASSWORD` / `SEED_ADMIN_PASSWORD` | dev presets | Seed logins |

## Out of scope (by design)

- Model *quality* tuning (this is a deployment pipeline, not a modeling contest).
- Enterprise SSO, external secrets manager, multi-region HA.
- Kafka/Spark streaming arm; A/B user-sticky measurement.

---

## Live smoke test (verified end-to-end)

The full lifecycle was exercised against the running compose stack and
confirmed green:

| Step | Endpoint | Result |
|---|---|---|
| Login (operator) | `POST /auth/token` | 200 |
| Register v1 → Staging | `POST /api/models/1/register` | 200 |
| Promote (starts durable gate) | `POST /api/models/1/promote` | returns `workflow_id` |
| Approve (Temporal signal w/ identity) | `POST /api/models/1/approve` | stage → **Production** |
| MLflow registry | (Temporal activity) | `v1: stage=Production` ✅ |
| Serving predict | `POST /v1/predict` (30 features) | routes on `{"1":100}`, real artifact |
| Retrain from console | `POST /api/models/train` | TrainingWorkflow → new version in Staging |
| Rollback (blue-green) | `POST /api/models/rollback` | 200 → the prior servable version (`v1` is refused with **409**: its artifact is gone) |
| Audit trail | `GET /api/models/events` | register/promote/approve/rollback events |

The human-approval **gate is real**: `promote` starts a Temporal workflow that
waits on the `approval_signal`; `approve` sends that durable signal (with the
operator's identity), the workflow resumes, and its `promote_stage` activity
atomically transitions the MLflow registry to Production.

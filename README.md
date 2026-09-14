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
  (no-ops when empty; no self-hosted Sentry).
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

## Environment variables

| Var | Default | Note |
|---|---|---|
| `SENTRY_DSN` | *(empty)* | Set a real DSN to enable Sentry capture |
| `SENTRY_TRACES_SAMPLE_RATE` | `1.0` | Worker only: sample rate for the agent's LLM spans (the api keeps its own `0.25`) |
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

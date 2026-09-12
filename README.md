# Build1 — End-to-End ML Lifecycle Platform

A runnable, `docker-compose` microservice that owns the **end-to-end model lifecycle** — a portfolio centerpiece for a TetraScience-flavored ML/MLOps role.

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
[serving]  FastAPI: canary/blue-green router + Sentry            ── :8001
[worker]   Temporal worker: activities, promote/rollback wf
[mlflow]   model registry  (train → register → stage)
[temporal] durable orchestration (human-approval gate)
[postgres] shared state (users + registry/metadata)
```

### Single-origin gateway ("harness")

The `ui` service doubles as a **same-origin gateway**. After sign-in it renders a
left-sidebar tabbed shell that switches between the lifecycle console and the
embedded tools — all under one `:8082` origin, so the JWT HttpOnly cookie and the
frame/cookie policies just work:

| Tab (sidebar) | Served how |
|---|---|
| **Ops Console** | inline React (versions, stages, routing, promote/approve/rollback, audit) |
| **Diagrams** (architecture / workflow / lifecycle / sequence / dataflow) | static `diagrams/*.html` (Archify, `<meta animation="trace">`) |
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

**Flow to demo:**
1. Sign in to the console → you'll see the version staged as **Staging**.
2. Click **Promote** → the Temporal workflow starts and *waits* for approval.
3. Click **Approve** → the version transitions to **Production** (identity recorded).
4. Use the **Rollback** button to blue-green flip back to a prior version.
5. Call **serving** (`POST /v1/predict`) to see canary weighting route to versions.

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

---

## Run the tests

```bash
python3 -m unittest tests.test_domain -v
```

## Environment variables

| Var | Default | Note |
|---|---|---|
| `SENTRY_DSN` | *(empty)* | Set a real DSN to enable Sentry capture |
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
| Serving predict | `POST /v1/predict` | routes on `{"1":100}` |
| Rollback (blue-green) | `POST /api/models/rollback` | 200 → v1 |
| Audit trail | `GET /api/models/events` | register/promote/approve/rollback events |

The human-approval **gate is real**: `promote` starts a Temporal workflow that
waits on the `approval_signal`; `approve` sends that durable signal (with the
operator's identity), the workflow resumes, and its `promote_stage` activity
atomically transitions the MLflow registry to Production.

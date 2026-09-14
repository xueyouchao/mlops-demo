#!/usr/bin/env bash
# demo-reset — put the platform into the state docs/demo-script.md expects.
#
# Run this before every rehearsal, not just before the real thing. The demo's own
# state is the easiest thing to leave broken: a promotion parked at the gate makes
# the next promote a 409, and a staging version whose artifact is gone fails on
# promote, mid-demo, in front of people.
#
# It is a demo harness, not product code: it reaches into MLflow and Temporal with
# docker exec rather than through the API, because clearing up after an accident is
# not a thing the console exposes a button for.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

API_URL=${API_URL:-https://mlops.srv1567269.hstgr.cloud}
# A fixed path: mktemp honours TMPDIR, and in the sandbox this repo is developed in
# that is a directory the script cannot write to, which silently left the script
# cookie-less and reporting "nothing is serving production" when v7 was.
JAR=/tmp/demo-reset-cookies.txt
problems=0
note() { printf '  %s\n' "$*"; }
warn() { printf '  !! %s\n' "$*"; problems=$((problems + 1)); }

echo "demo-reset"

# ---- 1. anything still waiting at the gate ------------------------------------
# A pending promotion blocks the next one for that model (409) and leaves a run
# waiting for an answer nobody is going to give.
echo "· pending promotions"
timeout 60 docker exec -i mlops-demo-api python3 - <<'PY'
import asyncio
from temporalio.client import Client
async def main():
    c = await Client.connect("temporal:7233")
    n = 0
    async for wf in c.list_workflows('WorkflowType = "PromotionWorkflow" AND ExecutionStatus = "Running"'):
        await c.get_workflow_handle(wf.id).terminate(reason="demo-reset: cleared before the demo")
        print(f"  terminated {wf.id}"); n += 1
    print("  none pending" if not n else f"  {n} cleared")
asyncio.run(main())
PY

# ---- 2. the worker, and the fallback switch -----------------------------------
# Act 3 leaves the worker running the scripted policy. Forgetting to undo that
# makes every later run look scripted while the narration claims it is a model.
echo "· worker"
FB=$(docker inspect mlops-demo-worker --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | sed -n 's/^AGENT_FALLBACK=//p')
if [ "${FB:-auto}" != "auto" ]; then
  note "AGENT_FALLBACK=$FB -> restoring auto"
  AGENT_FALLBACK=auto docker compose up -d --force-recreate worker >/dev/null 2>&1
fi
if ! docker ps --filter name=mlops-demo-worker --filter status=running -q | grep -q .; then
  note "worker is not running -> starting it"
  docker compose start worker >/dev/null 2>&1 || docker compose up -d worker >/dev/null 2>&1
fi
sleep 4
if docker ps --filter name=mlops-demo-worker --filter status=running -q | grep -q .; then
  note "worker up ($(docker ps --filter name=mlops-demo-worker --format '{{.Status}}'))"
else
  warn "worker is still down — the demo needs it for anything but the kill"
fi

# ---- 3. unpromotable staging versions -----------------------------------------
# A staging version with no artifact can never be promoted. A run that picks it
# burns a step discovering that on stage, so it gets archived out of the way.
echo "· staging versions with no artifact"
timeout 90 docker exec -i mlops-demo-api python3 - <<'PY'
import mlflow
from mlflow.tracking import MlflowClient
c = MlflowClient()
name = "breast-cancer-classifier"
fixed = 0
for v in c.search_model_versions(f"name='{name}'"):
    if v.current_stage != "Staging":
        continue
    # Use the product's own rule, and branch on it. This block has now been wrong
    # three times: first reading `source` as a filesystem path, then disagreeing
    # with `artifact_problem` about thirty-two servable versions, and then -- after
    # both were "fixed" -- stitching an `if present:` header out of existence, so
    # `present` was computed and never read and the archive branch ran for every
    # staging version while printing "artifact MISSING" without checking anything.
    import os
    import time
    from ml_platform.registry_health import artifact_problem
    problem = artifact_problem(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
                               name, str(v.version))
    # MLflow creates model versions asynchronously ("waiting up to 300 seconds for
    # model version to finish creation"), so a version registered seconds ago can
    # look artifact-less. Never judge a fresh one.
    age_ms = int(time.time() * 1000) - int(v.creation_timestamp or 0)
    if not problem:
        print(f"  v{v.version} staging, artifact present — promotable")
    elif age_ms < 180_000:
        print(f"  v{v.version} staging, created {age_ms // 1000}s ago — too new to judge, left alone")
    else:
        c.transition_model_version_stage(name, int(v.version), "Archived")
        print(f"  v{v.version} staging, artifact MISSING -> archived (it could only fail on promote)")
        fixed += 1
print("  nothing to archive" if not fixed else f"  {fixed} archived")
PY

# ---- 4. what the run will actually have to choose between ---------------------
echo "· state"
curl -sS -c "$JAR" -X POST "$API_URL/auth/token" \
  -d "username=operator&password=operator-pass" >/dev/null 2>&1
# Optional: pin the incumbent. Approving a promotion promotes the best candidate,
# so the next investigation honestly concludes that nothing beats production and
# never reaches the gate — which is how a rehearsal that approves every pass walks
# production from v7 to v19 and then cannot find a gate anywhere. Pinning puts the
# question back: is there something better than what is serving?
#
#   DEMO_INCUMBENT=7         pin v7, the number you chose
#   DEMO_INCUMBENT=weakest   let the script pick: the servable version with the
#                            lowest recorded roc_auc (step 0 of docs/demo-script.md)
#
# `weakest` is the same mechanism with the number chosen for you, because the
# number is the whole problem: against a strong incumbent the agent honestly
# concludes that nothing beats production and the gate is unreachable on demand.
# It picks by *score*, from a version that is really registered and really
# servable — not a magic number — so what the run finds is a genuinely weak model
# rather than a rigged comparison.
if [ -n "${DEMO_INCUMBENT:-}" ]; then
  PIN=$DEMO_INCUMBENT
  if [ "$PIN" = "weakest" ]; then
    PICK=$(timeout 90 docker exec -i mlops-demo-api python3 - <<'PY'
import os

from mlflow.tracking import MlflowClient
from ml_platform.registry_health import artifact_problem

name = "breast-cancer-classifier"
uri = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
client = MlflowClient()
scored = []
for v in client.search_model_versions(f"name='{name}'"):
    # Servable first, by the product's own rule rather than a second opinion
    # invented here: a version whose artifact is gone cannot serve traffic, so it
    # cannot be the incumbent a run argues against.
    if artifact_problem(uri, name, str(v.version)):
        continue
    # The honest score is the version's *own recorded* roc_auc — the number its
    # training run logged on the held-out split `evaluate_version` reuses, so it
    # is comparable with whatever the agent measures later. Nothing is invented,
    # and nothing is re-measured: re-scoring forty versions would take minutes.
    try:
        auc = float(dict(client.get_run(v.run_id).data.metrics)["roc_auc"])
    except Exception:
        continue
    scored.append((auc, int(v.version)))
if not scored:
    print("  no servable version carries a recorded roc_auc — the incumbent cannot be chosen for you")
else:
    scored.sort()  # weakest first; a tie goes to the older version, so the pick is deterministic
    auc, version = scored[0]
    print(f"  {len(scored)} servable versions carry a recorded roc_auc")
    print(f"  weakest   v{version} roc_auc {auc:.4f}  <- picked as the incumbent")
    print(f"  strongest v{scored[-1][1]} roc_auc {scored[-1][0]:.4f}")
    print(f"PIN={version}")
PY
)
    printf '%s\n' "$PICK" | grep -v '^PIN=' | grep -v '^$'
    PIN=$(printf '%s\n' "$PICK" | sed -n 's/^PIN=//p' | tail -n1)
  fi
  if [ -n "$PIN" ]; then
    # Pin only when the pick is not already serving. A reset that re-pins the same
    # weak incumbent — the normal case, since `weakest` is a function of the
    # registry and returns the same version every time — would otherwise re-run a
    # rollback to the version already live: it moves nothing, writes a "rolled back
    # from v18 to v18" audit event, and re-transitions MLflow for no reason.
    SERVING_NOW=$(curl -sS -b "$JAR" "$API_URL/api/models/routing" 2>/dev/null \
      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("production") or "")' 2>/dev/null)
    if [ "$SERVING_NOW" = "$PIN" ]; then
      note "v$PIN is already serving production — nothing to move"
    else
      OUT=$(curl -sS -b "$JAR" -X POST "$API_URL/api/models/rollback?to_version_id=$PIN" 2>/dev/null)
      note "pinned the incumbent -> v$PIN  ($OUT)"
    fi
  else
    warn "DEMO_INCUMBENT=weakest found no version to pin — refusing to guess one"
  fi
fi
ROUTING=$(curl -sS -b "$JAR" "$API_URL/api/models/routing" 2>/dev/null)
MODELS=$(curl -sS -b "$JAR" "$API_URL/api/models" 2>/dev/null)
python3 - "$ROUTING" "$MODELS" <<'PY' || problems=$((problems + 1))
import json, sys
try:
    routing = json.loads(sys.argv[1]); models = json.loads(sys.argv[2])
except Exception as e:
    print(f"  !! could not read the registry through the API: {e}"); raise SystemExit(1)
prod = routing.get("production")
print(f"  serving production: v{prod}  (weights {routing.get('weights')})")
servable = [v for v in models.get("versions", []) if v.get("artifact_uri")]
if prod and not any(v["version_id"] == str(prod) for v in servable):
    print(f"  !! production v{prod} has no artifact — the incumbent cannot be compared")
    raise SystemExit(1)
cand = [v for v in servable if v["version_id"] != str(prod)][-3:]
print("  candidates a run may weigh: " + (", ".join(f"v{v['version_id']}({v['stage']})" for v in cand) or "none"))
if not cand:
    print("  !! nothing to compare against — train one before demoing")
    raise SystemExit(1)
PY

echo
if [ "$problems" -eq 0 ]; then
  echo "  ready. Open the console's Agent tab."
else
  echo "  $problems problem(s) above — fix them before an audience is watching."
fi
exit "$problems"

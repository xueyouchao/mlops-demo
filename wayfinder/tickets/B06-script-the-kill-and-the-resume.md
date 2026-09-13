---
id: B06
title: Script the kill and the resume
labels: [wayfinder:build]
status: open
assignee: ""
blocked-by: [B05]
---

## Scope

The demo itself. The kill lands **between steps** — watch until an observation appears, then stop the worker — and the narration states exactly what is true: *the run resumes where it was, and an interrupted activity runs again*, never the stronger "nothing ever runs twice". Includes what to show before, during and after the kill, how the fallback is demonstrated deliberately, and the state to reset between runs.

**Done when:** the demo runs end to end twice in a row without leaving stale pending promotions or unpromotable versions behind.

**Read with:** the map's Notes (word the durability claim exactly), T06 (kill point), T09 (what the sources do and do not support).

## Found while building the loop (verified live, 2026-09-13)

`docker kill mlops-demo-worker` does **not** restart itself, despite `restart: unless-stopped` being set on the service: the container sat at `Exited (137)` for ten minutes until it was started by hand. That is the better behaviour for this demo — the freeze stays on screen for as long as the narration needs it, instead of self-healing in three seconds — but it means the script must bring the worker back explicitly (`docker compose start worker`), and must not assume the platform recovers on its own.

Timing that the narration can rely on: with the operator's brain, early steps are fast (the six tool schemas and a short transcript) and later steps slow down as the transcript grows, so the kill window is widest in the middle of a run. The first real kill landed **inside a `train_candidate`** — which is worth saying out loud in the demo, because the retry then returned *"already exists for exactly these hyperparameters and this data — reused, no new version registered"* (T06 dec. 1's idempotency, proven by a real SIGKILL rather than a manual double-call).

**An action worth adding to the script: cancel a promotion while the run is waiting on it.** The loop handles it — a run waiting on the gate checks the promotion's status every 30 s, so a promotion that is terminated or fails without signalling is recorded as a failure instead of hanging forever — but that path is the one thing in the loop that the build could not demonstrate live, and it is the exact hazard that the wedged v4 promotion created. Killing the promotion in front of an audience, and showing the run record a failure rather than wait forever, is a better ending for the durability section than one more restart.

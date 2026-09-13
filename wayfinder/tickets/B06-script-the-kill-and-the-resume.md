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

**The kill's *moment* decides how long the audience waits, and this was measured, not guessed.** If an activity is in flight when the worker dies, Temporal does not retry it until that activity's start-to-close timeout expires — 180 s for a brain call, 60–120 s for a tool — so the run sits visibly frozen for up to three minutes before moving again. Killing with *no* activity in flight resumes immediately. The wide, controllable window with nothing in flight is the approval wait: the run is parked on the gate, indefinitely, and comes back the instant the operator decides. A mid-run kill still proves the claim — nothing is lost and the projection shows the in-flight step as `pending` throughout the wait, which is exactly what the panel renders as "deciding…" — but it is a slower reveal, so the script should place the kill deliberately rather than hope.

Confirmed in the same run: `docker kill` leaves the worker down (see above), and after a 7.5-minute outage the resume is *instant*, because the timeout has already expired while nothing was running.

**And the kill can land in a window that used to hang, which the script must now respect.** A kill 8 seconds after an activity was *scheduled* — before any worker acknowledged it — left that run stalled indefinitely: no timeout applies to a task that never started, so nothing re-delivered it. That is fixed in the loop (every agent activity now carries an explicit `schedule_to_start_timeout`, see the third amendment in T06), so the worst case is now a visible retry rather than a run that never moves. It is still worth knowing *why* the script should kill where it says to: the safe window is either with no activity pending at all, or with one genuinely in flight.

**And the cost of a mid-activity kill is measurable, so the script should choose its moment with the number in hand.** Killing the worker while a *brain call* was in flight (a 3-minute `start_to_close`) cost the run **183 seconds of wall-clock for 148 seconds of work** — the audience watches a frozen run for three minutes, which is a long silence on stage. Killing while a *read* is in flight costs up to 60 s, a training up to 5 minutes. The panel does its part — the frozen step says *"no worker is answering"* and keeps its clock running — but the script should aim at the cheapest window it can hit deliberately: at the approval gate, where the run is waiting on a person rather than on an activity, or immediately after a step completes. That is a scripting decision this ticket owns, and the numbers above are why it matters.

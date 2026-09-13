---
id: B05
title: Build the console panel
labels: [wayfinder:build]
status: closed
assignee: ""
blocked-by: [B04]
---

## Scope

The agreed panel in `ui/src/App.jsx`, in the console's own conventions: its **own sidebar entry**, the goal composer with presets (frozen as workflow input once a run starts), and the **timeline spine** — a rail that *breaks* at the worker's death and shows the resume, a `deciding…` node with a running clock while a step is in flight, labelled fallbacks, separate work and gate clocks, the four terminal reasons, and the approval card (candidate vs incumbent on the same split, rationale, cost paid) with **Abandon run** visually separated from Approve and Decline.

**Done when:** the panel renders every state from the projection alone, including with the worker dead.

**Design source:** T07's resolution. The variant exploration is the primary source and lives on the local branch `prototype/agent-panel-variants`.

## Outcome

**Built**, as its own sidebar entry: `ui/src/AgentPanel.jsx`, wired in `App.jsx`, rendering from `GET /api/agent/runs/{id}` alone — the projection [Project the transcript from Temporal history](B04-project-the-transcript-from-temporal-history.md) built. It is not a mock of the design; it is the design in the console's own conventions.

- **Composer with presets, frozen while a run is in flight.** The field then shows *that run's* goal, disabled, because the goal is workflow input and cannot be edited after the fact.
- **The spine.** One step per unit, header first — `step 4 · train_candidate · 25.9s · [model]` — so it can be skimmed before the reasoning is read, with the rationale above its observation as an indented quote of the agent's own words.
- **`deciding…` / `running <tool>…` with a clock that moves**, and the frozen case said in words: *"no worker is answering. The run is frozen, not lost: every step above is already in event history, and it continues from here when a worker returns."* A step in flight is `pending` whether the brain is deciding or the tool is running — a training is the longest thing in the loop, so it is the likeliest thing to be in flight when the worker dies.
- **Two clocks, never one**: work (the activities' own execution — no operator wait, no time when the platform was down) and waiting on you, with wall-clock elapsed beside them.
- **The four endings** said plainly, and `budget_exhausted` / `no_progress` dressed as results rather than failures, because that is where this demo's honesty lives.
- **The fallback spelled out once**, above the spine, rather than as a chip a room has to interpret.
- **The approval card**: candidate against the incumbent on the same split (shown as — when the run never evaluated one, rather than invented), the rationale, the cost paid in steps and trainings, Approve and Decline — and **Abandon run** below a rule, separated, with its own consequence stated and a two-click confirm.

**Two routes this ticket owed, and both are built.** `approved=false` on the existing decision route, so a decline reaches the durable workflow and moves nothing; and `POST /api/agent/runs/{run_id}/cancel`, which terminates the run **and withdraws the promotion it filed**. Abandoning decides the run, not the promotion — but leaving the orphan would block every later proposal for that model, so it cannot be left behind.

**What verification showed**, over the real origin with a real login:

- **A run killed mid-flight resumed and finished**: `interruptions=1`, the interrupted step at `attempts=2`, `interrupted=true`, 7 steps, ending `concluded`. The break in the rail is read from activity attempt numbers, so it is durable history rather than a guess from how long something has been quiet.
- **A run at the gate** projected as `awaiting-approval` with the card's data intact from history: the rationale, `candidate` and `incumbent` metrics for v8 against v7 on the same held-out split, and `cost {steps: 8, trainings: 3}` — read from the `propose_promotion` activity's *own arguments*, so the card needs no second store and still works with the worker dead.
- **Abandon**: `{'run_status': 'TERMINATED', 'withdrawn_promotion': 'promote-breast-cancer-classifier-8'}`, that promotion's Temporal status then `TERMINATED`, the run projecting as `terminated`, and a re-promote of v8 accepted. No orphan — which is the whole point of the action.
- **Decline**: `{'approved': False, 'declined_by': 'operator'}`, the promotion workflow completing with `promoted: False`, v6 still in **staging** (a decline moves nothing), and a re-promote accepted.
- **A step in flight projects as pending**, with its phase (`deciding`) and the run still open — the read that keeps working while no worker is running anything.
- **The build carries it**: the image builds and the served bundle contains the panel.

**What was not verified, and will not be claimed:** I have not *seen* it render. This sandbox has no browser — the devtools bridge is not available here and headless Chrome cannot start — so verification is the data contract field by field plus a successful production build, not a screenshot. The one path not observed live is `phase: "calling"` (a tool in flight when the worker dies): the kill landed inside a brain call, so the pending step observed was a decision. Both phases are one branch of the same code and both are styled; only one was seen.

**The throwaway mock is off main**, with its compose mount, as T07 said it would be once the panel existed.

**Found while building, and it is worth more than the panel:** an unbounded `schedule_to_start_timeout` is a hang, and the *fix for it* was wrong the first time. Both are recorded in the third amendment to [Lock the run semantics](T06-lock-the-run-semantics.md); the short version is that a schedule-to-start timeout counts as a **failed attempt**, so a tight bound turns an outage into a failed run — the opposite of what this demo is about. The bound is now ten minutes, longer than any outage the demo shows.

Two smaller things this ticket paid for, both in the read path: the assembled `terminal` dict is built *after* the activity walk, so using it during the walk is a `NameError` — and the route then reported that bug as *"Temporal is not reachable"*, which sent me looking at the wrong service. It now says what actually failed.

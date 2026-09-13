---
id: B01
title: Build the agent loop workflow
labels: [wayfinder:build]
status: closed
assignee: ""
blocked-by: [B02, B03]
---

## Scope

The ReAct loop as a Temporal workflow in `services/worker/`, exactly as [Lock the agent loop contract](T01-lock-the-agent-loop-contract.md) fixed it: the goal as workflow input, one step = one brain call → one tool call → one observation, cap 8, the transcript as workflow instance state, a **six-minute** ceiling measured on the **workflow clock** and excluding the human-gate wait (amended from three minutes in T06 for the operator's slower brain), and the four terminal reasons (`concluded` / `budget_exhausted` / `no_progress` / `failed`).

Also the API's start route: role-gated like the promote route, the goal and `requested_by` as input, the run id returned.

**Done when:** a run can be started through the API, its steps are visible in event history, and killing the worker between steps resumes without re-calling the brain for a recorded step.

**Read with:** T01 (loop contract), T06 (run semantics), T04 (the read path needs the activity names to be distinguishable).

## Outcome

`InvestigationWorkflow` in `services/worker/workflows.py`, plus `POST /api/agent/runs` (`services/api/app/agent_routes.py`, `TemporalLifecyclePort.start_investigation`). The loop is flat ReAct — one step is one brain call → one tool call → one observation — with the transcript as workflow instance state, the allow-list checked in the workflow (a pure function of recorded values), bad decisions appended as observations that burn a step, `no_progress` on a consecutive identical call, per-tool retry policies, and the run staying alive across the human gate so its *ending* records what was actually decided.

Built in thin slices, each verified live rather than assumed. In order: the loop ran and concluded, then a real `docker kill` mid-run, then a **seven-minute** outage (longer than the run's own ceiling), then the operator gate end to end.

**Verified live**

1. **Started through the API** — cookie auth, role-gated like the promote route, returns `agent-<8 hex>` as the run id.
2. **Steps visible in event history** — each step is an activity result in history (rationale + observation) and the whole transcript is returned as the run's result.
3. **Kill and resume** — SIGKILL 20 s into a run, with steps already recorded. After a **7.5-minute** outage the run resumed and finished: **7 `brain_decide` schedules for 7 steps** (no recorded step was re-called) and an attempt distribution of **`{1: 13, 2: 1}`** — exactly one extra attempt, the call that was in flight when the worker died, and nothing else. This is the ticket's done-when, and it is the same claim the demo will make, so the wording has evidence behind it: *the run resumes where it was; an interrupted activity runs again.*
4. **The gate, end to end** — a run proposed v7, waited durably on the operator (the 30 s status poll visible as a `TIMER_STARTED`), and when the operator approved, its ending recorded the promotion's *own* outcome: `{"approved": true, "approved_by": "operator", "promoted": true, "version_id": "7"}`, detail *"the operator approved v7"*. T05 decisions 1 and 4, demonstrated rather than asserted.
5. **A refusal is adapted to, not crashed on** — an earlier run's proposal was refused (`a promotion … is already awaiting the operator`) and the agent concluded with a recommendation: v7 (0.9561) dominates the pending v6 (0.9474), endorse v7 instead. T05 decision 3's behaviour, without being asked for.
6. **"No better candidate" is a result** — the last smoke run evaluated the incumbent, two rivals and a fresh candidate (v8), found nothing meaningfully better, and concluded *"v7 … is still the best version we have"*. T01 decision 5's point: a run that concludes without proposing is legitimate and visible.
7. **`concluded` and `budget_exhausted` both observed for real.** `budget_exhausted` was not simulated — it ended a run, for the reason in the next section.

**Not demonstrated live:** `no_progress` (needs a brain that repeats itself) and the promotion-failed path of `failed` (needs a promotion that dies after approval). Both are implemented and named here rather than claimed; [Script the kill and the resume](B06-script-the-kill-and-the-resume.md) carries the second one as a demo action worth adding.

**Two changes the build forced, both recorded in their own tickets**

- **The ceiling charged an outage as work.** The first kill exposed it: a ten-minute outage was charged to the agent, so the run resumed correctly and then died `budget_exhausted` having recorded five good steps — a demo about surviving a kill, failing because of the kill. The ceiling now charges each step its own duration, capped, and excludes the operator wait. Amended in [Lock the run semantics](T06-lock-the-run-semantics.md).
- **A decline had nowhere to land.** `PromotionWorkflow` only ever ended on approval, so "decline" would have been a button that recorded nothing and left the run waiting for a decision already made. It now ends on either, and tells the asking run what happened. **The API's decline and cancel routes land with [Build the console panel](B05-build-the-console-panel.md)** — the workflow side is done and verified by signal; the buttons are the panel's, and they must not be forgotten.

**Also fixed while verifying:** the first real run burned a step on `there is no vv5` — the digests write versions as `v6` and the brain copies the prefix straight back, so both version-taking tools now normalise it (and the prompt says so as well). A tool that punishes the notation it taught is a trap with extra steps.

**Handoff to [Project the transcript from Temporal history](B04-project-the-transcript-from-temporal-history.md)** — the read path needs the names:

- Activities: `brain_decide`, then the six tools `read_registry`, `read_run_metrics`, `evaluate_version`, `train_candidate`, `propose_promotion`, `conclude` — plus `promotion_outcome`, which is loop plumbing and is never offered to the brain.
- Run ids: prefix **`agent-`**, and the workflow type is `InvestigationWorkflow`. Visibility works as `WorkflowId STARTS_WITH "agent-"` — underscore, and `ExecutionStatus = "Running"` with a capital `R`.
- Terminal entry: `{reason, detail, at, steps, promotion}` plus `answer`/`evidence` when the reason is `concluded`. `reason` is one of `concluded` / `budget_exhausted` / `no_progress`; **`failed` is Temporal's own workflow status**, reached by raising — a brain that cannot be reached at all, or a promotion that dies after approval — so the projection must read the status as well as the entry, and a run with no result still has a complete transcript in history.
- Transcript entry: `{step, at, tool, arguments, rationale, observation, producer, ok, kind}`, where `producer` is `model` or the labelled fallback, and `tool` is `null` for a decision that never became a call.

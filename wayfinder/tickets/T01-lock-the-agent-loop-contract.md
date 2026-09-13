---
id: T01
title: Lock the agent loop contract
labels: [wayfinder:grilling]
status: closed
assignee: "dsh session"
blocked-by: []
---

## Question

How is the agent's reason → act → observe cycle expressed as a Temporal workflow, such that a **nondeterministic brain still yields a deterministic, replayable, resumable run**?

Settle at least:

- **Where the brain sits.** It must be an activity, never workflow code: the LLM SDK must not be imported into the workflow sandbox (same discipline the existing workflows use by referring to activities by string name). Confirm the call shape and what the activity returns.
- **What the workflow holds.** The transcript (goal, each tool call, each observation, the final answer) is workflow state, and therefore event history — which is what makes the killed-worker resume work. Decide its shape and what is *not* kept.
- **How the next tool is chosen**, and how a malformed or unparseable brain response is handled (retry? repair prompt? fail the run?).
- **Termination**: the step cap, what counts as done, and whether a run may legitimately end without proposing anything (e.g. "no candidate beats production").
- **Determinism**: anything the brain returns must reach history before it is acted on, so a replay makes the same decisions. State explicitly what would break replay.

Constraints from the map: the brain is host ollama behind an activity with a scripted-policy fallback; the agent may train and propose but never approve or roll back.

## Prior evidence (from the research branch)

[Research how production durable-agent frameworks structure their loops](T09-research-durable-agent-loop-patterns.md) closed with findings on a throwaway branch — read with `git show research/durable-agent-loop-patterns:docs/research/durable-agent-loop-patterns.md` (§1.1, §5). It **narrows this ticket rather than settling it**, and corrects two premises:

- **The shape is already endorsed, so copy it deliberately**: Temporal's own OpenAI Agents SDK integration runs the agent loop in the workflow, model calls as activities, and keeps the transcript in workflow state because that state is replay-safe. Cite that pattern; do not present it as our invention.
- **Correction — "the LLM SDK must not be imported into the workflow sandbox" is stricter than the documented rule.** Temporal's rule is about *calls*; its own cookbook imports the SDK behind the sandbox's pass-through hatch. Our string-name discipline (`services/worker/workflows.py`) is deliberate hardening: keep it, but record it as a choice, not as the rule.
- **State the replay rule precisely**: the tool *choice* must be derived only from values already recorded (goal + transcript) — never from anything sampled inside workflow code. That, not the activity boundary, is what makes replay deterministic.
- **The step cap is ours alone** (Temporal ships none — its own recipe is an unbounded loop). Fix the *unit* as well as the number: does an activity retry, or a repair round-trip, consume a step? The unstated unit is where these designs surprise their authors. [Lock the run semantics](T06-lock-the-run-semantics.md) owns the bound itself.
- **Record the divergence consciously**: every-tool-an-activity is stricter than Temporal's guidance, which leaves deterministic tools inline. Defensible here — every tool is I/O against the platform — but say why rather than leaving it implicit.
- The human gate as signal + `wait_condition` is validated by the same evidence; `PromotionWorkflow` already does exactly this.

Feeds [Define the agent's tool surface & schemas](T02-define-the-agent-tool-surface-and-schemas.md), [Decide how an investigation starts](T03-decide-how-an-investigation-starts.md), [Decide where the agent transcript lives](T04-decide-where-the-agent-transcript-lives.md), [Lock the run semantics](T06-lock-the-run-semantics.md). Informed by [Research how production durable-agent frameworks structure their loops](T09-research-durable-agent-loop-patterns.md).

## Resolution

Grilled one question at a time (`/grilling`, with `/domain-modeling` consulted for the vocabulary). Six decisions:

1. **Shape — flat ReAct.** One step is: one brain call → exactly one tool call → one observation. No plan-then-execute, no variable-size batch — those were offered and rejected (a plan is made blind to intermediate observations, and a variable shape muddies what the cap counts). Chosen because each step is a clean checkpoint (the kill can land on a boundary), the reasoning unfolds legibly one step at a time, and replay stays trivial (one recorded brain output per step). Cost accepted: one model call per step, so an 8-step run is 8 model calls.

2. **One step is one brain call, and that is what the cap counts.** A step contains exactly one brain call, so counting steps and counting brain calls are the same thing. An activity retry does not consume a step (invisible infrastructure; history does not even record `ActivityTaskStarted` until the attempt resolves), and tool execution time is not counted. **Cap = 8.** Since a malformed decision burns a step (decision 4), a confused brain self-terminates instead of spinning. State this unit wherever the cap appears — the research found the unstated unit is where these designs surprise their authors.

3. **The brain is stateless; the transcript is the memory.** The activity takes (goal + transcript) and returns one decision. Nothing lives in a process or a session — the research is explicit that state held outside the workflow is what Temporal cannot recover. The transcript is an append-only list of typed entries in workflow instance state, the same mechanism as `PromotionWorkflow`'s `self._approved`, so it is event history and it replays. Each step records the brain's short **rationale** and the tool's **observation**. The raw `thinking` field is deliberately **not** recorded: it is large, and activity results are visible in the Temporal Web UI, so recording it publishes it.

4. **Bad output is an observation, not an exception.** The activity parses tolerantly and returns either a decision or a typed failure — `unparseable` / `unknown tool` / `bad arguments`. The **workflow** then checks the tool name against its allow-list: a pure function of recorded values, so it stays replay-safe. Every failure is appended as an observation and the loop continues, so the next brain call sees the error and can correct. No silent repair inside the activity — one model call per activity keeps latency predictable and keeps the struggle visible in the transcript, which is the thing being demoed.

5. **Three endings, and "no better candidate" is a result, not an error.** The loop ends on (a) `conclude` — the normal ending; (b) the step cap, reason `budget_exhausted`; (c) a brain that cannot be reached at all (ollama down, no fallback), which fails the run. The ending is a typed terminal entry so the console and [Lock the run semantics](T06-lock-the-run-semantics.md) render it without guessing. A run that concludes without proposing is a legitimate, visible outcome — forcing a proposal every time would undermine the credibility the approval gate rests on.

**Amended by [Lock the run semantics](T06-lock-the-run-semantics.md):** there is a **fourth** terminal reason, `no_progress`, raised when the same tool is called with the same arguments twice in a row. The full set is therefore `concluded` / `budget_exhausted` / `no_progress` / `failed`, and the console renders all four.

6. **We hand-roll the loop, with two deliberate divergences recorded.** (a) Activities are referenced **by string name**, so the workflow module never imports the LLM SDK. That is stricter than Temporal's cookbook, which imports the SDK behind the sandbox pass-through hatch because its plugin intercepts the call and reroutes it to an activity; we have no plugin, so we keep the repo's existing discipline (`services/worker/workflows.py` already does this for `promote_stage`). **Note what this is not**: the LLM call is still part of the workflow — it executes as an activity, its result lands in history, and the workflow's control flow depends on it. The string-name rule is about *which module imports the SDK*. (b) **Every tool is an activity**, stricter than Temporal's guidance that deterministic tools may run inline. Defensible here because every tool is I/O against the platform — MLflow, training, promotion requests — and uniformity keeps "the transcript is history" true without exception. The alternative (adopting Temporal's OpenAI Agents SDK integration via LiteLLM) was offered and rejected: it adds dependencies, its support matrix does not list ollama, and it brings its own state handling.

**The replay rule, stated for the build session:** every decision the loop makes must derive only from values already recorded — the goal and the transcript. Nothing may be sampled inside workflow code from a source outside history: no `datetime.now()` or `time.time()` — use Temporal's deterministic **workflow clock** (`workflow.now()` / `workflow.time()`), which the SDK provides precisely for this — no stdlib `random` (use `workflow.random()`), no environment, no model. Anything that must vary per run is obtained through an activity and is therefore recorded before it is acted on. This is the property that makes the killed-worker resume work, and the first thing to check if a replay ever diverges.

**Consequence noted, not asked:** at cap 8 with bounded entries the full transcript is passed to the brain on every call — no compaction or summarisation is needed at this size.

Graduates no fog: mid-run steering still waits on [Lock the run semantics](T06-lock-the-run-semantics.md), the console's dead-window rendering on T04 + T06, and concurrent investigations on [Define the agent's tool surface & schemas](T02-define-the-agent-tool-surface-and-schemas.md).

Narrows [Define the agent's tool surface & schemas](T02-define-the-agent-tool-surface-and-schemas.md) (exactly one tool per decision; `conclude` is terminal), [Decide where the agent transcript lives](T04-decide-where-the-agent-transcript-lives.md) (entry shape settled; the store and read path remain), and [Lock the run semantics](T06-lock-the-run-semantics.md) (the cap and its unit are settled; wall-clock, retries and fallback selection remain).

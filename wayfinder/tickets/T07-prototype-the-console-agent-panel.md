---
id: T07
title: Prototype the console's agent panel
labels: [wayfinder:prototype]
status: closed
assignee: "dsh session"
blocked-by: [T03, T04]
---

## Question

What does the agent panel actually look like and read like, live, while a run is in flight?

This is a **prototype** ticket: build the cheapest rough artifact that lets the human react — a static mock in the console's own style (`ui/src/App.jsx` + `style.css` conventions: `<section>`, `.row`, `.hint`, `.err`) with fake transcript data is enough. Do not wire it to a real workflow.

What the human needs to judge:

- **How the transcript reads.** Thought / tool call / observation as rows, a chat, or a timeline? The demo's punch is watching the reasoning, so legibility at a glance matters more than density.
- **The durability moment.** What the panel shows while the worker is dead (stale? "worker down, run durable"?), and what it shows when the run resumes — the resume has to be *visible*, or the demo's climax happens off-screen.
- **The proposal**, presented with the evidence [Decide the proposal handoff into the approval gate](T05-decide-the-proposal-handoff-into-the-approval-gate.md) settles, and the existing Approve button as the only way it goes live.
- **Budget and state visibility** — steps used, elapsed time, and whether the scripted fallback is in play.
- **Where the panel lives** — a new sidebar entry alongside the existing inline console, a section of it, or a tab. The console is a single-origin harness with a sidebar (`/diagrams/`, `/temporal/`, `/mlflow/` are frame/link-out tabs).

Deliverable: a throwaway mock the human reviews. Its resolution records what was accepted, and the build work later graduates from it.

## Three rendering requirements inherited from the run semantics

[Lock the run semantics](T06-lock-the-run-semantics.md) settled things the panel must show honestly:

- **Elapsed work time apart from time spent waiting on the human gate.** The three-minute ceiling excludes the approval wait, so a single combined clock would misrepresent a run that is correctly waiting on the operator — the mock must show the two separately.
- **Which of the four terminal reasons ended a run**: `concluded`, `budget_exhausted`, `no_progress`, `failed`.
- **Which producer made each decision.** Every fallback decision is labelled, because the map's standing preference is that the demo never silently pretends.

## Inherited from how a run starts and where the transcript comes from

[Decide how an investigation starts](T03-decide-how-an-investigation-starts.md) and [Decide where the agent transcript lives](T04-decide-where-the-agent-transcript-lives.md) settled two things the mock should already assume:

- The start affordance is a **goal field with one-click presets** filling the same input, plus who is asking.
- The transcript is **projected from Temporal history**, so the panel is showing exactly what the console can see when history is all it has — including while the worker is dead.

## Inherited from the proposal handoff

[Decide the proposal handoff into the approval gate](T05-decide-the-proposal-handoff-into-the-approval-gate.md) settled what the approval card contains, and left the mock one question of its own:

- The card shows the **candidate version, its metrics against the incumbent on the same split, the rationale, and the cost paid** (steps used, trainings run), with a way through to the transcript.
- Because the run now **waits** on the operator, the console shows an `awaiting-approval` run — and the mock must decide whether the operator can **cancel** one, since that is the only escape from never deciding.
- One pending promotion per model: the mock should not design a queue, because a second proposal is refused.

## Resolution

**Verdict: the Timeline, in its own sidebar entry.** The other two were rejected for reasons that matter to the demo:

- **Scratchpad (chat)** — the most familiar and the densest, and mounting the panel as a *section of the Ops Console* is a genuinely good placement argument; rejected because the chat metaphor imports an expectation the agent does not meet (this is a control loop with a cap of 8, not a conversation), and because it flattens the endings — `budget_exhausted`, `no_progress` and `failed` arrive as just more bubbles, and the endings are where this demo's honesty lives.
- **Inspector (two-pane)** — the right shape for *operating* this daily, and the one that answers "why did it pick max_depth 6?"; rejected because a demo is not debugging: its punchline sits behind a click, and any step that needs a click in front of an audience is a place the demo can die.

**Why the spine wins.** The demo's climax is a *sequence*, and a vertical spine makes "what is recorded so far" a property of the layout rather than a sentence someone has to read — the rail stops where history stops. It also makes the loop contract visible: one step = one brain call → one tool call → one observation reads as a repeating unit.

**Three changes agreed after the variants were seen:**

1. **The worker's death breaks the rail** — a gap in the spine (`✕` node, dashed rail), not a banner over a live spine. The structural version is the one that reads as lost history rather than as a message.
2. **An in-progress `deciding…` node with a running clock.** At a measured 2.9 s per brain call an 8-step run is ~25 s of on-screen stillness; without this the panel reads as a log dump rather than something thinking. Streaming the rationale was considered and rejected as the alternative: the decision arrives as one activity result, which is what keeps the run replayable.
3. **The fallback is spelled out once** — "scripted policy — ollama unreachable, so the loop fell back to its deterministic policy rather than stopping" — never a bare chip a room cannot interpret.

**Stolen from the rejected variants:** the Scratchpad's **composer** as the start affordance (a goal field that looks like somewhere you would type a sentence, frozen while a run is in flight, with presets filling the same field) and the Inspector's scannable one-line step header (`step 4 · train_candidate · 21.4s · [chip]`) so the spine can be skimmed before the reasoning is read.

**Cancel stays, but not as a peer of Approve and Decline.** Those two decide the *promotion*; abandoning decides the *run* — different objects, so it is visually separated with its own consequence stated (abandoning withdraws the pending promotion, leaving no orphan waiting). Without it, "the operator never decides" parks a run at `awaiting-approval` with no way out of the UI.

**Captured.** The three-variant exploration is the primary source and lives on the **local branch `prototype/agent-panel-variants`**. The winning mock is `prototype/agent-panel.html`, served from the console's own origin (mounted like `diagrams/`, no login) while the build is pending, and it comes off main — with its compose mount — once the panel exists in `ui/src/App.jsx`.

**Not decided here, and not needed to judge the design:** the projection's field names, how the panel polls, and whether the panel is a router route or a sidebar tab. The mock shows the shape, not the wiring.

**Graduated to build tickets:** [B05](B05-build-the-console-panel.md) carries this design into the console; [B06](B06-script-the-kill-and-the-resume.md) is where the demo moment itself gets scripted.

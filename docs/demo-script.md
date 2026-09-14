# The durability demo, scripted

This is the demo the whole agent effort was for: an investigation that survives the
platform dying underneath it, and a decision that a person makes. It is written to be
run from the console at <https://mlops.srv1567269.hstgr.cloud> with the **Agent** tab,
Temporal UI open in another tab, and a terminal for the kill.

Three acts. Act 2 is the point; Acts 1 and 3 exist so Act 2 lands.

---

## Step 0 — put the incumbent where the win is reachable

```bash
DEMO_INCUMBENT=weakest ./scripts/demo-reset.sh
```

One command, both jobs: it clears stale promotions, restores `AGENT_FALLBACK=auto`,
archives unpromotable staging versions, reports the state — and pins the incumbent so
the gate is reachable today.

**Why a weak incumbent.** The agent proposes only when a candidate genuinely beats the
version serving production, so against a strong incumbent it does the honest thing and
*concludes* — "no better candidate" — which is the most convincing behaviour in the demo
(T01) and also makes the human gate, the demo's climax, unreachable on demand: Acts 2
and 3 then have nothing to stand on when the presenter needs them. Step 0 buys a
reachable gate, and it does not buy a rigged one:

- `weakest` picks the version with the **lowest recorded `roc_auc`** among the versions
  whose artifact is present (`artifact_problem` — the product's own servability rule),
  and sends traffic to it through the same `POST /api/models/rollback` path
  `DEMO_INCUMBENT=N` uses.
- It is picked **by score, not by a magic number**: a real registered version, genuinely
  worse than the others, and servable. The script prints it beside the **strongest**
  score, so the size of the gap is on screen rather than in a footnote.
- The agent still measures real numbers on the held-out split and still decides for
  itself; nothing about the loop, the tools or the gate changes.

**Say this out loud, because it is the honest framing.** *The win is deliberately set
up.* The agent is not beating a strong model here — it is finding a better candidate
than a weak one, which is exactly the comparison a promotion gate exists to make. A
presenter who skips that sentence invites the room to conclude the agent beat the best
model in the registry, and it did not.

**What to expect, in order:** the agent reads the registry, scores the incumbent on the
held-out split, trains a candidate — or, more often than you would guess, finds its
hyperparameters already registered and reuses that version, because idempotency is keyed
on the data and the hyperparameters — scores what it found, and, if something beats the
pinned incumbent, files the promotion and sits at the gate waiting on you. It proposes
the best thing it has real numbers for, which can be an existing Staging candidate rather
than a fresh one: in the recorded arc below, both of its training calls reused existing
versions (v15, v6) and it proposed v41, whose numbers it had just re-measured itself. If
nothing beats even this incumbent, it concludes honestly instead; that is still a
legitimate ending, and the retry is to ask again.

A recorded arc with step 0 applied, so the narration has a shape to expect: v18 pinned
(roc_auc 0.9471, held-out accuracy 0.8860 as the agent re-measured it), 7 steps and 77 s
of work, one truncated decision absorbed as an observation and a step, and a proposal of
v41 — 0.9561 accuracy and 0.9914 roc_auc on the *same* split — waiting at the gate.

If the script exits non-zero, fix what it names before an audience is watching — it is
the only thing standing between you and a demo that starts with a 409 because some
earlier run left a promotion parked at the gate.

Then open the console, sign in as `operator` / `operator-pass`, and click **Agent**.

**One optional detour worth 30 seconds, if the room asks who trains here.** The console's
*Train a candidate* panel takes the same family choice the agent's `train_candidate` tool
does: pick `logistic_regression` and its inputs become `C` / `max_iter`, pick
`gradient_boosting` and they become the three knobs they have always been — the panel is
generated from the trainer's own definitions (`GET /api/models/kinds`), so it offers
exactly what the trainer accepts and a bad family or a bound comes back as a 400 on the
spot. The version table then names the family that produced each row. The agent and the
human are two doors into one trainer: same registry name, same split, same two metrics,
same idempotency key. What differs is only who decides — and the seed trainer
(`--profile tools`) is the one entry point that stays gradient-boosting only.

---

## Act 1 — An investigation, and a decision you make

**Type the goal** (the **Find a better candidate** preset is a shorter version of the
same sentence, and fills the same field — say so, it is the same input):

> Train a new candidate for the breast-cancer classifier, evaluate it against the
> version serving production on the held-out split, and propose it for promotion — I
> will make the call.

That last clause is doing work. The agent is honest, so if nothing beats production it
will **conclude** with "no better candidate" instead of proposing — which is a
legitimate ending (T01), not a bug, and worth saying out loud if it happens, because it
is the most convincing thing in the demo. If it happens and you wanted a gate, that is
your retry: ask again, with the clause above. The script copes with both. With step 0's
weak incumbent it should propose — the honest conclusion is now the fallback rather than
the default, which is the whole reason step 0 exists.

**Start it, then let the spine fill.** Narrate the loop contract as it does, because the
panel is showing it: *one step is one brain call, one tool call, one observation — eight
steps at most, and every step it took is in the run's event history.*

Points to make while it works, in the order they appear:

- **The header line of each step** (`step 4 · train_candidate · 25.9s · [model]`) is
  there so the spine can be skimmed before anyone reads the reasoning.
- **The two clocks are two clocks.** *Work* is what the agent spent. *Waiting on you* is
  a different fact and starts when it asks. A run correctly waiting for a person must
  not look like a slow agent.
- **Nothing here is a chat.** The agent cannot ask a question and it does not stream its
  thinking; the rationale is recorded after the fact, which is what keeps the run
  replayable.

**When it reaches the gate, stop and read the card aloud.** It shows the candidate
against the version currently serving, on the same held-out split, the reason it gave,
and what the decision cost in steps and trainings. This is where the run is *waiting*
rather than working — the clock says so.

**Approve it.** Watch the version move to Production, and the run end `concluded`. The
promotion is the durable workflow; the click is only how the workflow learns your answer.

---

## Act 2 — Kill the worker (the durability claim)

Start a **second** investigation with the same goal, and let it run.

### The moment to kill

Kill at the **approval gate** — wait until the card appears, then kill. Nothing is in
flight there, so the resume is immediate. This is the deliberate choice, not the timid
one: killing mid-run proves the same claim, but Temporal will not retry an activity
until its start-to-close timeout expires, so the audience watches a frozen run for up to
three minutes (measured: **183 s of wall-clock for 148 s of work**) before it moves. At
the gate, the freeze lasts as long as your narration does.

If you want the harder version anyway — killing mid-run — aim at the middle of the run,
where the transcript is long and the steps are slow, and say out loud that the wait you
are about to have is a *timeout*, not a lost run. The panel does its part: the in-flight
step shows `running <tool>…` with its clock still moving, and after twenty seconds of
silence it says **"no worker is answering. The run is frozen, not lost: every step above
is already in event history."** That sentence is the demo.

### The kill

```bash
docker kill mlops-demo-worker
```

The worker does **not** come back on its own — `restart: unless-stopped` does not cover a
kill, and the container sits at `Exited (137)`. That is better for this demo: the freeze
stays on screen as long as you need it.

**What to say, exactly.** Not *"nothing ever runs twice"* — that is not true, and the
sources do not support it. Say:

> The run resumes where it was, and an interrupted activity runs again.

Then say why that is still the right design: the step it is on will be attempted again,
and every activity in this loop is safe to attempt twice. Training asks whether a version
already exists for exactly these hyperparameters and this data, and reuses it rather than
registering a second one. The promotion refuses a second pending request for the same
model. Nothing about the *record* is at risk: the transcript is the workflow's own event
history, written by the server, and it is already on disk.

**Show the evidence while it is dead:**

- The panel: every completed step still there, the in-flight step `pending`.
- Temporal UI: the same run, `Running`, with its history — this is what "durable" means.
- Refresh the console tab. Nothing disappears, because the panel is not asking the
  worker anything; it reads history from the Temporal server (`source: temporal-history`).

### Bring it back

```bash
docker compose start worker
```

The run continues from where history stops. When it finishes, the step that was
interrupted carries an **`interrupted · ran again`** chip and `attempts=2`, and the run
reports how many times it was interrupted. That chip is durable: it is read from the
activity's own attempt numbers, so it is still there tomorrow.

Finish the act by deciding the promotion — **decline it**, and say why that is not a
throwaway: a decline moves nothing, which keeps the question open. Approving promotes the
best candidate, and then the *next* investigation honestly concludes that nothing beats
production and never reaches a gate at all. (This is not hypothetical: a rehearsal that
approved every pass walked production from v7 to v19 and then could not find a gate
anywhere.) Keep approving for Act 1 if you want to show a promotion landing; decline in
Act 2 so Act 3 still has something to propose.

If you want the incumbent where you left it, `DEMO_INCUMBENT=7 ./scripts/demo-reset.sh`
pins production back to v7. And `DEMO_INCUMBENT=weakest` re-runs step 0, which is what
you want before the next rehearsal — the gate has to be reachable again.

---

## Act 3 — The fallback, on purpose (optional, 60 s)

The agent's brain is a model. When the model is unavailable the loop does **not** stop:
it falls back to a deterministic scripted policy and *labels every decision it made*.
Show it deliberately rather than waiting for it to happen:

```bash
AGENT_FALLBACK=on docker compose up -d --force-recreate worker
```

Start a run and watch: every step carries a **`scripted policy`** chip, and the panel
spells the situation out once, above the spine, rather than leaving a room to interpret
a chip:

> **scripted policy** — ollama was unreachable, so the loop fell back to its
> deterministic policy instead of stopping. Every decision it made is labelled.

Then put it back — this is part of the reset, and forgetting it means every later run
looks scripted:

```bash
AGENT_FALLBACK=auto docker compose up -d --force-recreate worker
```

---

## If you would rather show a run dying than waiting: kill its promotion

A run parked at the gate is a run with nothing to lose yet. A stronger ending is to take
away the thing it is waiting for: `docker compose stop` the worker is *not* this — this
is terminating the **promotion** while the agent sits at the gate.

In Temporal UI, find the `PromotionWorkflow` for the pending promotion and terminate it.
Within 30 s the agent's gate poll notices, and the run records a **failure** with the
reason, instead of waiting for ever for an answer that can no longer come.

Prefer the console's **Abandon run** when you want the tidy version: it terminates the
run *and* withdraws the promotion it filed, so nothing is left waiting at the gate for a
run that no longer exists. That is the difference — abandoning decides the run, and
approve/decline decide the promotion.

---

## Between runs

```bash
DEMO_INCUMBENT=weakest ./scripts/demo-reset.sh   # step 0 again: a reachable gate for the next run
```

It terminates anything still pending, archives staging versions whose artifact is gone
(they can never be promoted, and a run that evaluates one wastes a step finding out),
leaves alone any version registered in the last three minutes — MLflow creates versions
asynchronously, so a fresh one can look artifact-less — restores `AGENT_FALLBACK=auto`,
pins the incumbent when asked (an explicit `DEMO_INCUMBENT=N`, or `weakest` for the
servable version with the lowest recorded `roc_auc`), and prints the pinned version with
the weakest/strongest scores plus the candidates a run is likely to choose between. Run
it before every rehearsal, not just before the real thing: the demo's own state is the
easiest thing to leave broken.

---

## Numbers the narration can rely on

All measured on this deployment, not estimated:

| Thing | Number |
|---|---|
| Brain latency, cloud model | p50 12.9 s, max 36.5 s; early steps ~2–5 s |
| A whole 5–7 step investigation | 40–150 s of work |
| A training (tiny dataset) | 5–30 s; a repeat of the same hyperparameters is reused in ~5 s |
| Cost of a mid-run kill | up to the activity's start-to-close: 180 s brain, 60–120 s reads, 5 min training |
| Cost of a kill at the gate | nothing — the resume is immediate |
| Resume after a long outage | immediate; the timeout already expired while nothing ran |
| Step cap / work ceiling | 8 steps / 6 minutes of *step* time, and waiting on you is excluded |

## What this demo does not claim

- **Not exactly-once.** An interrupted activity runs again (T09's at-least-once hole).
  Every activity here is safe to repeat, and the reuse is shown, not asserted.
- **Not that the step cap is a framework feature.** Temporal ships no step bound; this
  one is ours.
- **Not that a kill is free.** Mid-activity kills cost the activity's timeout in wall
  clock, which is why the script kills at the gate.

import React, { useEffect, useState } from "react";

import { api, errorText } from "./api.js";

/**
 * The investigation agent panel — T07's Timeline, carried into the console.
 *
 * Every field it renders comes from `GET /api/agent/runs/{id}`, which projects
 * the run out of Temporal's **event history**. That is the whole reason the panel
 * keeps working while the worker is dead: it is not asking the worker anything.
 * The rail that breaks, the `deciding…` clock and the two clocks are all
 * consequences of reading history rather than a live process.
 */

const POLL_MS = 1500;

// How long a step may sit in flight before the panel says what is actually
// happening. A brain call takes seconds; a killed worker takes minutes, and the
// difference deserves different words rather than a spinner that means "soon".
const QUIET_BEFORE_FROZEN_S = 20;

const PRESETS = [
  {
    label: "Is production still the best?",
    goal: "Check whether the version serving production traffic is still the best candidate we have, and say what you would do next.",
  },
  {
    label: "Find a better candidate",
    goal: "Compare the version currently serving against a fresh candidate, and propose the stronger one for promotion.",
  },
  {
    label: "Audit what is serving",
    goal: "Audit the version taking production traffic: is its artifact intact, how does it score on the held-out split, and is anything else close?",
  },
];

const STATE_LABEL = {
  running: "running",
  "awaiting-approval": "awaiting approval",
  concluded: "concluded",
  failed: "failed",
  cancelled: "cancelled",
  terminated: "abandoned",
};

// The four endings, said plainly. `budget_exhausted` and `no_progress` are
// results, not errors: a run that stopped for a stated reason is the honesty
// this demo is for, so they must not be dressed up as failures.
const ENDING = {
  concluded: { label: "Concluded", cls: "ok" },
  budget_exhausted: { label: "Ended — work ceiling reached", cls: "warn" },
  no_progress: { label: "Ended — no progress", cls: "warn" },
  failed: { label: "Failed", cls: "bad" },
};

const METRICS = ["accuracy", "roc_auc", "precision", "recall"];

const fmt = (s) => {
  if (s == null) return "—";
  if (s < 1) return `${s.toFixed(1)}s`;
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s`;
};

const since = (iso) => (iso ? Math.max(0, (Date.now() - Date.parse(iso)) / 1000) : 0);
const metric = (m, k) => (m && m[k] != null ? Number(m[k]).toFixed(4) : "—");

function Clocks({ run }) {
  return (
    <div className="clocks">
      <span title="Time the agent actually worked. Excludes time spent waiting on you, and time when the platform was not running.">
        work <b>{fmt(run.work_seconds)}</b>
      </span>
      <span title="Time this run has spent waiting for an operator decision.">
        waiting on you <b>{fmt(run.waiting_seconds)}</b>
      </span>
      <span title="Wall-clock since the run started.">elapsed <b>{fmt(run.elapsed_seconds)}</b></span>
    </div>
  );
}

function ApprovalCard({ run, onDecide, onAbandon, confirming, setConfirming, busy }) {
  const p = run.promotion;
  const decided = !!p.outcome;
  const cand = p.evidence?.candidate;
  const inc = p.evidence?.incumbent;
  return (
    <section className="gate">
      <header>
        <h2>
          {decided ? "Promotion decided" : "Waiting for you"} — v{p.version}
        </h2>
        <span className={`chip ${decided ? "chip-done" : "chip-wait"}`}>
          {decided
            ? p.outcome.promoted
              ? `approved by ${p.outcome.approved_by} — now serving`
              : p.outcome.approved === false
                ? `declined by ${p.outcome.declined_by}`
                : `did not complete: ${p.outcome.failed || p.outcome.status || "unknown"}`
            : "awaiting approval"}
        </span>
      </header>

      {!decided && (
        <p className="hint">
          The run is <b>alive</b> and stays alive until you decide — it is not blocked, it is waiting.
          Your answer reaches it through Temporal, and the run records what actually happened, not that
          someone clicked.
        </p>
      )}

      <table className="compare">
        <thead>
          <tr>
            <th>held-out split</th>
            <th>candidate v{p.version}</th>
            {/* The incumbent's id is not in the run projection — the proposal
                carries its metrics, not its version number — so the column names
                what the column actually holds rather than heading every run with a
                version that was never read. */}
            <th>incumbent (serving)</th>
          </tr>
        </thead>
        <tbody>
          {METRICS.map((k) => (
            <tr key={k}>
              <td>{k}</td>
              <td>{metric(cand, k)}</td>
              <td>{metric(inc, k)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {(!cand || !inc) && (
        <p className="hint">
          {!inc
            ? "The run did not evaluate the serving version, so there is nothing to compare against — shown as — rather than invented."
            : "The run did not evaluate the candidate before proposing it."}
        </p>
      )}

      {p.rationale && (
        <p className="rationale">
          <b>Why:</b> {p.rationale}
        </p>
      )}
      {p.cost && (
        <p className="hint">
          cost paid: {p.cost.steps} step{p.cost.steps === 1 ? "" : "s"}, {p.cost.trainings} training
          {p.cost.trainings === 1 ? "" : "s"}
        </p>
      )}

      <div className="row">
        {!decided && (
          <>
            <button onClick={() => onDecide(true)} disabled={busy}>
              Approve v{p.version}
            </button>
            <button className="ghost" onClick={() => onDecide(false)} disabled={busy}>
              Decline
            </button>
          </>
        )}
      </div>

      {!decided && (
        <div className="abandon">
          <span>
            Abandoning decides the <b>run</b>, not the promotion: it withdraws the request and leaves
            nothing waiting at the gate.
          </span>
          {confirming ? (
            <span className="abandon-actions">
              <button className="danger" onClick={onAbandon} disabled={busy}>
                Confirm — abandon the run and withdraw v{p.version}
              </button>
              <button className="ghost" onClick={() => setConfirming(false)} disabled={busy}>
                Keep it waiting
              </button>
            </span>
          ) : (
            <button className="ghost" onClick={() => setConfirming(true)} disabled={busy}>
              Abandon run…
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function Step({ s }) {
  const inFlight = s.pending ? since(s.at) : 0;
  const frozen = s.pending && inFlight > QUIET_BEFORE_FROZEN_S;
  return (
    <li className={`node${s.pending ? " pending" : s.ok ? " ok" : " bad"}${s.interrupted ? " broken" : ""}${frozen ? " frozen" : ""}`}>
      <div className="node-head">
        <span className="node-step">step {s.step}</span>
        <span className="node-tool">{s.tool || (s.pending ? "deciding" : "no tool call")}</span>
        {!s.pending && <span className="node-secs">{fmt(s.seconds)}</span>}
        {s.producer && (
          <span className={`chip ${s.producer === "model" ? "chip-model" : "chip-fallback"}`}>
            {s.producer === "model" ? "model" : "scripted policy"}
          </span>
        )}
        {s.interrupted && <span className="chip chip-break">interrupted · ran again</span>}
      </div>

      {s.rationale && <p className="node-rationale">{s.rationale}</p>}

      {s.pending ? (
        <p className="node-obs deciding">
          {s.phase === "calling" ? (
            <>
              running <b>{s.tool}</b>…
            </>
          ) : (
            <>deciding…</>
          )}{" "}
          <b>{fmt(inFlight)}</b>
          {frozen && (
            <span className="frozen-note">
              {" "}
              — no worker is answering. The run is frozen, not lost: every step above is already in
              event history, and it continues from here when a worker returns.
            </span>
          )}
        </p>
      ) : (
        <p className="node-obs">{s.observation || <em>no observation</em>}</p>
      )}
    </li>
  );
}

export function AgentPanel({ me }) {
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState(null);
  const [run, setRun] = useState(null);
  const [goal, setGoal] = useState(PRESETS[1].goal);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [, setTick] = useState(0);

  const live = run && (run.state === "running" || run.state === "awaiting-approval");

  // Poll the read path. It is a Temporal-history projection, so this keeps
  // returning the truth whether the worker is up, restarting, or dead.
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await api("/api/agent/runs");
        const body = await r.json().catch(() => null);
        if (!alive) return;
        if (!r.ok) throw new Error(errorText(body, r.status));
        setRuns(body.runs || []);
        setErr(null);
      } catch (e) {
        if (alive) setErr(String(e.message || e));
      }
    };
    load();
    const t = setInterval(load, POLL_MS * 2);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (!runId) return undefined;
    let alive = true;
    const load = async () => {
      try {
        const r = await api(`/api/agent/runs/${encodeURIComponent(runId)}`);
        const body = await r.json().catch(() => null);
        if (!alive) return;
        if (!r.ok) throw new Error(errorText(body, r.status));
        setRun(body);
        setErr(null);
      } catch (e) {
        if (alive) setErr(String(e.message || e));
      }
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [runId]);

  // A local ticker for the clocks that must visibly move: the `deciding…` node
  // and the elapsed time. Without it the panel reads as a log dump rather than
  // something thinking (T07).
  useEffect(() => {
    if (!live) return undefined;
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [live]);

  const selected = runs.find((r) => r.run_id === runId);

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api("/api/agent/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal }),
      });
      const body = await r.json().catch(() => null);
      if (!r.ok) setErr(errorText(body, r.status));
      else {
        setConfirming(false);
        setRunId(body.run_id);
      }
    } finally {
      setBusy(false);
    }
  };

  const decide = async (approved) => {
    const p = run?.promotion;
    if (!p) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api(
        `/api/models/${encodeURIComponent(p.version)}/approve?workflow_id=${encodeURIComponent(
          p.workflow_id,
        )}&approved=${approved}`,
        { method: "POST" },
      );
      const body = await r.json().catch(() => null);
      if (!r.ok) setErr(errorText(body, r.status));
    } finally {
      setBusy(false);
    }
  };

  const abandon = async () => {
    if (!run) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api(`/api/agent/runs/${encodeURIComponent(run.run_id)}/cancel`, {
        method: "POST",
      });
      const body = await r.json().catch(() => null);
      if (!r.ok) setErr(errorText(body, r.status));
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  };

  const ending = run?.terminal ? ENDING[run.reason] || { label: run.reason, cls: "warn" } : null;

  return (
    <div className="ops agent">
      <header>
        <h1>Investigation agent</h1>
        <span className="who">a durable ReAct loop — 8 steps at most, one tool call each</span>
      </header>

      {err && (
        <div className="err" role="alert">
          {err}
        </div>
      )}

      <section className="composer">
        <h2>Give it a goal</h2>
        <textarea
          rows={3}
          aria-label="Goal for the investigation"
          value={live ? run.goal : goal}
          disabled={!!live}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="Ask it to look into something…"
        />
        <div className="row">
          {PRESETS.map((p) => (
            <button
              key={p.label}
              className="ghost"
              disabled={!!live || busy}
              onClick={() => setGoal(p.goal)}
              title={p.goal}
            >
              {p.label}
            </button>
          ))}
          <button onClick={start} disabled={!!live || busy || !(live ? run.goal : goal).trim()}>
            {busy ? "Starting…" : "Start an investigation"}
          </button>
        </div>
        <p className="hint">
          {live
            ? "Frozen: this text is the running run's input, recorded in its event history. Abandon the run or wait for it to end to start another."
            : "The goal becomes the workflow's input, so it is recorded and replays with the run. Asking as " + (me?.username || "you") + "."}
        </p>
      </section>

      {runs.length > 0 && (
        <section className="runs">
          <h2>Runs</h2>
          <div className="run-list">
            {runs.map((r) => (
              <button
                key={r.run_id}
                className={`run-pill${r.run_id === runId ? " active" : ""}`}
                onClick={() => {
                  setRunId(r.run_id);
                  setConfirming(false);
                }}
                title={r.goal}
              >
                <span className={`state state-${r.state}`}>{STATE_LABEL[r.state] || r.state}</span>
                <code>{r.run_id}</code>
                <span className="pill-meta">
                  {r.step_count} step{r.step_count === 1 ? "" : "s"}
                  {r.interruptions ? ` · ${r.interruptions} interruption${r.interruptions === 1 ? "" : "s"}` : ""}
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {run && (
        <section className="run">
          <div className="run-head">
            <div>
              <span className={`state state-${run.state}`}>{STATE_LABEL[run.state] || run.state}</span>{" "}
              <code>{run.run_id}</code>
              <span className="hint"> · asked by {run.requested_by || "?"}</span>
            </div>
            <Clocks run={run} />
          </div>
          <p className="goal-line">“{run.goal}”</p>
          <p className="hint source">
            projected from Temporal event history — which is why this panel still shows every recorded
            step while the worker is stopped.
            {run.interruptions > 0 &&
              ` This run was interrupted ${run.interruptions} time${run.interruptions === 1 ? "" : "s"} and continued.`}
          </p>

          {run.promotion && (
            <ApprovalCard
              run={run}
              onDecide={decide}
              onAbandon={abandon}
              confirming={confirming}
              setConfirming={setConfirming}
              busy={busy}
            />
          )}

          {ending && (
            <div className={`ending ${ending.cls}`}>
              <b>{ending.label}</b>
              <p>{run.terminal.detail}</p>
              {run.terminal.answer && <p className="answer">{run.terminal.answer}</p>}
              {run.terminal.evidence && <p className="hint">evidence: {run.terminal.evidence}</p>}
            </div>
          )}

          {run.steps.some((s) => s.producer && s.producer !== "model") && (
            <p className="hint fallback-note">
              <b>scripted policy</b> — ollama was unreachable, so the loop fell back to its deterministic
              policy instead of stopping. Every decision it made is labelled.
            </p>
          )}

          <ol className="spine" aria-label="Steps recorded in this run's event history">
            {run.steps.map((s) => (
              <Step key={s.step} s={s} />
            ))}
          </ol>

          {run.steps.length === 0 && <p className="hint">No step has been recorded yet.</p>}
        </section>
      )}

      {!run && runs.length === 0 && (
        <section>
          <h2>Nothing has run yet</h2>
          <p className="hint">
            Start an investigation above. The run is a Temporal workflow: kill the worker mid-run and it
            resumes from its own history, with nothing to prove other than what history says.
          </p>
        </section>
      )}
    </div>
  );
}

import React, { useEffect, useState } from "react";

import { AgentPanel } from "./AgentPanel.jsx";
import { api, errorText } from "./api.js";

/**
 * mlops-demo — Model Lifecycle Ops Console → single-origin harness.
 * Left sidebar switches tabs between the inline lifecycle console and
 * embedded same-origin apps (diagrams, Temporal UI, MLflow UI, API docs).
 * Auth is a JWT held in an HttpOnly cookie set by the api service (same origin).
 */

const API = ""; // same-origin via Nginx gateway

// Sentry can't be embedded (X-Frame-Options: DENY), so it's surfaced as a
// link-out tab that opens the project's Issues view in a new tab.
// Edit these to point at your own Sentry instance / project.
const SENTRY_HOST = "test-q0r.sentry.io";           // e.g. "your-org.sentry.io" or "sentry.io"
const SENTRY_ORG_SLUG = "test-q0r";                  // organization slug
const SENTRY_PROJECT_ID = "4512071434829824";        // project id (numeric, from the DSN)
const SENTRY_URL = `https://${SENTRY_HOST}/organizations/${SENTRY_ORG_SLUG}/issues/?project=${SENTRY_PROJECT_ID}`;

const TABS = {
  ops:                 { kind: "inline", title: "Ops Console", short: "Ops" },
  agent:               { kind: "inline", title: "Investigation Agent", short: "Agent" },
  "diagram-architecture": { kind: "frame",  title: "Architecture", short: "Arch", src: "/diagrams/architecture.html", group: "Diagrams" },
  "diagram-workflow":    { kind: "frame",  title: "Workflow",      short: "WF",   src: "/diagrams/workflow.html",    group: "Diagrams" },
  "diagram-lifecycle":   { kind: "frame",  title: "Lifecycle",     short: "LC",   src: "/diagrams/lifecycle.html",   group: "Diagrams" },
  "diagram-sequence":    { kind: "frame",  title: "Sequence",      short: "Seq",  src: "/diagrams/sequence.html",    group: "Diagrams" },
  "diagram-dataflow":    { kind: "frame",  title: "Data Flow",     short: "DF",   src: "/diagrams/dataflow.html",    group: "Diagrams" },
  temporal:            { kind: "frame",  title: "Temporal UI",    short: "Temporal", src: "/temporal/", group: "Apps" },
  mlflow:              { kind: "frame",  title: "MLflow UI",      short: "MLflow",   src: "/mlflow/",    group: "Apps" },
  docs:                { kind: "frame",  title: "API Docs",       short: "Docs", src: "/docs",        group: "Apps" },
  sentry:              { kind: "link",  title: "Sentry",         short: "Sentry", url: SENTRY_URL, group: "Apps" },
};

const SECTIONS = [
  { label: "Lifecycle", ids: ["ops", "agent"] },
  { label: "Diagrams", ids: ["diagram-architecture", "diagram-workflow", "diagram-lifecycle", "diagram-sequence", "diagram-dataflow"] },
  { label: "Apps & docs", ids: ["temporal", "mlflow", "docs", "sentry"] },
];

const shortLabel = (t) => t.short || t.title;

function useApi() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [me, setMe] = useState(null);

  const refresh = async () => {
    try {
      const [models, routing, events] = await Promise.all([
        api("/api/models").then((r) => r.json()),
        api("/api/models/routing").then((r) => r.json()),
        api("/api/models/events").then((r) => r.json()),
      ]);
      setData({ models, routing, events: events.events || [] });
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    api("/auth/me")
      .then((r) => (r.ok ? r.json() : null))
      .then(setMe)
      .catch(() => setMe(null));
    refresh();
  }, []);

  const call = async (path, opts = {}) => {
    const r = await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const body = await r.json().catch(() => null);
    if (!r.ok) setError(errorText(body, r.status));
    else setError(null);
    refresh();
    return body;
  };
  return { data, error, me, refresh, call };
}

function Login() {
  const [user, setUser] = useState("");
  const [pw, setPw] = useState("");
  return (
    <div className="login">
      <h1>mlops-demo — Model Lifecycle Platform</h1>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const body = new URLSearchParams({ username: user, password: pw });
          api("/auth/token", { method: "POST", body })
            .then((r) => (r.ok ? r.json() : null))
            .then((d) => d && location.reload());
        }}
      >
        <input value={user} onChange={(e) => setUser(e.target.value)} placeholder="username" />
        <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="password" />
        <button>Sign in</button>
      </form>
      <p className="hint">seeded: operator/operator-pass · admin/admin-pass</p>
    </div>
  );
}

function TrainPanel({ refresh }) {
  const [params, setParams] = useState({ n_estimators: 120, max_depth: 3, learning_rate: 0.08 });
  const [job, setJob] = useState(null); // { workflow_id, status, result, error }
  const jobId = job?.workflow_id;
  const jobStatus = job?.status;

  const start = async () => {
    setJob({ status: "STARTING" });
    const r = await api("/api/models/train", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        n_estimators: Number(params.n_estimators),
        max_depth: Number(params.max_depth),
        learning_rate: Number(params.learning_rate),
      }),
    });
    const body = await r.json().catch(() => null);
    if (!r.ok) {
      setJob({ status: "ERROR", error: errorText(body, r.status) });
      return;
    }
    setJob({ workflow_id: body.workflow_id, status: "RUNNING" });
  };

  // Poll the durable workflow until it settles, then refresh the console state.
  useEffect(() => {
    if (!jobId || jobStatus !== "RUNNING") return;
    const timer = setInterval(async () => {
      const r = await api(`/api/models/train/${jobId}`);
      const body = await r.json().catch(() => null);
      if (!r.ok) {
        setJob((j) => ({ ...j, status: "ERROR", error: errorText(body, r.status) }));
        return;
      }
      if (body.status !== "RUNNING") {
        setJob((j) => ({ ...j, status: body.status, result: body.result, error: body.error }));
        refresh();
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [jobId, jobStatus]);

  const set = (k) => (e) => setParams({ ...params, [k]: e.target.value });
  const busy = jobStatus === "RUNNING" || jobStatus === "STARTING";

  return (
    <section>
      <h2>Train a candidate</h2>
      <p className="hint">
        Runs a durable TrainingWorkflow on the worker and registers a <em>new</em> version
        in Staging. An existing version is never modified, and nothing serves traffic
        until you promote it below.
      </p>
      <div className="row">
        <label>
          n_estimators
          <input value={params.n_estimators} onChange={set("n_estimators")} />
        </label>
        <label>
          max_depth
          <input value={params.max_depth} onChange={set("max_depth")} />
        </label>
        <label>
          learning_rate
          <input value={params.learning_rate} onChange={set("learning_rate")} />
        </label>
        <button onClick={start} disabled={busy}>
          {busy ? "Training…" : "Train & register"}
        </button>
      </div>
      {jobId && (
        <p className="status">
          workflow <b>{jobId}</b> — {job?.status}
        </p>
      )}
      {job?.result && <pre>{JSON.stringify(job.result, null, 2)}</pre>}
      {job?.error && <div className="err">{job.error}</div>}
    </section>
  );
}

function PredictPanel() {
  const [featText, setFeatText] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const useSample = () =>
    api("/v1/sample")
      .then((r) => r.json())
      .then((d) => d.features && setFeatText(d.features.join(", ")));

  const run = async () => {
    setBusy(true);
    try {
      const features = featText.split(/[,\s]+/).filter(Boolean).map(Number);
      const r = await api("/v1/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(features),
      });
      setResult({ ok: r.ok, body: await r.json() });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>Predict (live serving)</h2>
      <p className="hint">
        Goes through the same origin to the serving router and loads the real artifact
        for the routed version — so the version it reports is the one that answered.
      </p>
      <textarea
        rows={3}
        value={featText}
        onChange={(e) => setFeatText(e.target.value)}
        placeholder="30 comma-separated feature values"
      />
      <div className="row">
        <button className="ghost" onClick={useSample}>
          Use a sample row
        </button>
        <button onClick={run} disabled={busy || !featText.trim()}>
          {busy ? "Scoring…" : "Predict"}
        </button>
      </div>
      {result && (
        <pre className={result.ok ? undefined : "err"}>{JSON.stringify(result.body, null, 2)}</pre>
      )}
    </section>
  );
}

function InlineConsole({ data, error, call, refresh }) {
  const [version, setVersion] = useState(""); // empty, deliberately: the box used to
  // default to "1", and one unconsidered click of Rollback sent production there.
  // The human-approval gate is keyed by the workflow id that promote returns:
  // the approve signal has to go to *that* workflow, not a placeholder.
  const [pending, setPending] = useState(null); // { version, workflow_id }
  const [note, setNote] = useState(null);
  const weights = data?.routing?.weights || {};

  const startPromotion = async () => {
    if (!version.trim()) return;
    const res = await call(`/api/models/${version}/promote`);
    if (res?.workflow_id) {
      setPending({ version, workflow_id: res.workflow_id });
      setNote(null);
    } else {
      // A 409 here used to look like a dead button: `call` resolved with a body
      // that has no workflow_id, nothing was set, and the promotion that was
      // already waiting at the gate stayed invisible.
      setNote(res?.detail
        ? `promote refused: ${res.detail}`
        : `no promotion started for v${version} — check the error above`);
    }
  };

  return (
    <div className="ops">
      {error && <div className="err">{error}</div>}
      <section>
        <h2>Versions &amp; Stages</h2>
        <table>
          <thead>
            <tr><th>id</th><th>stage</th><th>run</th><th>traffic %</th></tr>
          </thead>
          <tbody>
            {(data?.models?.versions || []).map((v) => {
              // Label a version by whether it serves, not by MLflow's stage. Traffic
              // comes from the routing table, which is the source of truth; the stage
              // is registry history, and a rollback used to leave the displaced
              // version wearing "Production" while nothing routed to it — two rows
              // badged production, one at 0%. "retired" says that out loud instead of
              // showing a second production that is not serving anything.
              const serving = (weights[v.version_id] ?? 0) > 0;
              const label = serving ? "serving" : v.stage === "Production" ? "retired" : v.stage;
              return (
                <tr key={v.version_id} className={serving ? "row-serving" : undefined}>
                  <td>{v.version_id}</td>
                  <td className={`stage-${serving ? "serving" : String(v.stage).toLowerCase()}`}>
                    {label}
                  </td>
                  <td>{v.run_id}</td>
                  <td>{weights[v.version_id] ?? 0}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Routing (canary / blue-green)</h2>
        <ul>
          {Object.entries(weights).map(([vid, w]) => (
            <li key={vid}>version {vid} — {w}%</li>
          ))}
        </ul>
        <label>
          version id for&nbsp;
          <input
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="e.g. 25"
            style={{ width: 56 }}
          />
        </label>
        <button
          disabled={!version.trim()}
          title="files a promotion and waits at the human gate — traffic does not move yet"
          onClick={startPromotion}
        >
          Start a promotion (goes to the gate)
        </button>
        <button
          disabled={!pending}
          title={pending ? `signal ${pending.workflow_id}` : "start a promotion first"}
          onClick={() =>
            pending &&
            call(`/api/models/${pending.version}/approve?workflow_id=${encodeURIComponent(pending.workflow_id)}`)
          }
        >
          Approve
        </button>
        <button
          disabled={!version.trim()}
          title="moves live traffic to this version right now, bypassing the gate"
          onClick={() => {
            // The three buttons are an ask, an answer and an override; the override
            // is the one that moves production with no workflow behind it, so it is
            // the one that asks first. A default of "1" in this box once sent
            // production to a version whose artifact was gone.
            if (!version.trim()) return;
            if (window.confirm(`Send 100% of traffic to v${version} now? This bypasses the approval gate and is not recorded as a promotion.`)) {
              call(`/api/models/rollback?to_version_id=${version}`);
            }
          }}
        >
          Send traffic now (override)
        </button>
        {note && <div className="err">{note}</div>}
      </section>

      <TrainPanel refresh={refresh} />

      <PredictPanel />

      <section>
        <h2>Audit / Lineage (events)</h2>
        <pre>{JSON.stringify(data?.events, null, 2)}</pre>
      </section>
    </div>
  );
}

function Shell({ me, onLogout }) {
  const { data, error, call, refresh } = useApi();
  const [tab, setTab] = useState("ops");
  const active = TABS[tab];

  const renderPane = () => {
    // The agent panel is its own sidebar entry, not a section of the ops console
    // (T07): the console is about the lifecycle's state, this is about one run's
    // history, and mixing them buries the run.
    if (tab === "agent") return <AgentPanel me={me} />;
    if (active.kind === "inline") return <InlineConsole data={data} error={error} call={call} refresh={refresh} />;
    if (active.kind === "link")
      return (
        <div className="linkout">
          <p>
            {active.title} opens in a new tab — a fresh browser session, so any
            login happens there independently of the ops console.
          </p>
          <a className="linkout-cta" href={active.url} target="_blank" rel="noreferrer">
            Open {shortLabel(active)} →
          </a>
        </div>
      );
    return (
      <iframe
        key={tab}
        className="frame"
        title={active.title}
        src={active.src}
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
        onLoad={(e) => {
          // Best-effort height fit inside the flex pane (no page scroll).
          try { e.target.classList.add("loaded"); } catch (_) {}
        }}
      />
    );
  };

  return (
    <div className="harness">
      <aside className="sidebar">
        <div className="brand">mlops-demo</div>
        {SECTIONS.map((sec) => (
          <div className="section" key={sec.label}>
            <div className="section-label">{sec.label}</div>
            {sec.ids.map((id) => {
              const t = TABS[id];
              if (t.kind === "link")
                return (
                  <a
                    key={id}
                    className="nav"
                    href={t.url}
                    target="_blank"
                    rel="noreferrer"
                    title={t.title}
                  >
                    {t.title}
                  </a>
                );
              return (
                <button
                  key={id}
                  className={`nav ${tab === id ? "active" : ""}`}
                  onClick={() => setTab(id)}
                  title={t.title}
                >
                  {t.title}
                </button>
              );
            })}
          </div>
        ))}
        <div className="spacer" />
        <div className="who-line">
          <span title="role">{me.role} @ {me.username}</span>
          <button className="ghost" onClick={onLogout}>Sign out</button>
        </div>
      </aside>
      <main className="pane">
        <div className="pane-head">
          <span className="pane-title">{active.title}</span>
          <span className="pane-group">{active.group || "Lifecycle"}</span>
        </div>
        {renderPane()}
      </main>
    </div>
  );
}

export function App() {
  const [me, setMe] = useState(undefined);

  useEffect(() => {
    api("/auth/me")
      .then((r) => (r.ok ? r.json() : null))
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  if (me === undefined) return null; // still checking
  if (!me) return <Login />;

  return <Shell me={me} onLogout={() => api("/auth/logout", { method: "POST" }).finally(() => location.reload())} />;
}

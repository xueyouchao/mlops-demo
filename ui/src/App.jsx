import React, { useEffect, useState } from "react";

/**
 * mlops-demo — Model Lifecycle Ops Console → single-origin harness.
 * Left sidebar switches tabs between the inline lifecycle console and
 * embedded same-origin apps (diagrams, Temporal UI, MLflow UI, API docs).
 * Auth is a JWT held in an HttpOnly cookie set by the api service (same origin).
 */

const API = ""; // same-origin via Nginx gateway

const TABS = {
  ops:                 { kind: "inline", title: "Ops Console", short: "Ops" },
  "diagram-architecture": { kind: "frame",  title: "Architecture", short: "Arch", src: "/diagrams/architecture.html", group: "Diagrams" },
  "diagram-workflow":    { kind: "frame",  title: "Workflow",      short: "WF",   src: "/diagrams/workflow.html",    group: "Diagrams" },
  "diagram-lifecycle":   { kind: "frame",  title: "Lifecycle",     short: "LC",   src: "/diagrams/lifecycle.html",   group: "Diagrams" },
  "diagram-sequence":    { kind: "frame",  title: "Sequence",      short: "Seq",  src: "/diagrams/sequence.html",    group: "Diagrams" },
  "diagram-dataflow":    { kind: "frame",  title: "Data Flow",     short: "DF",   src: "/diagrams/dataflow.html",    group: "Diagrams" },
  temporal:            { kind: "frame",  title: "Temporal UI",    short: "Temporal", src: "/temporal/", group: "Apps" },
  mlflow:              { kind: "frame",  title: "MLflow UI",      short: "MLflow",   src: "/mlflow/",    group: "Apps" },
  docs:                { kind: "frame",  title: "API Docs",       short: "Docs", src: "/docs",        group: "Apps" },
};

const SECTIONS = [
  { label: "Lifecycle", ids: ["ops"] },
  { label: "Diagrams", ids: ["diagram-architecture", "diagram-workflow", "diagram-lifecycle", "diagram-sequence", "diagram-dataflow"] },
  { label: "Apps & docs", ids: ["temporal", "mlflow", "docs"] },
];

const api = (path, opts = {}) =>
  fetch(`${API}${path}`, { credentials: "include", ...opts });

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
    if (!r.ok) setError(await r.text());
    else setError(null);
    refresh();
    return r.json();
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

function InlineConsole({ data, error, call }) {
  const [version, setVersion] = useState("1");
  const weights = data?.routing?.weights || {};
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
            {(data?.models?.versions || []).map((v) => (
              <tr key={v.version_id}>
                <td>{v.version_id}</td>
                <td className={`stage-${v.stage}`}>{v.stage}</td>
                <td>{v.run_id}</td>
                <td>{weights[v.version_id] ?? 0}</td>
              </tr>
            ))}
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
          canary % for version&nbsp;
          <input value={version} onChange={(e) => setVersion(e.target.value)} style={{ width: 40 }} />
        </label>
        <button onClick={() => version && call(`/api/models/${version}/promote`)}>Promote (gate)</button>
        <button onClick={() => version && call(`/api/models/${version}/approve?workflow_id=wf-demo`)}>Approve</button>
        <button onClick={() => call(`/api/models/rollback?to_version_id=${version}`)}>Rollback</button>
      </section>

      <section>
        <h2>Audit / Lineage (events)</h2>
        <pre>{JSON.stringify(data?.events, null, 2)}</pre>
      </section>
    </div>
  );
}

function Shell({ me, onLogout }) {
  const { data, error, call } = useApi();
  const [tab, setTab] = useState("ops");
  const active = TABS[tab];

  const renderPane = () => {
    if (active.kind === "inline") return <InlineConsole data={data} error={error} call={call} />;
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
            {sec.ids.map((id) => (
              <button
                key={id}
                className={`nav ${tab === id ? "active" : ""}`}
                onClick={() => setTab(id)}
                title={TABS[id].title}
              >
                {TABS[id].title}
              </button>
            ))}
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

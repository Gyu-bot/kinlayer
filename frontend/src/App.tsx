const apiUrl = import.meta.env.VITE_KINLAYER_API_URL ?? "http://127.0.0.1:8765";

function App() {
  return (
    <main className="shell">
      <section className="masthead" aria-labelledby="page-title">
        <p className="eyebrow">Local relationship context layer</p>
        <h1 id="page-title">Kinlayer</h1>
        <p className="summary">
          A correctable, policy-aware relationship memory layer for AI agents.
        </p>
      </section>

      <section className="status-panel" aria-label="Project status">
        <div>
          <span className="label">API</span>
          <strong>{apiUrl}</strong>
        </div>
        <div>
          <span className="label">Web</span>
          <strong>http://127.0.0.1:5173</strong>
        </div>
        <div>
          <span className="label">Database</span>
          <strong>127.0.0.1:15432</strong>
        </div>
      </section>
    </main>
  );
}

export default App;

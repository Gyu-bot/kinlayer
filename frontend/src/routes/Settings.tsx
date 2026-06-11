import {FormEvent, useEffect, useState} from "react";

import {
  apiUrl,
  clearLocalApiToken,
  formatApiError,
  getEmbeddingStatus,
  getOntology,
  getSystemConfig,
  getSystemHealth,
  isLocalApiTokenConfigured,
  setLocalApiToken,
} from "../api/client";
import type {EmbeddingStatus, Ontology, SystemConfig, SystemHealth} from "../types/entities";

export function Settings() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [embedding, setEmbedding] = useState<EmbeddingStatus | null>(null);
  const [ontology, setOntology] = useState<Ontology | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [localTokenConfigured, setLocalTokenConfigured] = useState(isLocalApiTokenConfigured());
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    Promise.all([getSystemHealth(), getSystemConfig(), getEmbeddingStatus(), getOntology()])
      .then(([healthResult, configResult, embeddingResult, ontologyResult]) => {
        setHealth(healthResult);
        setConfig(configResult);
        setEmbedding(embeddingResult);
        setOntology(ontologyResult);
        setError(null);
      })
      .catch((err: unknown) => setError(formatApiError(err)));
  }

  useEffect(() => {
    refresh();
  }, []);

  function saveToken(event: FormEvent) {
    event.preventDefault();
    setLocalApiToken(tokenInput);
    setTokenInput("");
    setLocalTokenConfigured(isLocalApiTokenConfigured());
    refresh();
  }

  function clearToken() {
    clearLocalApiToken();
    setTokenInput("");
    setLocalTokenConfigured(false);
    refresh();
  }

  return (
    <section className="page-section" aria-labelledby="settings-title">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Control Plane</p>
          <h1 id="settings-title">Settings</h1>
        </div>
        <span className="status-chip">{health?.status ?? "loading"}</span>
      </div>

      {error ? <p className="error">{error}</p> : null}

      <div className="settings-grid">
        <section className="panel" aria-labelledby="api-settings-title">
          <h2 id="api-settings-title">API</h2>
          <dl className="definition-list">
            <div>
              <dt>URL</dt>
              <dd>{apiUrl}</dd>
            </div>
            <div>
              <dt>Health</dt>
              <dd>{health ? `${health.status} / database ${health.database}` : "Loading"}</dd>
            </div>
            <div>
              <dt>Server token</dt>
              <dd>{config?.auth_token_configured ? "Required" : "Not required"}</dd>
            </div>
            <div>
              <dt>Local token</dt>
              <dd>{localTokenConfigured ? "Local token configured" : "No local token"}</dd>
            </div>
          </dl>

          <form className="inline-form" onSubmit={saveToken}>
            <label>
              <span>Local API token</span>
              <input
                type="password"
                value={tokenInput}
                autoComplete="off"
                onChange={(event) => setTokenInput(event.target.value)}
              />
            </label>
            <button type="submit">Save token</button>
            <button type="button" className="secondary" onClick={clearToken}>
              Clear
            </button>
          </form>
        </section>

        <section className="panel" aria-labelledby="embedding-settings-title">
          <h2 id="embedding-settings-title">Embedding</h2>
          <dl className="definition-list">
            <div>
              <dt>Provider</dt>
              <dd>{embedding?.provider ?? config?.embedding.provider ?? "Loading"}</dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{embedding?.model ?? config?.embedding.model ?? "Not configured"}</dd>
            </div>
            <div>
              <dt>Dim</dt>
              <dd>{embedding?.dim ?? config?.embedding.dim ?? "Not configured"}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{embedding?.status ?? config?.embedding.status ?? "Loading"}</dd>
            </div>
          </dl>
        </section>
      </div>

      <section className="detail-section">
        <h2>Ontology</h2>
        <div className="ontology-grid">
          <OntologyList
            title="Entity types"
            items={ontology?.entity_types.map((item) => item.value) ?? []}
          />
          <OntologyList
            title="Fact types"
            items={ontology?.fact_types.map((item) => item.value) ?? []}
          />
          <OntologyList
            title="Edge types"
            items={ontology?.edge_types.map((item) => item.relation_type) ?? []}
          />
          <OntologyList
            title="Observation types"
            items={ontology?.observation_types.map((item) => item.observation_type) ?? []}
          />
          <OntologyList
            title="AI policies"
            items={ontology?.policies.ai_use_policies.map((item) => item.value) ?? []}
          />
          <OntologyList
            title="Sensitivity"
            items={ontology?.policies.sensitivity_levels.map((item) => item.value) ?? []}
          />
        </div>
      </section>
    </section>
  );
}

function OntologyList({title, items}: {title: string; items: string[]}) {
  return (
    <div className="ontology-list">
      <h3>{title}</h3>
      <div className="pill-row">
        {items.map((item) => (
          <span className="pill" key={item}>
            {item}
          </span>
        ))}
        {items.length === 0 ? <span className="muted">Loading</span> : null}
      </div>
    </div>
  );
}

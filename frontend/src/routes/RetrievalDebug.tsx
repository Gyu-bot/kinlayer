import {FormEvent, useEffect, useMemo, useState} from "react";

import {formatApiError, listPeople, packContext, retrieveContext} from "../api/client";
import type {Entity} from "../types/entities";
import type {ContextPackResponse, ContextRetrieveResponse, MatchedEntity} from "../types/context";

function compactPayload({
  query,
  situation,
  focalEntityId,
  entityHints,
}: {
  query: string;
  situation: string;
  focalEntityId: string;
  entityHints: string[];
}) {
  const base = {
    query: query.trim(),
    entity_hints: entityHints,
    include_debug: true,
    limit: 10,
  };
  return {
    retrieve: {
      ...base,
      ...(focalEntityId.trim() ? {focal_entity_id: focalEntityId.trim()} : {}),
    },
    pack: {
      ...base,
      ...(focalEntityId.trim() ? {focal_entity_id: focalEntityId.trim()} : {}),
      ...(situation.trim() ? {situation: situation.trim()} : {}),
    },
  };
}

export function RetrievalDebug() {
  const [people, setPeople] = useState<Entity[]>([]);
  const [query, setQuery] = useState("");
  const [situation, setSituation] = useState("");
  const [focalEntityId, setFocalEntityId] = useState("");
  const [entityHints, setEntityHints] = useState<string[]>([]);
  const [showRaw, setShowRaw] = useState(false);
  const [retrieveResult, setRetrieveResult] = useState<ContextRetrieveResponse | null>(null);
  const [packResult, setPackResult] = useState<ContextPackResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listPeople("")
      .then((result) => {
        setPeople(result.items);
        setFocalEntityId((current) => current || result.items[0]?.id || "");
      })
      .catch(() => undefined);
  }, []);

  function runDebug(event: FormEvent) {
    event.preventDefault();
    const payload = compactPayload({query, situation, focalEntityId, entityHints});
    if (!payload.retrieve.query) {
      setError("Query is required.");
      return;
    }
    setLoading(true);
    Promise.all([retrieveContext(payload.retrieve), packContext(payload.pack)])
      .then(([retrieveResponse, packResponse]) => {
        setRetrieveResult(retrieveResponse);
        setPackResult(packResponse);
        setError(null);
      })
      .catch((err: unknown) => setError(formatApiError(err)))
      .finally(() => setLoading(false));
  }

  const pack = packResult?.context_pack;
  const scoreBreakdownByName = useMemo(() => {
    if (!retrieveResult) {
      return {};
    }
    return Object.fromEntries(
      Object.entries(retrieveResult.score_breakdown).map(([entityId, score]) => {
        const match = retrieveResult.matched_entities.find((item) => item.entity_id === entityId);
        return [match?.display_name ?? "Unknown entity", score];
      }),
    );
  }, [retrieveResult]);

  return (
    <section className="page-section" aria-labelledby="retrieval-debug-title">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Retrieval</p>
          <h1 id="retrieval-debug-title">Retrieval Debug</h1>
        </div>
        <span className="status-chip">{pack?.suggested_response_policy ?? "idle"}</span>
      </div>

      <form className="debug-form" onSubmit={runDebug}>
        <label>
          <span>Query</span>
          <textarea value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <label>
          <span>Situation</span>
          <input value={situation} onChange={(event) => setSituation(event.target.value)} />
        </label>
        <label>
          <span>Focal entity</span>
          <select value={focalEntityId} onChange={(event) => setFocalEntityId(event.target.value)}>
            <option value="">None</option>
            {people.map((person) => (
              <option key={person.id} value={person.id}>
                {person.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Candidate entities</span>
          <select
            multiple
            value={entityHints}
            onChange={(event) =>
              setEntityHints(Array.from(event.target.selectedOptions, (option) => option.value))
            }
          >
            {people.map((person) => (
              <option key={person.id} value={person.id}>
                {person.display_name}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={loading}>
          {loading ? "Running..." : "Run debug"}
        </button>
      </form>

      {error ? <p className="error">{error}</p> : null}

      {retrieveResult ? (
        <div className="debug-grid">
          <section className="panel" aria-labelledby="retrieval-matches-title">
            <h2 id="retrieval-matches-title">Matched entities</h2>
            <div className="debug-stack">
              {retrieveResult.matched_entities.map((match) => (
                <MatchedEntitySummary key={match.entity_id} match={match} />
              ))}
              {retrieveResult.matched_entities.length === 0 ? (
                <p className="muted">No matches.</p>
              ) : null}
            </div>
          </section>

          <section className="panel" aria-labelledby="context-pack-title">
            <h2 id="context-pack-title">Context pack buckets</h2>
            <dl className="definition-list compact">
              <div>
                <dt>Confidence</dt>
                <dd>{pack?.confidence ?? "none"}</dd>
              </div>
              <div>
                <dt>Policy</dt>
                <dd>{pack?.suggested_response_policy ?? "none"}</dd>
              </div>
              <div>
                <dt>Ambiguity</dt>
                <dd>{pack?.ambiguity_detected ? "detected" : "clear"}</dd>
              </div>
            </dl>
            <div className="debug-stack">
              {Object.entries(pack?.buckets ?? {}).map(([bucket, matches]) => (
                <div className="bucket-row" key={bucket}>
                  <strong>{bucket}</strong>
                  <span>{matches.map((match) => match.display_name).join(", ") || "None"}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="panel" aria-labelledby="recent-context-title">
            <h2 id="recent-context-title">Recent context</h2>
            <div className="debug-stack">
              {(pack?.recent_context ?? []).map((observation) => (
                <p key={observation.observation_id}>{observation.content}</p>
              ))}
              {(pack?.recent_context ?? []).length === 0 ? <p className="muted">None</p> : null}
            </div>
          </section>

          <section className="panel" aria-labelledby="score-breakdown-title">
            <h2 id="score-breakdown-title">Score breakdown</h2>
            <pre>{JSON.stringify(scoreBreakdownByName, null, 2)}</pre>
          </section>

          <section className="panel" aria-labelledby="semantic-debug-title">
            <h2 id="semantic-debug-title">Semantic metadata</h2>
            <pre>{JSON.stringify(retrieveResult.debug, null, 2)}</pre>
          </section>

          <section className="panel wide" aria-labelledby="raw-retrieval-title">
            <h2 id="raw-retrieval-title">Raw retrieval result</h2>
            <button type="button" className="secondary" onClick={() => setShowRaw((current) => !current)}>
              {showRaw ? "Hide raw payload" : "Show raw payload"}
            </button>
            {showRaw ? <pre>{JSON.stringify(retrieveResult, null, 2)}</pre> : null}
          </section>
        </div>
      ) : null}
    </section>
  );
}

function MatchedEntitySummary({match}: {match: MatchedEntity}) {
  return (
    <article className="match-summary">
      <div>
        <strong>{match.display_name}</strong>
        <span>{match.entity_type}</span>
      </div>
      <div className="pill-row">
        <span className="pill">{match.confidence_band}</span>
        <span className="pill">{match.surface_bucket}</span>
        <span className="pill">{match.ai_use_policy}</span>
      </div>
      <dl className="definition-list compact">
        <div>
          <dt>Score</dt>
          <dd>{match.score.toFixed(2)}</dd>
        </div>
        <div>
          <dt>Reasons</dt>
          <dd>{match.match_reasons.join(", ") || "None"}</dd>
        </div>
      </dl>
      {match.observations.map((observation) => (
        <p key={observation.observation_id}>{observation.content}</p>
      ))}
    </article>
  );
}

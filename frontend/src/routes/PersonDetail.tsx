import {useEffect, useState} from "react";

import {getAliases, getContextCard, getFacts, getPerson} from "../api/client";
import type {ContextCard, Entity, EntityAlias, EntityFact, Observation} from "../types/entities";

type Props = {
  id: string;
  onNavigate: (path: string) => void;
};

export function PersonDetail({id, onNavigate}: Props) {
  const [person, setPerson] = useState<Entity | null>(null);
  const [aliases, setAliases] = useState<EntityAlias[]>([]);
  const [facts, setFacts] = useState<EntityFact[]>([]);
  const [contextCard, setContextCard] = useState<ContextCard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getPerson(id), getAliases(id), getFacts(id), getContextCard(id)])
      .then(([entity, aliasList, factList, card]) => {
        setPerson(entity);
        setAliases(aliasList.items);
        setFacts(factList.items);
        setContextCard(card);
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  }, [id]);

  if (error) {
    return (
      <section className="page-section">
        <p className="error">{error}</p>
        <button type="button" onClick={() => onNavigate("/people")}>
          Back to people
        </button>
      </section>
    );
  }

  if (!person) {
    return <p className="muted">Loading person...</p>;
  }

  return (
    <section className="page-section" aria-labelledby="person-title">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Person</p>
          <h1 id="person-title">{person.display_name}</h1>
        </div>
        <button type="button" className="secondary" onClick={() => onNavigate("/people")}>
          Back
        </button>
      </div>

      <div className="summary-grid">
        <div>
          <span>Status</span>
          <strong>{person.status}</strong>
        </div>
        <div>
          <span>Sensitivity</span>
          <strong>{person.sensitivity}</strong>
        </div>
        <div>
          <span>Policy</span>
          <strong>{person.ai_use_policy}</strong>
        </div>
        <div>
          <span>System role</span>
          <strong>{person.system_role ?? "None"}</strong>
        </div>
      </div>

      <section className="detail-section">
        <h2>Aliases</h2>
        <div className="pill-row">
          {aliases.map((alias) => (
            <span className="pill" key={alias.id}>
              {alias.alias}
            </span>
          ))}
          {aliases.length === 0 ? <span className="muted">No aliases.</span> : null}
        </div>
      </section>

      <section className="detail-section">
        <h2>Profile Facts</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Content</th>
                <th>Claim</th>
                <th>Confidence</th>
                <th>Policy</th>
              </tr>
            </thead>
            <tbody>
              {facts.map((fact) => (
                <tr key={fact.id}>
                  <td>{fact.fact_type}</td>
                  <td>{fact.content}</td>
                  <td>{fact.claim_type}</td>
                  <td>{fact.confidence}</td>
                  <td>{fact.ai_use_policy}</td>
                </tr>
              ))}
              {facts.length === 0 ? (
                <tr>
                  <td colSpan={5}>No active facts.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="detail-section">
        <h2>Relationships</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Claim</th>
                <th>Confidence</th>
                <th>Policy</th>
              </tr>
            </thead>
            <tbody>
              {(contextCard?.relationship_edges ?? []).map((edge) => (
                <tr key={edge.id}>
                  <td>{edge.relation_type}</td>
                  <td>{edge.claim_text}</td>
                  <td>{edge.confidence}</td>
                  <td>{edge.ai_use_policy}</td>
                </tr>
              ))}
              {(contextCard?.relationship_edges ?? []).length === 0 ? (
                <tr>
                  <td colSpan={4}>No active relationships.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <ObservationSection title="Stable Observations" observations={contextCard?.stable_context ?? []} />
      <ObservationSection title="Recent Observations" observations={contextCard?.recent_context ?? []} />

      <section className="detail-section">
        <h2>Provenance</h2>
        <p className="muted">
          Facts {contextCard?.provenance_summary.fact_count ?? 0} / Edges{" "}
          {contextCard?.provenance_summary.edge_count ?? 0} / Observations{" "}
          {contextCard?.provenance_summary.observation_count ?? 0} / Evidence{" "}
          {contextCard?.provenance_summary.evidence_count ?? 0}
        </p>
        <div className="debug-stack">
          {(contextCard?.provenance_summary.evidence ?? []).map((item) => (
            <div className="bucket-row" key={`${item.record_type}-${item.record_id}`}>
              <strong>{item.record_type}</strong>
              <span>{item.excerpt ?? item.record_id}</span>
            </div>
          ))}
          {(contextCard?.provenance_summary.evidence ?? []).length === 0 ? (
            <p className="muted">No evidence linked.</p>
          ) : null}
        </div>
      </section>
    </section>
  );
}

function ObservationSection({title, observations}: {title: string; observations: Observation[]}) {
  return (
    <section className="detail-section">
      <h2>{title}</h2>
      <div className="debug-stack">
        {observations.map((observation) => (
          <article className="match-summary" key={observation.id}>
            <div>
              <strong>{observation.observation_type}</strong>
              <span>{observation.embedding_status}</span>
            </div>
            <p>{observation.content}</p>
            <div className="pill-row">
              <span className="pill">{observation.claim_type}</span>
              <span className="pill">{observation.ai_use_policy}</span>
              <span className="pill">{observation.sensitivity}</span>
            </div>
          </article>
        ))}
        {observations.length === 0 ? <p className="muted">No observations.</p> : null}
      </div>
    </section>
  );
}

import {useEffect, useState} from "react";

import {editAcceptCandidate, formatApiError, listCandidates, runCandidateAction} from "../api/client";
import type {Candidate, CandidateFilters} from "../types/candidates";

const candidateTypes = [
  "all",
  "new_entity",
  "alias",
  "profile_field",
  "relationship_edge",
  "observation",
  "merge",
  "conflict",
  "supersede",
];

const statuses = ["pending", "all", "accepted", "rejected", "archived", "needs_clarification"];
const sensitivities = ["all", "low", "medium", "high"];

export function Candidates() {
  const [filters, setFilters] = useState<CandidateFilters>({
    status: "pending",
    candidate_type: "all",
    sensitivity: "all",
  });
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [editedPayload, setEditedPayload] = useState("");
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    listCandidates(filters)
      .then((result) => {
        setCandidates(result.items);
        setTotal(result.total);
        setSelected(result.items[0] ?? null);
        setEditedPayload(result.items[0] ? JSON.stringify(result.items[0].payload, null, 2) : "");
        setError(null);
      })
      .catch((err: unknown) => setError(formatApiError(err)))
      .finally(() => setLoading(false));
  }, [filters]);

  function updateFilter(key: keyof CandidateFilters, value: string) {
    setFilters((current) => ({...current, [key]: value}));
  }

  function selectCandidate(candidate: Candidate) {
    setSelected(candidate);
    setEditedPayload(JSON.stringify(candidate.payload, null, 2));
  }

  function mergeCandidate(candidate: Candidate) {
    setSelected(candidate);
    setCandidates((current) => current.map((item) => (item.id === candidate.id ? candidate : item)));
    setEditedPayload(JSON.stringify(candidate.payload, null, 2));
    setError(null);
  }

  function action(endpoint: string) {
    if (!selected) {
      return;
    }
    runCandidateAction(selected.id, endpoint)
      .then(mergeCandidate)
      .catch((err: unknown) => setError(formatApiError(err)));
  }

  function editAccept() {
    if (!selected) {
      return;
    }
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(editedPayload);
    } catch {
      setError("Invalid edited payload JSON.");
      return;
    }
    if (!payload || Array.isArray(payload) || typeof payload !== "object") {
      setError("Invalid edited payload JSON.");
      return;
    }
    editAcceptCandidate(selected.id, payload)
      .then(mergeCandidate)
      .catch((err: unknown) => setError(formatApiError(err)));
  }

  return (
    <section className="page-section" aria-labelledby="candidates-title">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Review</p>
          <h1 id="candidates-title">Candidates</h1>
        </div>
        <span className="status-chip">{total} total</span>
      </div>

      <div className="filter-grid">
        <label>
          <span>Status</span>
          <select value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}>
            {statuses.map((status) => (
              <option value={status} key={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Candidate type</span>
          <select
            value={filters.candidate_type}
            onChange={(event) => updateFilter("candidate_type", event.target.value)}
          >
            {candidateTypes.map((candidateType) => (
              <option value={candidateType} key={candidateType}>
                {candidateType}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Sensitivity</span>
          <select
            value={filters.sensitivity}
            onChange={(event) => updateFilter("sensitivity", event.target.value)}
          >
            {sensitivities.map((sensitivity) => (
              <option value={sensitivity} key={sensitivity}>
                {sensitivity}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {loading ? <p className="muted">Loading candidates...</p> : null}

      <div className="review-grid">
        <div className="table-wrap">
          <table>
            <caption>{total} candidates</caption>
            <thead>
              <tr>
                <th>ID</th>
                <th>Type</th>
                <th>Status</th>
                <th>Sensitivity</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((candidate) => (
                <tr key={candidate.id} onClick={() => selectCandidate(candidate)}>
                  <td>{candidate.id}</td>
                  <td>{candidate.candidate_type}</td>
                  <td>{candidate.status}</td>
                  <td>{candidate.sensitivity}</td>
                </tr>
              ))}
              {candidates.length === 0 && !loading ? (
                <tr>
                  <td colSpan={4}>No candidates found.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <section className="panel" aria-labelledby="candidate-detail-title">
          <h2 id="candidate-detail-title">Candidate detail</h2>
          {selected ? (
            <div className="debug-stack">
              <dl className="definition-list compact">
                <div>
                  <dt>ID</dt>
                  <dd>{selected.id}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>{selected.status}</dd>
                </div>
                <div>
                  <dt>Canonical</dt>
                  <dd>{selected.canonical_record_ref ?? "None"}</dd>
                </div>
              </dl>
              <div className="action-row">
                <button type="button" onClick={() => action("accept")}>
                  Accept
                </button>
                <button type="button" className="secondary" onClick={() => action("reject")}>
                  Reject
                </button>
                <button type="button" className="secondary" onClick={() => action("archive")}>
                  Archive
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => action("needs-clarification")}
                >
                  Needs clarification
                </button>
              </div>
              <label className="json-editor">
                <span>Edited payload JSON</span>
                <textarea value={editedPayload} onChange={(event) => setEditedPayload(event.target.value)} />
              </label>
              <button type="button" onClick={editAccept}>
                Edit accept
              </button>
              <section>
                <h3>Evidence</h3>
                <div className="debug-stack">
                  {selected.evidence.map((evidence) => (
                    <p key={evidence.id}>{evidence.excerpt ?? evidence.episode_id}</p>
                  ))}
                  {selected.evidence.length === 0 ? <p className="muted">No evidence.</p> : null}
                </div>
              </section>
              <section>
                <h3>Typed payload</h3>
                <pre>{JSON.stringify(selected.payload, null, 2)}</pre>
              </section>
            </div>
          ) : (
            <p className="muted">Select a candidate.</p>
          )}
        </section>
      </div>
    </section>
  );
}

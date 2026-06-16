import {useEffect, useState} from "react";

import {editAcceptCandidate, formatApiError, getOntology, listCandidates, listPeople, runCandidateAction} from "../api/client";
import {includeAllOption, registryOptions, type SelectOption} from "../ontologyOptions";
import type {Candidate, CandidateFilters} from "../types/candidates";
import type {Entity} from "../types/entities";

const statuses = ["pending", "all", "accepted", "rejected", "archived", "needs_clarification"];

function summarizeCandidate(candidate: Candidate) {
  const payload = candidate.payload;
  const content = payload.content;
  const displayName = payload.display_name;
  const alias = payload.alias;
  const relationType = payload.relation_type;
  if (typeof content === "string" && content.trim()) {
    return content.trim();
  }
  if (typeof displayName === "string" && displayName.trim()) {
    return displayName.trim();
  }
  if (typeof alias === "string" && alias.trim()) {
    return alias.trim();
  }
  if (typeof relationType === "string" && relationType.trim()) {
    return `Relationship: ${relationType}`;
  }
  return candidate.suggested_action ?? candidate.candidate_type;
}

function targetSummary(candidate: Candidate, people: Entity[]) {
  if (!candidate.target_entity_id) {
    return "No target";
  }
  return people.find((person) => person.id === candidate.target_entity_id)?.display_name ?? "Linked target";
}

function canonicalSummary(candidate: Candidate) {
  if (!candidate.canonical_record_ref) {
    return "None";
  }
  const [recordType] = candidate.canonical_record_ref.split(":");
  return `${recordType || "Canonical"} record`;
}

function formatTimestamp(value: string | null) {
  if (!value) {
    return "Unknown";
  }
  return new Date(value).toLocaleString();
}

export function Candidates() {
  const [filters, setFilters] = useState<CandidateFilters>({
    status: "pending",
    candidate_type: "all",
    sensitivity: "all",
  });
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [people, setPeople] = useState<Entity[]>([]);
  const [candidateTypeOptions, setCandidateTypeOptions] = useState<SelectOption[]>([]);
  const [sensitivityOptions, setSensitivityOptions] = useState<SelectOption[]>([]);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [editedPayload, setEditedPayload] = useState("");
  const [showRawPayload, setShowRawPayload] = useState(false);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      listCandidates(filters),
      listPeople("").catch(() => ({items: [] as Entity[]})),
      getOntology().catch(() => null),
    ])
      .then(([result, peopleResult, ontology]) => {
        setCandidates(result.items);
        setPeople(peopleResult.items);
        if (ontology) {
          setCandidateTypeOptions(registryOptions(ontology.policies.candidate_types));
          setSensitivityOptions(registryOptions(ontology.policies.sensitivity_levels));
        }
        setTotal(result.total);
        setSelected(result.items[0] ?? null);
        setEditedPayload(result.items[0] ? JSON.stringify(result.items[0].payload, null, 2) : "");
        setShowRawPayload(false);
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
    setShowRawPayload(false);
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
            {includeAllOption(candidateTypeOptions).map((candidateType) => (
              <option value={candidateType.value} key={candidateType.value}>
                {candidateType.label}
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
            {includeAllOption(sensitivityOptions).map((sensitivity) => (
              <option value={sensitivity.value} key={sensitivity.value}>
                {sensitivity.label}
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
                <th>Summary</th>
                <th>Type</th>
                <th>Status</th>
                <th>Confidence</th>
                <th>Target</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((candidate) => (
                <tr key={candidate.id} onClick={() => selectCandidate(candidate)}>
                  <td>{summarizeCandidate(candidate)}</td>
                  <td>{candidate.candidate_type}</td>
                  <td>{candidate.status}</td>
                  <td>{candidate.confidence.toFixed(2)}</td>
                  <td>{targetSummary(candidate, people)}</td>
                  <td>{formatTimestamp(candidate.created_at)}</td>
                </tr>
              ))}
              {candidates.length === 0 && !loading ? (
                <tr>
                  <td colSpan={6}>No candidates found.</td>
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
                  <dt>Summary</dt>
                  <dd>{summarizeCandidate(selected)}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>{selected.status}</dd>
                </div>
                <div>
                  <dt>Type</dt>
                  <dd>{selected.candidate_type}</dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd>{selected.confidence.toFixed(2)}</dd>
                </div>
                <div>
                  <dt>Target</dt>
                  <dd>{targetSummary(selected, people)}</dd>
                </div>
                <div>
                  <dt>Created</dt>
                  <dd>{formatTimestamp(selected.created_at)}</dd>
                </div>
                <div>
                  <dt>Canonical</dt>
                  <dd>{canonicalSummary(selected)}</dd>
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
              <button
                type="button"
                className="secondary"
                onClick={() => setShowRawPayload((current) => !current)}
              >
                {showRawPayload ? "Hide raw/edit payload" : "Show raw/edit payload"}
              </button>
              {showRawPayload ? (
                <section>
                  <h3>Raw/edit payload</h3>
                  <label className="json-editor">
                    <span>Edited payload JSON</span>
                    <textarea
                      value={editedPayload}
                      onChange={(event) => setEditedPayload(event.target.value)}
                    />
                  </label>
                  <button type="button" onClick={editAccept}>
                    Edit accept
                  </button>
                  <pre>{JSON.stringify(selected.payload, null, 2)}</pre>
                </section>
              ) : null}
              <section>
                <h3>Evidence</h3>
                <div className="debug-stack">
                  {selected.evidence.map((evidence) => (
                    <p key={evidence.id}>{evidence.excerpt ?? "Evidence record"}</p>
                  ))}
                  {selected.evidence.length === 0 ? <p className="muted">No evidence.</p> : null}
                </div>
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

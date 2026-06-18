import {useEffect, useState} from "react";

import {editAcceptCandidate, formatApiError, getOntology, listCandidates, listPeople, runCandidateAction} from "../api/client";
import {FieldHelp} from "../components/FieldHelp";
import {includeAllOption, registryOptions, type SelectOption} from "../ontologyOptions";
import type {Candidate, CandidateFilters} from "../types/candidates";
import type {Entity} from "../types/entities";

const statuses = [
  "pending",
  "all",
  "accepted",
  "edited_accepted",
  "rejected",
  "archived",
  "needs_clarification",
  "superseded",
];
const terminalStatuses = new Set(["accepted", "edited_accepted", "rejected", "archived", "superseded"]);
const reviewOnlyTypes = new Set(["merge", "conflict", "supersede"]);

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

function rawRefSummary(value: string | null) {
  return value && value.trim() ? value : "None";
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
  const [supersedesCandidateId, setSupersedesCandidateId] = useState("");
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
    setSupersedesCandidateId("");
  }

  function mergeCandidate(candidate: Candidate) {
    setSelected(candidate);
    setCandidates((current) => current.map((item) => (item.id === candidate.id ? candidate : item)));
    setEditedPayload(JSON.stringify(candidate.payload, null, 2));
    setSupersedesCandidateId("");
    setError(null);
  }

  function action(endpoint: string, payload: Record<string, unknown> = {}) {
    if (!selected) {
      return;
    }
    runCandidateAction(selected.id, endpoint, payload)
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

  function supersede() {
    if (!supersedesCandidateId.trim()) {
      setError("Superseding candidate ID is required.");
      return;
    }
    action("supersede", {supersedes_candidate_id: supersedesCandidateId.trim()});
  }

  const selectedIsResolved = selected ? terminalStatuses.has(selected.status) : true;
  const selectedIsReviewOnly = selected ? reviewOnlyTypes.has(selected.candidate_type) : false;
  const canCanonicalize = Boolean(selected && !selectedIsResolved && !selectedIsReviewOnly);
  const canResolve = Boolean(selected && !selectedIsResolved);

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
          <FieldHelp label="Status" help="검토 전인지, 승인/거절/보류됐는지" />
          <select value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}>
            {statuses.map((status) => (
              <option value={status} key={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <label>
          <FieldHelp label="Candidate type" help="AI가 제안한 정보의 형태" />
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
          <FieldHelp label="Sensitivity" help="정보가 얼마나 조심스러운지로 좁혀 보기" />
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
                  <dt>Created by</dt>
                  <dd>{selected.created_by}</dd>
                </div>
                <div>
                  <dt>Suggested action</dt>
                  <dd>{selected.suggested_action ?? "None"}</dd>
                </div>
                <div>
                  <dt>Target</dt>
                  <dd>{targetSummary(selected, people)}</dd>
                </div>
                <div>
                  <dt>Created at</dt>
                  <dd>{formatTimestamp(selected.created_at)}</dd>
                </div>
                <div>
                  <dt>Canonical record</dt>
                  <dd>{canonicalSummary(selected)}</dd>
                </div>
                <div>
                  <dt>Canonical ref</dt>
                  <dd>{rawRefSummary(selected.canonical_record_ref)}</dd>
                </div>
                <div>
                  <dt>Superseded candidate</dt>
                  <dd>{rawRefSummary(selected.supersedes_candidate_id)}</dd>
                </div>
                <div>
                  <dt>Superseded record</dt>
                  <dd>{rawRefSummary(selected.supersedes_record_ref)}</dd>
                </div>
              </dl>
              <div className="action-row">
                <button type="button" disabled={!canCanonicalize} onClick={() => action("accept")}>
                  Accept
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={!canResolve}
                  onClick={() => action("reject")}
                >
                  Reject
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={!canResolve}
                  onClick={() => action("archive")}
                >
                  Archive
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={!canResolve}
                  onClick={() => action("needs-clarification")}
                >
                  Needs clarification
                </button>
              </div>
              {canResolve ? (
                <div className="inline-form">
                  <label>
                    <FieldHelp label="Superseding candidate ID" help="이 후보가 더 새 후보로 바뀌었을 때 입력" />
                    <input
                      value={supersedesCandidateId}
                      onChange={(event) => setSupersedesCandidateId(event.target.value)}
                    />
                  </label>
                  <button type="button" className="secondary" onClick={supersede}>
                    Supersede
                  </button>
                </div>
              ) : null}
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
                    <FieldHelp label="Edited payload JSON" help="원본 제안을 고쳐 확정 기록으로 만들 때만 사용" />
                    <textarea
                      value={editedPayload}
                      onChange={(event) => setEditedPayload(event.target.value)}
                    />
                  </label>
                  <button type="button" disabled={!canCanonicalize} onClick={editAccept}>
                    {canCanonicalize ? "Edit accept" : "Edit accept unavailable"}
                  </button>
                  <pre>{JSON.stringify(selected.payload, null, 2)}</pre>
                </section>
              ) : null}
              <section>
                <h3>Evidence</h3>
                <div className="debug-stack">
                  {selected.evidence.map((evidence) => (
                    <dl className="definition-list compact" key={evidence.id}>
                      <div>
                        <dt>Excerpt</dt>
                        <dd>{evidence.excerpt ?? "Evidence record"}</dd>
                      </div>
                      <div>
                        <dt>Confidence</dt>
                        <dd>{evidence.confidence ?? "Unknown"}</dd>
                      </div>
                      <div>
                        <dt>Episode</dt>
                        <dd>{evidence.episode_id}</dd>
                      </div>
                      <div>
                        <dt>Source type</dt>
                        <dd>{evidence.source_type ?? "Unknown"}</dd>
                      </div>
                      <div>
                        <dt>Source ref</dt>
                        <dd>{evidence.source_ref ?? "None"}</dd>
                      </div>
                      <div>
                        <dt>Source description</dt>
                        <dd>{evidence.source_description ?? "None"}</dd>
                      </div>
                      <div>
                        <dt>Body hash</dt>
                        <dd>{evidence.body_hash ?? "None"}</dd>
                      </div>
                      <div>
                        <dt>Actor</dt>
                        <dd>{evidence.actor ?? "Unknown"}</dd>
                      </div>
                    </dl>
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

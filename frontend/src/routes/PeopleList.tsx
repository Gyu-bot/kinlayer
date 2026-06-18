import {useEffect, useState} from "react";

import {
  createCandidate,
  formatApiError,
  getAliases,
  getContextCard,
  getOntology,
  listPeople,
} from "../api/client";
import {FieldHelp, helpCopy} from "../components/FieldHelp";
import {includeAllOption, registryOptions, type SelectOption} from "../ontologyOptions";
import type {Entity, EntityAlias} from "../types/entities";

type Props = {
  onNavigate: (path: string) => void;
};

const mergeFields = ["aliases", "profile_facts", "edges", "observations"];

async function loadPeopleContext(people: Entity[]) {
  const aliasesByPerson: Record<string, EntityAlias[]> = {};
  const summariesByPerson: Record<string, string> = {};
  const batchSize = 6;

  for (let index = 0; index < people.length; index += batchSize) {
    await Promise.all(
      people.slice(index, index + batchSize).map(async (person) => {
        const [aliases, card] = await Promise.allSettled([
          getAliases(person.id),
          getContextCard(person.id),
        ]);

        aliasesByPerson[person.id] =
          aliases.status === "fulfilled" ? aliases.value.items : [];
        summariesByPerson[person.id] =
          card.status === "fulfilled"
            ? `${card.value.relationship_edges.length} relationships / ${card.value.recent_context.length} recent`
            : "Context unavailable";
      }),
    );
  }

  return {aliasesByPerson, summariesByPerson};
}

function personName(people: Entity[], id: string) {
  return people.find((person) => person.id === id)?.display_name ?? "selected person";
}

function mergeCandidateSensitivity(source: Entity | undefined, target: Entity | undefined) {
  const rank: Record<string, number> = {low: 0, medium: 1, high: 2};
  const values = [source?.sensitivity, target?.sensitivity].filter(
    (value): value is string => Boolean(value),
  );
  return values.reduce(
    (highest, value) => (rank[value] > rank[highest] ? value : highest),
    "medium",
  );
}

export function PeopleList({onNavigate}: Props) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sensitivityFilter, setSensitivityFilter] = useState("all");
  const [people, setPeople] = useState<Entity[]>([]);
  const [sensitivityOptions, setSensitivityOptions] = useState<SelectOption[]>([]);
  const [aliasesByPerson, setAliasesByPerson] = useState<Record<string, EntityAlias[]>>({});
  const [summariesByPerson, setSummariesByPerson] = useState<Record<string, string>>({});
  const [mergeSourceId, setMergeSourceId] = useState("");
  const [mergeTargetId, setMergeTargetId] = useState("");
  const [mergeStatus, setMergeStatus] = useState<string | null>(null);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [creatingMerge, setCreatingMerge] = useState(false);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getOntology()
      .then((ontology) => setSensitivityOptions(registryOptions(ontology.policies.sensitivity_levels)))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      setLoading(true);
      listPeople(query, {status: statusFilter, sensitivity: sensitivityFilter})
        .then(async (result) => {
          if (!active) {
            return;
          }
          setPeople(result.items);
          setTotal(result.total);
          setError(null);
          const context = await loadPeopleContext(result.items);
          if (!active) {
            return;
          }
          setAliasesByPerson(context.aliasesByPerson);
          setSummariesByPerson(context.summariesByPerson);
        })
        .catch((err: Error) => {
          if (active) {
            setError(err.message);
          }
        })
        .finally(() => {
          if (active) {
            setLoading(false);
          }
        });
    }, 160);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [query, sensitivityFilter, statusFilter]);

  const sourcePerson = people.find((person) => person.id === mergeSourceId);
  const targetPerson = people.find((person) => person.id === mergeTargetId);
  const canCreateMergeCandidate =
    Boolean(sourcePerson && targetPerson) && mergeSourceId !== mergeTargetId && !creatingMerge;

  function createMergeCandidate() {
    if (!sourcePerson || !targetPerson || mergeSourceId === mergeTargetId) {
      setMergeStatus("Choose two different people before creating a merge candidate.");
      return;
    }
    setCreatingMerge(true);
    setMergeStatus(null);
    createCandidate({
      candidate_type: "merge",
      target_entity_id: targetPerson.id,
      payload: {
        source_entity_id: sourcePerson.id,
        target_entity_id: targetPerson.id,
        reason: `Manual Web merge request: merge ${sourcePerson.display_name} into ${targetPerson.display_name}.`,
        fields_to_merge: mergeFields,
        merge_plan: {
          aliases: "copy_non_conflicting",
          profile_facts: "copy_non_conflicting",
          edges: "repoint_without_self_or_duplicate_edges",
          observations: "repoint_related_entities",
        },
        field_conflict_policy: {
          display_name: "keep_target",
          canonical_name: "keep_target",
          sensitivity: "use_more_restrictive",
          ai_use_policy: "use_more_restrictive",
        },
        risk_notes: ["Manual Web merge request requires reviewer confirmation before acceptance."],
      },
      confidence: 0.5,
      sensitivity: mergeCandidateSensitivity(sourcePerson, targetPerson),
      suggested_action: "review",
      created_by: "user",
    })
      .then(() => setMergeStatus("Merge candidate created for review."))
      .catch((err: unknown) => setMergeStatus(formatApiError(err)))
      .finally(() => setCreatingMerge(false));
  }

  return (
    <section className="page-section" aria-labelledby="people-title">
      <div className="toolbar">
        <div>
          <p className="eyebrow">People</p>
          <h1 id="people-title">Relationship Context</h1>
        </div>
        <button type="button" onClick={() => onNavigate("/people/new")}>
          New person
        </button>
      </div>

      <label className="search-field">
        <span>Search by name or alias</span>
        <input value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      <div className="filter-grid">
        <label>
          <FieldHelp label="Status filter" help="현재 보이는 사람 기록의 상태로 좁혀 보기" />
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">all</option>
            <option value="active">active</option>
            <option value="deprecated">deprecated</option>
            <option value="merged">merged</option>
            <option value="deleted">deleted</option>
          </select>
        </label>
        <label>
          <FieldHelp label="Sensitivity filter" help="정보가 얼마나 조심스러운지로 좁혀 보기" />
          <select
            value={sensitivityFilter}
            onChange={(event) => setSensitivityFilter(event.target.value)}
          >
            {includeAllOption(sensitivityOptions).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {loading ? <p className="muted">Loading people...</p> : null}

      <section className="merge-accordion" aria-labelledby="manual-merge-title">
        <button
          type="button"
          className="accordion-toggle"
          aria-expanded={mergeOpen}
          aria-controls="manual-merge-body"
          onClick={() => setMergeOpen((current) => !current)}
        >
          <div>
            <span className="eyebrow">Review</span>
            <span className="accordion-title" id="manual-merge-title">Merge people</span>
          </div>
          <span className="status-chip">{personName(people, mergeSourceId)} {"->"} {personName(people, mergeTargetId)}</span>
        </button>
        {mergeOpen ? (
          <div className="accordion-body" id="manual-merge-body">
            <div className="filter-grid">
              <label>
                <FieldHelp label="Source person" help="병합 후 흡수되어 사라질 사람 기록" />
                <select
                  aria-label="Source person"
                  value={mergeSourceId}
                  onChange={(event) => setMergeSourceId(event.target.value)}
                >
                  <option value="">Choose source</option>
                  {people.map((person) => (
                    <option key={person.id} value={person.id}>
                      {person.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <FieldHelp label="Target person" help="병합 후 남길 사람 기록" />
                <select
                  aria-label="Target person"
                  value={mergeTargetId}
                  onChange={(event) => setMergeTargetId(event.target.value)}
                >
                  <option value="">Choose target</option>
                  {people.map((person) => (
                    <option key={person.id} value={person.id} disabled={person.id === mergeSourceId}>
                      {person.display_name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="action-row">
              <button type="button" disabled={!canCreateMergeCandidate} onClick={createMergeCandidate}>
                {creatingMerge ? "Creating..." : "Create merge candidate"}
              </button>
              <button type="button" className="secondary" onClick={() => onNavigate("/candidates")}>
                Review in Candidates
              </button>
            </div>
            {mergeStatus ? (
              <p className={mergeStatus.includes(":") ? "error" : "muted"}>{mergeStatus}</p>
            ) : null}
          </div>
        ) : null}
      </section>

      <div className="table-wrap">
        <table>
          <caption>{total} people</caption>
          <thead>
            <tr>
              <th>Name</th>
              <th>{helpCopy.status.label}</th>
              <th>{helpCopy.sensitivity.label}</th>
              <th>{helpCopy.policy.label}</th>
              <th>Relationships</th>
              <th>Last referenced</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {people.map((person) => (
              <tr
                className="clickable-row"
                key={person.id}
                onClick={() => onNavigate(`/people/${person.id}`)}
              >
                <td>
                  <strong>{person.display_name}</strong>
                  <span>
                    {(aliasesByPerson[person.id] ?? []).map((alias) => alias.alias).join(", ") ||
                      person.canonical_name}
                  </span>
                </td>
                <td>{person.status}</td>
                <td>{person.sensitivity}</td>
                <td>{person.ai_use_policy}</td>
                <td>{summariesByPerson[person.id] ?? "Loading"}</td>
                <td>{person.last_referenced_at ?? "None"}</td>
                <td>
                  <button
                    type="button"
                    className="secondary"
                    onClick={(event) => {
                      event.stopPropagation();
                      onNavigate(`/people/${person.id}`);
                    }}
                  >
                    Open {person.display_name}
                  </button>
                </td>
              </tr>
            ))}
            {!loading && people.length === 0 ? (
              <tr>
                <td colSpan={7}>No people found.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

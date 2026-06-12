import {FormEvent, useCallback, useEffect, useState} from "react";

import {
  createAlias,
  createEdge,
  createFact,
  deleteAlias,
  deleteEdge,
  deleteFact,
  deleteObservation,
  formatApiError,
  getAliases,
  getContextCard,
  getFacts,
  getPerson,
  updateAlias,
  updateEdge,
  updateFact,
  updatePerson,
} from "../api/client";
import type {ContextCard, Entity, EntityAlias, EntityEdge, EntityFact, Observation} from "../types/entities";

type Props = {
  id: string;
  onNavigate: (path: string) => void;
};

const STRUCTURED_FACT_TYPES = [
  "legal_name",
  "birth_date",
  "phone",
  "email",
  "address",
  "organization",
  "role",
  "memo",
];

const SENSITIVITY_OPTIONS = ["low", "medium", "high"];
const POLICY_OPTIONS = ["freely_use", "cautious_use", "ask_before_use", "never_surface"];

type FactDraft = {
  fact_type: string;
  content: string;
  claim_type: string;
  sensitivity: string;
  ai_use_policy: string;
};

type EdgeDraft = {
  relation_type: string;
  claim_text: string;
  sensitivity: string;
  ai_use_policy: string;
};

export function PersonDetail({id, onNavigate}: Props) {
  const [person, setPerson] = useState<Entity | null>(null);
  const [aliases, setAliases] = useState<EntityAlias[]>([]);
  const [facts, setFacts] = useState<EntityFact[]>([]);
  const [contextCard, setContextCard] = useState<ContextCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [profileDraft, setProfileDraft] = useState({
    display_name: "",
    sensitivity: "medium",
    ai_use_policy: "cautious_use",
    short_note: "",
  });
  const [aliasDrafts, setAliasDrafts] = useState<Record<string, string>>({});
  const [newAlias, setNewAlias] = useState("");
  const [factDrafts, setFactDrafts] = useState<Record<string, FactDraft>>({});
  const [newFact, setNewFact] = useState<FactDraft>({
    fact_type: "email",
    content: "",
    claim_type: "fact",
    sensitivity: "medium",
    ai_use_policy: "cautious_use",
  });
  const [edgeDrafts, setEdgeDrafts] = useState<Record<string, EdgeDraft>>({});
  const [newEdge, setNewEdge] = useState({
    to_entity_id: "",
    relation_type: "friend",
    claim_text: "",
    sensitivity: "medium",
    ai_use_policy: "cautious_use",
  });

  const applyLoadedState = useCallback(
    ([entity, aliasList, factList, card]: [
      Entity,
      {items: EntityAlias[]},
      {items: EntityFact[]},
      ContextCard,
    ]) => {
      setPerson(entity);
      setAliases(aliasList.items);
      setFacts(factList.items);
      setContextCard(card);
      setProfileDraft({
        display_name: entity.display_name,
        sensitivity: entity.sensitivity,
        ai_use_policy: entity.ai_use_policy,
        short_note: String(entity.properties.short_note ?? ""),
      });
      setAliasDrafts(
        Object.fromEntries(aliasList.items.map((alias) => [alias.id, alias.alias])),
      );
      setFactDrafts(
        Object.fromEntries(
          factList.items.map((fact) => [
            fact.id,
            {
              fact_type: fact.fact_type,
              content: fact.content,
              claim_type: fact.claim_type,
              sensitivity: fact.sensitivity,
              ai_use_policy: fact.ai_use_policy,
            },
          ]),
        ),
      );
      setEdgeDrafts(
        Object.fromEntries(
          (card.relationship_edges ?? []).map((edge) => [
            edge.id,
            {
              relation_type: edge.relation_type,
              claim_text: edge.claim_text,
              sensitivity: edge.sensitivity,
              ai_use_policy: edge.ai_use_policy,
            },
          ]),
        ),
      );
      setError(null);
    },
    [],
  );

  const refresh = useCallback(async () => {
    const loaded = await Promise.all([getPerson(id), getAliases(id), getFacts(id), getContextCard(id)]);
    applyLoadedState(loaded);
  }, [applyLoadedState, id]);

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, [refresh]);

  async function runAction(action: () => Promise<unknown>) {
    try {
      setActionError(null);
      await action();
      await refresh();
    } catch (err) {
      setActionError(formatApiError(err));
    }
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    await runAction(() =>
      updatePerson(id, {
        display_name: profileDraft.display_name,
        sensitivity: profileDraft.sensitivity,
        ai_use_policy: profileDraft.ai_use_policy,
        properties: {...(person?.properties ?? {}), short_note: profileDraft.short_note},
      }),
    );
  }

  async function addAlias(event: FormEvent) {
    event.preventDefault();
    if (!newAlias.trim()) {
      return;
    }
    await runAction(() => createAlias(id, {alias: newAlias.trim(), created_by: "user"}));
    setNewAlias("");
  }

  async function addFact(event: FormEvent) {
    event.preventDefault();
    if (!newFact.content.trim()) {
      return;
    }
    await runAction(() =>
      createFact({
        entity_id: id,
        ...newFact,
        content: newFact.content.trim(),
        value: {field_path: `profile.${newFact.fact_type}`, value: newFact.content.trim()},
        confidence: 1,
        created_by: "user",
      }),
    );
    setNewFact({...newFact, content: ""});
  }

  async function addRelationship(event: FormEvent) {
    event.preventDefault();
    if (!newEdge.to_entity_id.trim() || !newEdge.claim_text.trim()) {
      return;
    }
    await runAction(() =>
      createEdge({
        from_entity_id: id,
        to_entity_id: newEdge.to_entity_id.trim(),
        relation_type: newEdge.relation_type,
        claim_text: newEdge.claim_text.trim(),
        claim_type: "fact",
        directed: true,
        confidence: 1,
        sensitivity: newEdge.sensitivity,
        ai_use_policy: newEdge.ai_use_policy,
        created_by: "user",
      }),
    );
    setNewEdge({...newEdge, to_entity_id: "", claim_text: ""});
  }

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

  const relationshipEdges = contextCard?.relationship_edges ?? [];
  const structuredFacts = facts.filter((fact) => STRUCTURED_FACT_TYPES.includes(fact.fact_type));
  const generalFacts = facts.filter((fact) => !STRUCTURED_FACT_TYPES.includes(fact.fact_type));

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

      {actionError ? <p className="error">{actionError}</p> : null}

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
        <h2>Profile</h2>
        <form className="edit-grid" onSubmit={saveProfile}>
          <label>
            Display name
            <input
              value={profileDraft.display_name}
              onChange={(event) =>
                setProfileDraft({...profileDraft, display_name: event.target.value})
              }
            />
          </label>
          <label>
            Sensitivity
            <select
              value={profileDraft.sensitivity}
              onChange={(event) =>
                setProfileDraft({...profileDraft, sensitivity: event.target.value})
              }
            >
              {SENSITIVITY_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label>
            AI use policy
            <select
              value={profileDraft.ai_use_policy}
              onChange={(event) =>
                setProfileDraft({...profileDraft, ai_use_policy: event.target.value})
              }
            >
              {POLICY_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label className="wide">
            Profile note
            <textarea
              value={profileDraft.short_note}
              onChange={(event) =>
                setProfileDraft({...profileDraft, short_note: event.target.value})
              }
            />
          </label>
          <button type="submit">Save profile</button>
        </form>
      </section>

      <section className="detail-section">
        <h2>Aliases</h2>
        <form className="inline-form" onSubmit={addAlias}>
          <label>
            New alias
            <input value={newAlias} onChange={(event) => setNewAlias(event.target.value)} />
          </label>
          <button type="submit">Add alias</button>
        </form>
        <div className="edit-stack">
          {aliases.map((alias) => (
            <div className="edit-row" key={alias.id}>
              <label>
                Alias {alias.id}
                <input
                  value={aliasDrafts[alias.id] ?? alias.alias}
                  onChange={(event) =>
                    setAliasDrafts({...aliasDrafts, [alias.id]: event.target.value})
                  }
                />
              </label>
              <button
                type="button"
                onClick={() =>
                  runAction(() =>
                    updateAlias(alias.id, {alias: aliasDrafts[alias.id] ?? alias.alias}),
                  )
                }
              >
                Update alias {alias.id}
              </button>
              <button type="button" className="secondary" onClick={() => runAction(() => deleteAlias(alias.id))}>
                Delete alias {alias.id}
              </button>
            </div>
          ))}
          {aliases.length === 0 ? <span className="muted">No aliases.</span> : null}
        </div>
      </section>

      <section className="detail-section">
        <h2>Structured Profile Facts</h2>
        <FactCreateForm newFact={newFact} setNewFact={setNewFact} onSubmit={addFact} />
        <FactTable
          facts={structuredFacts}
          factDrafts={factDrafts}
          setFactDrafts={setFactDrafts}
          runAction={runAction}
        />
      </section>

      <section className="detail-section">
        <h2>General Profile Facts</h2>
        <FactTable
          facts={generalFacts}
          factDrafts={factDrafts}
          setFactDrafts={setFactDrafts}
          runAction={runAction}
        />
      </section>

      <section className="detail-section">
        <h2>Relationships</h2>
        <form className="edit-grid" onSubmit={addRelationship}>
          <label>
            Related entity ID
            <input
              value={newEdge.to_entity_id}
              onChange={(event) => setNewEdge({...newEdge, to_entity_id: event.target.value})}
            />
          </label>
          <label>
            Relationship type
            <input
              value={newEdge.relation_type}
              onChange={(event) => setNewEdge({...newEdge, relation_type: event.target.value})}
            />
          </label>
          <label className="wide">
            Relationship note
            <input
              value={newEdge.claim_text}
              onChange={(event) => setNewEdge({...newEdge, claim_text: event.target.value})}
            />
          </label>
          <button type="submit">Add relationship</button>
        </form>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Claim</th>
                <th>Policy</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {relationshipEdges.map((edge) => (
                <RelationshipRow
                  edge={edge}
                  draft={edgeDrafts[edge.id]}
                  key={edge.id}
                  setDraft={(draft) => setEdgeDrafts({...edgeDrafts, [edge.id]: draft})}
                  runAction={runAction}
                />
              ))}
              {relationshipEdges.length === 0 ? (
                <tr>
                  <td colSpan={4}>No active relationships.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <ObservationSection
        title="Stable Observations"
        observations={contextCard?.stable_context ?? []}
        onDelete={(observationId) => runAction(() => deleteObservation(observationId))}
      />
      <ObservationSection
        title="Recent Observations"
        observations={contextCard?.recent_context ?? []}
        onDelete={(observationId) => runAction(() => deleteObservation(observationId))}
      />

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

function FactCreateForm({
  newFact,
  setNewFact,
  onSubmit,
}: {
  newFact: FactDraft;
  setNewFact: (fact: FactDraft) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <form className="edit-grid" onSubmit={onSubmit}>
      <label>
        New structured fact type
        <input
          list="structured-fact-types"
          value={newFact.fact_type}
          onChange={(event) => setNewFact({...newFact, fact_type: event.target.value})}
        />
      </label>
      <datalist id="structured-fact-types">
        {STRUCTURED_FACT_TYPES.map((type) => (
          <option key={type} value={type} />
        ))}
      </datalist>
      <label className="wide">
        New structured fact content
        <input
          value={newFact.content}
          onChange={(event) => setNewFact({...newFact, content: event.target.value})}
        />
      </label>
      <button type="submit">Add structured fact</button>
    </form>
  );
}

function FactTable({
  facts,
  factDrafts,
  setFactDrafts,
  runAction,
}: {
  facts: EntityFact[];
  factDrafts: Record<string, FactDraft>;
  setFactDrafts: (drafts: Record<string, FactDraft>) => void;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Type</th>
            <th>Content</th>
            <th>Claim</th>
            <th>Policy</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {facts.map((fact) => {
            const draft = factDrafts[fact.id] ?? {
              fact_type: fact.fact_type,
              content: fact.content,
              claim_type: fact.claim_type,
              sensitivity: fact.sensitivity,
              ai_use_policy: fact.ai_use_policy,
            };
            return (
              <tr key={fact.id}>
                <td>
                  <input
                    aria-label={`Fact type ${fact.id}`}
                    value={draft.fact_type}
                    onChange={(event) =>
                      setFactDrafts({
                        ...factDrafts,
                        [fact.id]: {...draft, fact_type: event.target.value},
                      })
                    }
                  />
                </td>
                <td>
                  <input
                    aria-label={`Fact content ${fact.id}`}
                    value={draft.content}
                    onChange={(event) =>
                      setFactDrafts({
                        ...factDrafts,
                        [fact.id]: {...draft, content: event.target.value},
                      })
                    }
                  />
                </td>
                <td>{draft.claim_type}</td>
                <td>{draft.ai_use_policy}</td>
                <td>
                  <div className="action-row">
                    <button
                      type="button"
                      onClick={() =>
                        runAction(() =>
                          updateFact(fact.id, {
                            fact_type: draft.fact_type,
                            content: draft.content,
                            value: {field_path: `profile.${draft.fact_type}`, value: draft.content},
                            claim_type: draft.claim_type,
                            sensitivity: draft.sensitivity,
                            ai_use_policy: draft.ai_use_policy,
                          }),
                        )
                      }
                    >
                      Update fact {fact.id}
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => runAction(() => deleteFact(fact.id))}
                    >
                      Delete fact {fact.id}
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
          {facts.length === 0 ? (
            <tr>
              <td colSpan={5}>No active facts.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

function RelationshipRow({
  edge,
  draft,
  setDraft,
  runAction,
}: {
  edge: EntityEdge;
  draft: EdgeDraft | undefined;
  setDraft: (draft: EdgeDraft) => void;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const current = draft ?? {
    relation_type: edge.relation_type,
    claim_text: edge.claim_text,
    sensitivity: edge.sensitivity,
    ai_use_policy: edge.ai_use_policy,
  };
  return (
    <tr>
      <td>
        <input
          aria-label={`Relationship type ${edge.id}`}
          value={current.relation_type}
          onChange={(event) => setDraft({...current, relation_type: event.target.value})}
        />
      </td>
      <td>
        <input
          aria-label={`Relationship claim ${edge.id}`}
          value={current.claim_text}
          onChange={(event) => setDraft({...current, claim_text: event.target.value})}
        />
      </td>
      <td>{current.ai_use_policy}</td>
      <td>
        <div className="action-row">
          <button
            type="button"
            onClick={() =>
              runAction(() =>
                updateEdge(edge.id, {
                  relation_type: current.relation_type,
                  claim_text: current.claim_text,
                  sensitivity: current.sensitivity,
                  ai_use_policy: current.ai_use_policy,
                }),
              )
            }
          >
            Update relationship {edge.id}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => runAction(() => deleteEdge(edge.id))}
          >
            Delete relationship {edge.id}
          </button>
        </div>
      </td>
    </tr>
  );
}

function ObservationSection({
  title,
  observations,
  onDelete,
}: {
  title: string;
  observations: Observation[];
  onDelete: (observationId: string) => void;
}) {
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
            <button type="button" className="secondary" onClick={() => onDelete(observation.id)}>
              Delete observation {observation.id}
            </button>
          </article>
        ))}
        {observations.length === 0 ? <p className="muted">No observations.</p> : null}
      </div>
    </section>
  );
}

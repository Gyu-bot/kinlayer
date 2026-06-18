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
  getOntology,
  getPerson,
  listPeople,
  updateAlias,
  updateEdge,
  updateFact,
  updatePerson,
} from "../api/client";
import {FieldHelp, helpCopy} from "../components/FieldHelp";
import {
  edgeTypeOptions,
  normalizeOptionValue,
  optionsWithCurrent,
  registryOptions,
  type SelectOption,
} from "../ontologyOptions";
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

function formatTimestamp(value: string | null) {
  if (!value) {
    return "Unknown";
  }
  return new Date(value).toLocaleString();
}

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
  const [people, setPeople] = useState<Entity[]>([]);
  const [edgeTypes, setEdgeTypes] = useState<SelectOption[]>([]);
  const [factTypes, setFactTypes] = useState<SelectOption[]>([]);
  const [sensitivityOptions, setSensitivityOptions] = useState<SelectOption[]>([]);
  const [policyOptions, setPolicyOptions] = useState<SelectOption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [profileDraft, setProfileDraft] = useState({
    display_name: "",
    sensitivity: "",
    ai_use_policy: "",
    short_note: "",
  });
  const [aliasDrafts, setAliasDrafts] = useState<Record<string, string>>({});
  const [newAlias, setNewAlias] = useState("");
  const [factDrafts, setFactDrafts] = useState<Record<string, FactDraft>>({});
  const [newFact, setNewFact] = useState<FactDraft>({
    fact_type: "",
    content: "",
    claim_type: "fact",
    sensitivity: "",
    ai_use_policy: "",
  });
  const [edgeDrafts, setEdgeDrafts] = useState<Record<string, EdgeDraft>>({});
  const [newEdge, setNewEdge] = useState({
    to_entity_id: "",
    relation_type: "",
    claim_text: "",
    sensitivity: "",
    ai_use_policy: "",
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

  useEffect(() => {
    Promise.all([listPeople(""), getOntology()])
      .then(([peopleResult, ontology]) => {
        const nextEdgeTypes = edgeTypeOptions(ontology.edge_types);
        const nextFactTypes = registryOptions(ontology.fact_types);
        const nextSensitivityOptions = registryOptions(ontology.policies.sensitivity_levels);
        const nextPolicyOptions = registryOptions(ontology.policies.ai_use_policies);
        setPeople(peopleResult.items);
        setEdgeTypes(nextEdgeTypes);
        setFactTypes(nextFactTypes);
        setSensitivityOptions(nextSensitivityOptions);
        setPolicyOptions(nextPolicyOptions);
        setNewEdge((current) => {
          const firstRelated = peopleResult.items.find((personItem) => personItem.id !== id);
          return {
            ...current,
            relation_type: normalizeOptionValue(current.relation_type, nextEdgeTypes),
            to_entity_id: current.to_entity_id || firstRelated?.id || "",
            sensitivity: normalizeOptionValue(current.sensitivity, nextSensitivityOptions),
            ai_use_policy: normalizeOptionValue(current.ai_use_policy, nextPolicyOptions),
          };
        });
        setNewFact((current) => ({
          ...current,
          fact_type: normalizeOptionValue(current.fact_type, nextFactTypes),
          sensitivity: normalizeOptionValue(current.sensitivity, nextSensitivityOptions),
          ai_use_policy: normalizeOptionValue(current.ai_use_policy, nextPolicyOptions),
        }));
      })
      .catch(() => undefined);
  }, [id]);

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
          <span>{helpCopy.status.label}</span>
          <strong>{person.status}</strong>
        </div>
        <div>
          <span>{helpCopy.sensitivity.label}</span>
          <strong>{person.sensitivity}</strong>
        </div>
        <div>
          <span>{helpCopy.policy.label}</span>
          <strong>{person.ai_use_policy}</strong>
        </div>
        <div>
          <span>System role</span>
          <strong>{person.system_role ?? "None"}</strong>
        </div>
      </div>

      <section className="detail-section">
        <h2>Profile</h2>
        <p className="section-help">이 사람을 식별하고 AI가 이 사람 정보를 다루는 기본 규칙입니다.</p>
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
            <FieldHelp {...helpCopy.sensitivity} />
            <select
              value={profileDraft.sensitivity}
              onChange={(event) =>
                setProfileDraft({...profileDraft, sensitivity: event.target.value})
              }
            >
              {optionsWithCurrent(sensitivityOptions, profileDraft.sensitivity).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <FieldHelp {...helpCopy.policy} />
            <select
              value={profileDraft.ai_use_policy}
              onChange={(event) =>
                setProfileDraft({...profileDraft, ai_use_policy: event.target.value})
              }
            >
              {optionsWithCurrent(policyOptions, profileDraft.ai_use_policy).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="wide">
            <FieldHelp label="Profile note" help="이 사람을 기억할 때 바로 떠올릴 짧은 설명" />
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
        <p className="section-help">별명, 영문 이름, 줄여 부르는 이름처럼 같은 사람을 찾는 데 쓰는 이름입니다.</p>
        <form className="inline-form" onSubmit={addAlias}>
          <label>
            <FieldHelp label="New alias" />
            <input value={newAlias} onChange={(event) => setNewAlias(event.target.value)} />
          </label>
          <button type="submit">Add alias</button>
        </form>
        <div className="edit-stack">
          {aliases.map((alias) => (
            <div className="edit-row" key={alias.id}>
              <label>
                Alias
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
                Update alias
              </button>
              <button type="button" className="secondary" onClick={() => runAction(() => deleteAlias(alias.id))}>
                Delete alias
              </button>
            </div>
          ))}
          {aliases.length === 0 ? <span className="muted">No aliases.</span> : null}
        </div>
      </section>

      <section className="detail-section">
        <h2>Structured Profile Facts</h2>
        <p className="section-help">이메일, 역할, 소속처럼 종류가 정해진 정보입니다. 검색과 정책 적용에 더 안정적으로 쓰입니다.</p>
        <FactCreateForm
          newFact={newFact}
          factTypes={factTypes}
          sensitivityOptions={sensitivityOptions}
          policyOptions={policyOptions}
          setNewFact={setNewFact}
          onSubmit={addFact}
        />
        <FactTable
          facts={structuredFacts}
          factDrafts={factDrafts}
          factTypes={factTypes}
          sensitivityOptions={sensitivityOptions}
          policyOptions={policyOptions}
          setFactDrafts={setFactDrafts}
          runAction={runAction}
        />
      </section>

      <section className="detail-section">
        <h2>General Profile Facts</h2>
        <p className="section-help">아직 정해진 종류로 나누기 애매하지만, 이 사람을 이해하는 데 도움이 되는 정보입니다.</p>
        <FactTable
          facts={generalFacts}
          factDrafts={factDrafts}
          factTypes={factTypes}
          sensitivityOptions={sensitivityOptions}
          policyOptions={policyOptions}
          setFactDrafts={setFactDrafts}
          runAction={runAction}
        />
      </section>

      <section className="detail-section">
        <h2>Relationships</h2>
        <p className="section-help">나 또는 다른 사람과의 관계입니다. AI가 응답 전 관계 맥락을 잡는 데 사용합니다.</p>
        <form className="edit-grid" onSubmit={addRelationship}>
          <label>
            <FieldHelp label="Related person" />
            <select
              value={newEdge.to_entity_id}
              onChange={(event) => setNewEdge({...newEdge, to_entity_id: event.target.value})}
            >
              {people
                .filter((personItem) => personItem.id !== id)
                .map((personItem) => (
                  <option value={personItem.id} key={personItem.id}>
                    {personItem.display_name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            <FieldHelp label="Relationship type" help="어떤 관계로 기억할지" />
            <select
              value={newEdge.relation_type}
              onChange={(event) => setNewEdge({...newEdge, relation_type: event.target.value})}
            >
              {optionsWithCurrent(edgeTypes, newEdge.relation_type).map((edgeType) => (
                <option key={edgeType.value} value={edgeType.value}>
                  {edgeType.label}
                </option>
              ))}
            </select>
          </label>
          <label className="wide">
            <FieldHelp label="Relationship note" help="관계를 판단한 짧은 근거" />
            <input
              value={newEdge.claim_text}
              onChange={(event) => setNewEdge({...newEdge, claim_text: event.target.value})}
            />
          </label>
          <label>
            <FieldHelp label="Relationship sensitivity" help={helpCopy.sensitivity.help} />
            <select
              value={newEdge.sensitivity}
              onChange={(event) => setNewEdge({...newEdge, sensitivity: event.target.value})}
            >
              {optionsWithCurrent(sensitivityOptions, newEdge.sensitivity).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <FieldHelp label="Relationship AI use policy" help={helpCopy.policy.help} />
            <select
              value={newEdge.ai_use_policy}
              onChange={(event) => setNewEdge({...newEdge, ai_use_policy: event.target.value})}
            >
              {optionsWithCurrent(policyOptions, newEdge.ai_use_policy).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <button type="submit">Add relationship</button>
        </form>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Claim</th>
                <th>{helpCopy.policy.label}</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {relationshipEdges.map((edge) => (
                <RelationshipRow
                  edge={edge}
                  draft={edgeDrafts[edge.id]}
                  edgeTypes={edgeTypes}
                  sensitivityOptions={sensitivityOptions}
                  policyOptions={policyOptions}
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
        description="오래 유지되는 선호, 주의점, 배경처럼 계속 참고해도 되는 맥락입니다."
        observations={contextCard?.stable_context ?? []}
        onDelete={(observationId) => runAction(() => deleteObservation(observationId))}
      />
      <ObservationSection
        title="Recent Observations"
        description="최근 대화나 사건처럼 시간 감각이 중요한 맥락입니다."
        observations={contextCard?.recent_context ?? []}
        onDelete={(observationId) => runAction(() => deleteObservation(observationId))}
      />

      <section className="detail-section">
        <h2>Provenance</h2>
        <p className="section-help">이 정보가 어디서 왔는지 확인하는 짧은 근거입니다.</p>
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
              <span>{item.excerpt ?? `${item.record_type} record`}</span>
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
  factTypes,
  sensitivityOptions,
  policyOptions,
  setNewFact,
  onSubmit,
}: {
  newFact: FactDraft;
  factTypes: SelectOption[];
  sensitivityOptions: SelectOption[];
  policyOptions: SelectOption[];
  setNewFact: (fact: FactDraft) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <form className="edit-grid" onSubmit={onSubmit}>
      <label>
        <FieldHelp label="New structured fact type" help="이메일, 역할, 소속처럼 어떤 정보인지" />
        <select
          value={newFact.fact_type}
          onChange={(event) => setNewFact({...newFact, fact_type: event.target.value})}
        >
          {optionsWithCurrent(factTypes, newFact.fact_type).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label className="wide">
        <FieldHelp label="New structured fact content" />
        <input
          value={newFact.content}
          onChange={(event) => setNewFact({...newFact, content: event.target.value})}
        />
      </label>
      <label>
        <FieldHelp label="New structured fact sensitivity" help={helpCopy.sensitivity.help} />
        <select
          value={newFact.sensitivity}
          onChange={(event) => setNewFact({...newFact, sensitivity: event.target.value})}
        >
          {optionsWithCurrent(sensitivityOptions, newFact.sensitivity).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        <FieldHelp label="New structured fact AI use policy" help={helpCopy.policy.help} />
        <select
          value={newFact.ai_use_policy}
          onChange={(event) => setNewFact({...newFact, ai_use_policy: event.target.value})}
        >
          {optionsWithCurrent(policyOptions, newFact.ai_use_policy).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <button type="submit">Add structured fact</button>
    </form>
  );
}

function FactTable({
  facts,
  factDrafts,
  factTypes,
  sensitivityOptions,
  policyOptions,
  setFactDrafts,
  runAction,
}: {
  facts: EntityFact[];
  factDrafts: Record<string, FactDraft>;
  factTypes: SelectOption[];
  sensitivityOptions: SelectOption[];
  policyOptions: SelectOption[];
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
            <th>{helpCopy.claim.label}</th>
            <th>{helpCopy.policy.label}</th>
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
                  <select
                    aria-label={`Fact type ${fact.fact_type}`}
                    value={draft.fact_type}
                    onChange={(event) =>
                      setFactDrafts({
                        ...factDrafts,
                        [fact.id]: {...draft, fact_type: event.target.value},
                      })
                    }
                  >
                    {optionsWithCurrent(factTypes, draft.fact_type).map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    aria-label={`Fact content ${fact.fact_type}`}
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
                <td>
                  <div className="stacked-selects">
                    <select
                      aria-label={`Fact sensitivity ${fact.fact_type}`}
                      value={draft.sensitivity}
                      onChange={(event) =>
                        setFactDrafts({
                          ...factDrafts,
                          [fact.id]: {...draft, sensitivity: event.target.value},
                        })
                      }
                    >
                      {optionsWithCurrent(sensitivityOptions, draft.sensitivity).map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <select
                      aria-label={`Fact AI use policy ${fact.fact_type}`}
                      value={draft.ai_use_policy}
                      onChange={(event) =>
                        setFactDrafts({
                          ...factDrafts,
                          [fact.id]: {...draft, ai_use_policy: event.target.value},
                        })
                      }
                    >
                      {optionsWithCurrent(policyOptions, draft.ai_use_policy).map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </td>
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
                      Update fact
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => runAction(() => deleteFact(fact.id))}
                    >
                      Delete fact
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
  edgeTypes,
  sensitivityOptions,
  policyOptions,
  setDraft,
  runAction,
}: {
  edge: EntityEdge;
  draft: EdgeDraft | undefined;
  edgeTypes: SelectOption[];
  sensitivityOptions: SelectOption[];
  policyOptions: SelectOption[];
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
        <select
          aria-label={`Relationship type ${edge.relation_type}`}
          value={current.relation_type}
          onChange={(event) => setDraft({...current, relation_type: event.target.value})}
        >
          {optionsWithCurrent(edgeTypes, current.relation_type).map((edgeType) => (
            <option key={edgeType.value} value={edgeType.value}>
              {edgeType.label}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          aria-label={`Relationship claim ${edge.relation_type}`}
          value={current.claim_text}
          onChange={(event) => setDraft({...current, claim_text: event.target.value})}
        />
      </td>
      <td>
        <div className="stacked-selects">
          <select
            aria-label={`Relationship sensitivity ${edge.relation_type}`}
            value={current.sensitivity}
            onChange={(event) => setDraft({...current, sensitivity: event.target.value})}
          >
            {optionsWithCurrent(sensitivityOptions, current.sensitivity).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            aria-label={`Relationship AI use policy ${edge.relation_type}`}
            value={current.ai_use_policy}
            onChange={(event) => setDraft({...current, ai_use_policy: event.target.value})}
          >
            {optionsWithCurrent(policyOptions, current.ai_use_policy).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </td>
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
            Update relationship
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => runAction(() => deleteEdge(edge.id))}
          >
            Delete relationship
          </button>
        </div>
      </td>
    </tr>
  );
}

function ObservationSection({
  title,
  description,
  observations,
  onDelete,
}: {
  title: string;
  description: string;
  observations: Observation[];
  onDelete: (observationId: string) => void;
}) {
  return (
    <section className="detail-section">
      <h2>{title}</h2>
      <p className="section-help">{description}</p>
      <div className="debug-stack">
        {observations.map((observation) => (
          <article className="match-summary" key={observation.id}>
            <div>
              <strong>{observation.observation_type}</strong>
              <span>{observation.embedding_status}</span>
            </div>
            <p>{observation.content}</p>
            <div className="pill-row">
              <span className="pill">{helpCopy.claim.label}: {observation.claim_type}</span>
              <span className="pill">{helpCopy.policy.label}: {observation.ai_use_policy}</span>
              <span className="pill">{helpCopy.sensitivity.label}: {observation.sensitivity}</span>
            </div>
            <div className="pill-row">
              {observation.occurred_at ? (
                <span className="pill">Event: {formatTimestamp(observation.occurred_at)}</span>
              ) : null}
              {observation.valid_from ? (
                <span className="pill">Valid from: {formatTimestamp(observation.valid_from)}</span>
              ) : null}
              {observation.valid_to ? (
                <span className="pill">Valid to: {formatTimestamp(observation.valid_to)}</span>
              ) : null}
            </div>
            <button type="button" className="secondary" onClick={() => onDelete(observation.id)}>
              Delete observation
            </button>
          </article>
        ))}
        {observations.length === 0 ? <p className="muted">No observations.</p> : null}
      </div>
    </section>
  );
}

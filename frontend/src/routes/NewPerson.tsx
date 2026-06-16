import {FormEvent, useEffect, useState} from "react";

import {createPerson, getOntology} from "../api/client";
import {
  edgeTypeOptions,
  normalizeOptionValue,
  observationTypeOptions,
  optionsWithCurrent,
  registryOptions,
  type SelectOption,
} from "../ontologyOptions";

type Props = {
  onNavigate: (path: string) => void;
};

export function NewPerson({onNavigate}: Props) {
  const [displayName, setDisplayName] = useState("");
  const [aliases, setAliases] = useState("");
  const [sensitivity, setSensitivity] = useState("medium");
  const [aiUsePolicy, setAiUsePolicy] = useState("cautious_use");
  const [shortNote, setShortNote] = useState("");
  const [factType, setFactType] = useState("");
  const [factContent, setFactContent] = useState("");
  const [initialRelationshipType, setInitialRelationshipType] = useState("");
  const [initialRelationshipNote, setInitialRelationshipNote] = useState("");
  const [initialObservationType, setInitialObservationType] = useState("");
  const [initialObservation, setInitialObservation] = useState("");
  const [factTypeOptions, setFactTypeOptions] = useState<SelectOption[]>([]);
  const [edgeTypes, setEdgeTypes] = useState<SelectOption[]>([]);
  const [observationTypes, setObservationTypes] = useState<SelectOption[]>([]);
  const [sensitivityOptions, setSensitivityOptions] = useState<SelectOption[]>([]);
  const [policyOptions, setPolicyOptions] = useState<SelectOption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getOntology()
      .then((ontology) => {
        const nextFactTypes = registryOptions(ontology.fact_types);
        const nextEdgeTypes = edgeTypeOptions(ontology.edge_types);
        const nextObservationTypes = observationTypeOptions(ontology.observation_types);
        const nextSensitivityOptions = registryOptions(ontology.policies.sensitivity_levels);
        const nextPolicyOptions = registryOptions(ontology.policies.ai_use_policies);
        setFactTypeOptions(nextFactTypes);
        setEdgeTypes(nextEdgeTypes);
        setObservationTypes(nextObservationTypes);
        setSensitivityOptions(nextSensitivityOptions);
        setPolicyOptions(nextPolicyOptions);
        setFactType((current) => normalizeOptionValue(current, nextFactTypes));
        setInitialRelationshipType((current) => normalizeOptionValue(current, nextEdgeTypes));
        setInitialObservationType((current) => normalizeOptionValue(current, nextObservationTypes));
        setSensitivity((current) => normalizeOptionValue(current, nextSensitivityOptions));
        setAiUsePolicy((current) => normalizeOptionValue(current, nextPolicyOptions));
      })
      .catch(() => undefined);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    try {
      const entity = await createPerson({
        displayName,
        aliases: aliases
          .split(",")
          .map((alias) => alias.trim())
          .filter(Boolean),
        sensitivity,
        aiUsePolicy,
        shortNote,
        factType,
        factContent,
        initialRelationshipType,
        initialRelationshipNote,
        initialObservationType,
        initialObservation,
      });
      onNavigate(`/people/${entity.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create person.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="page-section narrow" aria-labelledby="new-person-title">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Bootstrap</p>
          <h1 id="new-person-title">New Person</h1>
        </div>
        <button type="button" className="secondary" onClick={() => onNavigate("/people")}>
          Back
        </button>
      </div>

      <form className="form" onSubmit={submit}>
        <label>
          <span>Display name</span>
          <input required value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </label>
        <label>
          <span>Aliases</span>
          <input
            value={aliases}
            onChange={(e) => setAliases(e.target.value)}
            placeholder="Comma-separated"
          />
        </label>
        <div className="form-grid">
          <label>
            <span>Sensitivity</span>
            <select value={sensitivity} onChange={(e) => setSensitivity(e.target.value)}>
              {optionsWithCurrent(sensitivityOptions, sensitivity).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>AI use policy</span>
            <select value={aiUsePolicy} onChange={(e) => setAiUsePolicy(e.target.value)}>
              {optionsWithCurrent(policyOptions, aiUsePolicy).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label>
          <span>Short note</span>
          <textarea value={shortNote} onChange={(e) => setShortNote(e.target.value)} />
        </label>
        <div className="form-grid">
          <label>
            <span>Profile fact type</span>
            <select value={factType} onChange={(e) => setFactType(e.target.value)}>
              {optionsWithCurrent(factTypeOptions, factType).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Profile fact</span>
            <input value={factContent} onChange={(e) => setFactContent(e.target.value)} />
          </label>
        </div>
        <section className="form-section">
          <h2>Initial Relationship</h2>
          <div className="form-grid">
            <label>
              <span>Initial relationship type</span>
              <select
                value={initialRelationshipType}
                onChange={(e) => setInitialRelationshipType(e.target.value)}
              >
                {optionsWithCurrent(edgeTypes, initialRelationshipType).map((edgeType) => (
                  <option key={edgeType.value} value={edgeType.value}>
                    {edgeType.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Initial relationship note</span>
              <input
                value={initialRelationshipNote}
                onChange={(e) => setInitialRelationshipNote(e.target.value)}
              />
            </label>
          </div>
        </section>
        <section className="form-section">
          <h2>Initial Observation</h2>
          <div className="form-grid">
            <label>
              <span>Initial observation type</span>
              <select
                value={initialObservationType}
                onChange={(e) => setInitialObservationType(e.target.value)}
              >
                {optionsWithCurrent(observationTypes, initialObservationType).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Initial observation</span>
              <textarea
                value={initialObservation}
                onChange={(e) => setInitialObservation(e.target.value)}
              />
            </label>
          </div>
        </section>
        {error ? <p className="error">{error}</p> : null}
        <button type="submit" disabled={submitting}>
          {submitting ? "Creating..." : "Create person"}
        </button>
      </form>
    </section>
  );
}

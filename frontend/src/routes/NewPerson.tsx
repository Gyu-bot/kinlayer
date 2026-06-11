import {FormEvent, useState} from "react";

import {createPerson} from "../api/client";

type Props = {
  onNavigate: (path: string) => void;
};

export function NewPerson({onNavigate}: Props) {
  const [displayName, setDisplayName] = useState("");
  const [aliases, setAliases] = useState("");
  const [sensitivity, setSensitivity] = useState("medium");
  const [aiUsePolicy, setAiUsePolicy] = useState("cautious_use");
  const [shortNote, setShortNote] = useState("");
  const [factType, setFactType] = useState("organization");
  const [factContent, setFactContent] = useState("");
  const [initialRelationshipType, setInitialRelationshipType] = useState("knows");
  const [initialRelationshipNote, setInitialRelationshipNote] = useState("");
  const [initialObservationType, setInitialObservationType] = useState("recent_interaction");
  const [initialObservation, setInitialObservation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </label>
          <label>
            <span>AI use policy</span>
            <select value={aiUsePolicy} onChange={(e) => setAiUsePolicy(e.target.value)}>
              <option value="freely_use">freely_use</option>
              <option value="cautious_use">cautious_use</option>
              <option value="ask_before_use">ask_before_use</option>
              <option value="never_surface">never_surface</option>
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
              <option value="organization">organization</option>
              <option value="role">role</option>
              <option value="job">job</option>
              <option value="relationship_note">relationship_note</option>
              <option value="important_context">important_context</option>
              <option value="external_handle">external_handle</option>
              <option value="location_hint">location_hint</option>
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
                <option value="knows">knows</option>
                <option value="friend">friend</option>
                <option value="family">family</option>
                <option value="coworker">coworker</option>
                <option value="client_contact">client_contact</option>
                <option value="collaborated_with">collaborated_with</option>
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
                <option value="recent_interaction">recent_interaction</option>
                <option value="communication_preference">communication_preference</option>
                <option value="relationship_context">relationship_context</option>
                <option value="caution">caution</option>
                <option value="care_point">care_point</option>
                <option value="user_preference_about_person">user_preference_about_person</option>
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

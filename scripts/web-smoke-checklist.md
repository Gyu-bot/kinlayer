# Kinlayer Web Smoke Checklist

Run after `scripts/load-acceptance-fixtures.py` against the local stack.

- `/people`
  - People table loads without visible error.
  - Search and status/sensitivity filters are visible.
  - Alias preview, relationship summary, status, sensitivity, and last referenced columns render.
- `/people/new`
  - Person form renders.
  - Optional initial relationship and initial observation fields are visible.
  - Creating a person routes to its detail page.
- `/people/:id`
  - Fixture person `Acceptance Minji` or the newly created person opens from a direct detail URL.
  - Profile facts, relationships, stable/recent observations, provenance, and policy fields render.
  - Evidence from accepted candidates or corrections appears in the provenance section when present.
- `/candidates`
  - Status, type, and sensitivity filters render.
  - Pending candidates can be selected.
  - Switching to accepted status shows the accepted fixture candidate and its `canonical_record_ref`.
  - Accept, reject, archive, needs clarification, and edit-accept controls are visible.
- `/graph`
  - Ego graph renders from protected self with at least self plus two people.
  - Entity selector and relation/status/sensitivity filters render.
  - Node and edge detail panels can be opened.
- `/retrieval-debug`
  - Retrieve and pack debug controls render.
  - A Korean query with a fixture entity hint returns matched entity, bucket, score, and debug metadata.
  - The accepted candidate observation is inspectable in the debug result after fixture load.
- `/settings`
  - Health, config, embedding, and ontology sections render.
  - Local API token status is shown without exposing the token value.
- Browser console
  - Complete route sweep produces no new console errors.

# Kinlayer Web UI Specification

- Status: Draft v0.1
- Parent PRD: `prd.md`
- Related docs: `data-model.md`, `context-output-contract.md`, `candidate-lifecycle-and-payload.md`, `cli-spec.md`

---

## 1. Purpose

Kinlayer's Web UI is a minimal human-friendly control plane.

It is not the canonical capability layer. The HTTP API owns canonical capabilities; the Web UI is an API client for:

- bootstrap seed entry;
- candidate review;
- person/context inspection;
- manual cleanup;
- retrieval debugging;
- 1-hop ego graph viewing.

No Web-only state-changing capability is allowed.

---

## 2. MVP Screens

```text
/people
/people/new
/people/:id
/candidates
/graph
/retrieval-debug
/settings
```

Excluded from MVP:

```text
/episodes
/imports
/connectors
/audit
/ontology full admin
full-network graph analytics
```

---

## 3. `/people`

Purpose: list and search person entities.

Required behavior:

- list people with display name, aliases preview, relationship summary, status, sensitivity, last_referenced_at;
- search by name/alias using API-backed query;
- filter by status/sensitivity where API supports it;
- create button linking to `/people/new`;
- click row/card to open `/people/:id`.

MVP non-goals:

- bulk edit;
- advanced CRM fields;
- contact/address book replacement.

---

## 4. `/people/new`

Purpose: manual bootstrap seed entry.

Required fields:

- display_name;
- aliases optional;
- sensitivity;
- ai_use_policy;
- short note / lightweight properties;
- optional initial relationship edge to protected self entity;
- optional initial observation.

Expected behavior:

- creates `entities` row;
- creates aliases if provided;
- creates optional initial edge/observation through API;
- redirects to `/people/:id` after creation.

MVP non-goals:

- multi-step import wizard;
- connector-backed contact import;
- full ontology editing.

---

## 5. `/people/:id`

Purpose: inspect and lightly edit a person context.

Required sections:

1. Entity summary
   - display_name;
   - aliases;
   - sensitivity;
   - ai_use_policy;
   - status;
   - last_referenced_at.

2. Context card preview
   - calls `GET /api/entities/{id}/context-card`;
   - shows stable_context, recent_context, communication_context, cautions;
   - shows surface/policy markers.

3. Profile facts
   - list active `entity_facts`;
   - show claim_type/confidence/policy.

4. Relationship edges
   - list active edges to/from this person;
   - show relation_type, direction, confidence, status.

5. Observations
   - list observations where subject or related entity includes this person;
   - group recent/stable/caution-oriented sections where context-card data supports it.

6. Evidence/provenance panel
   - show source episode metadata and bounded excerpts for selected fact/edge/observation;
   - no full raw archive display in MVP.

Current MVP actions:

- navigate back to `/people`;
- inspect context card, evidence, policy, and relationship/observation sections.

Future API-backed actions:

- patch entity summary fields;
- add/deprecate alias;
- soft delete/deprecate canonical records through DELETE endpoints;
- open related candidates if applicable.

MVP non-goals:

- complete audit timeline;
- full raw conversation viewer;
- advanced merge UI.

---

## 6. `/candidates`

Purpose: candidate inbox and review surface.

Required behavior:

- list candidates with status, candidate_type, target entity, confidence, sensitivity, created_by, created_at;
- filter by status/type/sensitivity;
- show candidate detail drawer/panel with payload, evidence excerpts, suggested action;
- actions:
  - accept;
  - edit-accept;
  - reject;
  - archive;
  - needs-clarification.

Expected action semantics:

- accept/edit-accept call explicit action endpoints and may create canonical records;
- reject/archive/needs-clarification update candidate workflow state;
- supersede links candidate replacement through API/CLI, but is not a current Web control.

MVP non-goals:

- batch changesets;
- event-sourced candidate history;
- multi-user approval workflow.

---

## 7. `/graph`

Purpose: person-first 1-hop ego graph view.

Required behavior:

- select focal person;
- call `GET /api/graph/ego/{entity_id}`;
- render generic graph response with React Flow adapter;
- support filters:
  - relation_type;
  - status;
  - sensitivity;
- node click opens person detail side panel;
- edge click opens edge detail/evidence side panel.

MVP official support:

```text
depth = 1
```

MVP non-goals:

- full-network graph;
- community detection;
- centrality metrics;
- timeline graph;
- polished graph analytics.

---

## 8. `/retrieval-debug`

Purpose: inspect retrieval and context pack behavior.

Required behavior:

- input fields:
  - query;
  - situation;
  - focal_entity_id;
  - candidate entity IDs / entity_hints;
- call `POST /api/context/retrieve`;
- call `POST /api/context/pack`;
- display:
  - matched entities;
  - matched observations;
  - score breakdown;
  - confidence band;
  - suggested_response_policy;
  - context buckets;
  - raw debug metadata when returned.

MVP non-goals:

- prompt engineering lab;
- LLM response generation;
- automatic candidate extraction UI.

---

## 9. `/settings`

Purpose: local instance status and read-only configuration inspection.

Required sections:

- system health/status;
- database health;
- optional bearer token configured/not configured state;
- embedding provider status;
- active embedding model and dimension;
- OpenAI-compatible embedding API URL/API key configured state without displaying secret values;
- server `.env` key names for embedding setup, including provider, API URL, API key, model, and dimension;
- ontology registry read-only lists:
  - entity types;
  - fact types;
  - edge types;
  - observation types;
  - sensitivity levels;
  - ai_use_policies.

MVP non-goals:

- full auth/user management;
- token value display after save;
- full ontology editor;
- connector setup wizard.

---

## 10. UX Priorities

MVP Web UI should optimize for:

```text
clarity > polish
control > automation theater
correctability > archive browsing
agent runtime debugging > CRM completeness
```

The UI should make it easy to answer:

1. Who is this person?
2. What does Kinlayer remember about them?
3. Why did the agent retrieve this context?
4. What is pending review?
5. How do I correct or hide a bad memory?

# Kinlayer Web UI Specification

> **2026-10-01 replacement contract:** The user authorized replacing the old frontend with
> the reviewed `frontend_v2` design and the save-first corrections proposed in its audit.
> The active app is `frontend/`, implemented in `src/v2/`; `frontend_v2/` is a preserved reference.
> This current contract takes precedence over the historical MVP sections below.
> See the [delivery plan](../plans/frontend-rebuild.md) and
> [verification record](../verification/frontend-v2/README.md).

## Current replacement: navigation and routes

The UI uses Korean labels and the mockup's system fonts, spacing, neutral surfaces and blue action
color. Its primary navigation is 사람 / 기억 / 관계 그래프 / 변경 이력. Search, Settings and legacy
records remain secondary. The app uses actual API responses; browser demo state is not a fallback
when the API fails.

| Route | Behavior |
| --- | --- |
| `/people` | Server-paginated name/alias search, relationship filter, name/recent-reference sort, list/card view, matching person preview and explicit person creation. |
| `/people/:id` | Overview with paginated profile facts, all-information inventory, structured profile, relationships, sources and changes; direct profile/relationship entry and independent name/alias editing. |
| `/memories` | Server-side text/person/type/basis/current-history filters, exact memory links and individual creation. |
| `/memories?record=...` | Exact current or historical record, participants, basis, source/event/validity times and changes; correct/retract/reattribute actions where the server status permits them. |
| `/graph?focal=...` | Actual protected-self/default or selected person, 1-hop graph, ontology relation filters, directions, zoom/pan and equivalent mobile relationship access. Nodes open people; edges open the exact memory/source. |
| `/changes` | Paginated overall, person- or record-scoped changes and selected old/new comparison with the change's own source. `change`, `person` and `record` query parameters retain precise context. |
| `/sources/:id` | Bounded source excerpt, author, source/ingestion time, locator and linked memories across current and historical states. |
| `/search` | Query/situation and server-searchable paginated person selection, context retrieve/pack results, basis, uncertainty, partial dates and exact memory/source links. Diagnostic scores stay secondary. |
| `/settings` | API address/health/database/auth, user-entered local token management and separate embedding configuration/index counts. No provider secret values or embedding mutation. |
| `/legacy` | Read-only historical candidates and agent-operation filters/details. Official JSONL export is bounded to the first 200 filtered operations; CSV contains only the current page. |

Compatibility addresses `/retrieval-debug`, `/candidates`, `/agent-operations`, `/reviews` and
`/people/new` resolve to replacement surfaces rather than restoring the old edit/approval UI.
New people are added through the People dialog. `/reviews` opens Changes. Unsupported or
owner-unknown historical refs remain readable technical details instead of broken memory links;
`entities:` refs and aliases with a known owner open person detail.
Change comparisons fetch memory details only for fact, relationship and observation refs.
Identity migration rows link to the current person and explicitly state that the receipt has no
historical identity snapshot. Alias or unsupported refs without a known owner show an explanation
and collapsed technical details, without a broken memory link or an inferred owner.

## Current replacement: writes and source fidelity

- Memory creation, correction, retraction and reattribution use only `POST /api/memories`. Existing
  entity/alias APIs remain the identity-only paths for creating people or changing names/aliases.
  The UI never bypasses `409 memory_change_required` via old record mutation endpoints.
- Direct profile entry requires the actual value or known date components, without a separate
  memory narrative. Relationships require both people and an ontology-supported type; description
  is optional, and an empty description uses the selected relation's direction and label.
  For profile/relationship creation and correction, a blank source excerpt uses the visible direct
  input summary, including entered relationship properties; a blank actor means `나` (the user).
  Both defaults are explained before saving. Optional explicit source text/actor take precedence.
  These remain `manual_entry` evidence, never a fabricated conversation or inferred source time.
  Observation, retraction and reattribution flows still require explicit human source input.
- Before memory writes, inspect `GET /api/system/config.memory_write`: endpoint `/api/memories`,
  `contract_version: "2"`, `review_required: false`. Older/incompatible or unreachable servers leave
  saving unavailable and explain the cause.
- Correction and reattribution carry the exact old ref and `expected_updated_at`; retraction carries
  no replacement record. Every request includes the current human input/source and a request ID.
  A failed request preserves the draft. Unchanged retries reuse their ID; a changed body gets a new
  ID. Success appears only after an API receipt. LAN HTTP must not depend on secure-context-only
  `crypto.randomUUID`.
- Show `reported`, `inferred` and `unknown` as provenance distinctions, not verification or usage
  permission. Preserve uncertainty and future wording. An uncertain future employer is not silently
  installed as a current organization.
- Structured birthdays and birth dates preserve known precision. Never fill a missing year/month/day.
  Keep speaker, experiencer, subject and other participant roles distinct. Keep source time, event
  time, record time and validity separate; unchanged source record times retain their precision.
- Superseded, retracted and out-of-validity records remain inspectable in history without appearing
  as current memory. Available evidence excerpts survive a missing original source; a missing source
  does not create a working-looking link or fabricated author/date.
- Direction and relation type come from the live ontology; simultaneous relationships do not collapse
  into a single edge. Graph, context and directory views use current-validity rules.

The old candidate inbox has no accept/edit-accept/reject/archive mutation controls in the replacement.
AI-use-policy, sensitivity and confirmation gates are not part of the current product flow.
The browser stores only the user-entered API token in localStorage; people, memory, source, status
and history are server state. Saved tokens are never re-displayed.

## Current replacement: reads and verification

`GET /api/people` supplies complete-set filtering, sorting, summaries and pagination.
`GET /api/memories` supplies unified current/history inventory with exact refs, sources and role
metadata; `GET /api/memories/{record_type}/{record_id}` exposes individual historical records.
`GET /api/memory-changes` supports record/person scopes, and source detail combines an episode
read with reverse memory filtering. Existing retrieval, graph, health/config and embedding status
APIs remain the authoritative capabilities. A ready embedding configuration is not proof of indexed
records or a successful provider call.

The person overview puts basic profile information before relationship assessments. It does not
truncate profile facts to six or whitelist fact types. It pages all
current facts, including `job`, `birthday` and `birth_date`, independently from the context list.
The `전체 정보` tab pages facts, relationships and observations together and exposes current,
historical/future/retracted and all-record filters. Existing entity properties remain readable in
a secondary section. Record detail exposes the full saved payload, including older structured
fact values and unknown additional fields, without treating historical records as current.

Acceptance IDs UI01–UI09 remain in the delivery plan. Direct browser checks must cover Korean text,
desktop/mobile layout, keyboard/focus, empty/error/loading states, exact-record changes and preserved
history against a non-production API. Final results and limitations belong in the verification
record. No migration, production deployment or live-data conversion is implied by the replacement
or its disposable preview. Time-range list filters and direct conversational messaging are not
implemented by this delivery.

---

## Historical MVP v0.1 contract — preserved for traceability

**Everything below this boundary, including sections 1–11 and the Periodic Curation Boundary, is
historical implementation/compatibility context.** Its approval, policy, legacy PATCH/DELETE and
candidate merge controls are not requirements for the replacement. Backend compatibility APIs may
remain available independently of the UI. The original wording, numbering and rationale are kept.

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

By default, the Web UI should present names, summaries, ontology labels, status, policy, and
bounded excerpts rather than raw UUIDs or internal record refs. IDs may still be used in URLs,
React keys, API payloads, and explicit raw/debug affordances, but they should not be the normal
visible workflow input or label.

---

## 2. MVP Screens

```text
/people
/people/new
/people/:id
/candidates
/agent-operations
/graph
/retrieval-debug
/settings
```

Excluded from MVP:

```text
/episodes
/imports
/connectors
/audit full timeline
/ontology full admin
full-network graph analytics
```

---

## 3. `/people`

Purpose: list and search person entities.

Required behavior:

- list people with display name, aliases preview, relationship summary, status, last_referenced_at;
- search by name/alias using API-backed query;
- filter by status where API supports it, including `merged` for audit inspection;
- create button linking to `/people/new`;
- open each person through an explicit display-name action, such as `Open {display_name}`,
  while keeping the entity ID internal;
- click row/card to open `/people/:id` as a secondary shortcut.
- hide merged source entities from the default active people workflow while allowing direct URL or
  merged-status filter inspection.

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
- ai_use_policy;
- short note / lightweight properties;
- optional initial relationship edge to protected self entity;
- optional initial observation.

Expected behavior:

- creates `entities` row;
- creates aliases if provided;
- creates optional initial edge/observation through API;
- loads initial relationship type choices from ontology edge types and submits the selected
  canonical `relation_type`;
- loads profile fact type, initial observation type, and AI use policy choices from
  ontology registries or policy values and submits canonical values;
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
   - use ontology-backed fact type and AI use policy controls for creation and edit
     flows.
   - support adding structured profile facts for `legal_name`, `birth_date`, `phone`, `email`,
     `address`, `organization`, and `role` through the canonical entity-facts API.
   - validate empty structured content client-side where practical and surface API
     `validation_error` responses without rewriting user-entered values.
   - allow active general profile facts to be promoted into structured profile facts through
     `POST /api/entity-facts/{id}/promote`; successful promotion refreshes person detail, shows the
     replacement under structured facts, and removes the stale source from the active fact list.

4. Relationship edges
   - list active edges to/from this person;
   - show ontology-backed relationship type, direction, confidence, status;
   - use person selectors for related people while storing entity IDs internally;
   - hide edge IDs from default row labels and button text.

5. Observations
   - list observations where subject or related entity includes this person;
   - group recent/stable/caution-oriented sections where context-card data supports it.

6. Evidence/provenance panel
   - show source episode metadata and bounded excerpts for selected fact/edge/observation;
   - show record type and excerpt/summary before any technical record ref;
   - no full raw archive display in MVP.

Current MVP actions:

- navigate back to `/people`;
- inspect context card, evidence, policy, and relationship/observation sections.
- patch entity summary fields;
- add/deprecate alias;
- soft delete/deprecate canonical records through DELETE endpoints;
- add and update relationship edges with ontology-backed relationship type and AI
  use policy controls;
- add and update profile facts with ontology-backed fact type and AI use policy
  controls;
- open related candidates if applicable.

MVP non-goals:

- complete audit timeline;
- full raw conversation viewer;
- bulk merge UI.

Merge contract:

- Merge execution is reviewed from `/candidates`, not directly from person detail.
- Review UI must show source/target names, aliases, facts, relationship edges, observations,
  policy conflicts, protected self warnings, and risk notes before enabling merge
  accept.
- Merge accept is disabled until the reviewer confirms the target and acknowledges audit/risk notes.
- Web must not perform merge rewrites client-side; all state changes go through the canonical API.

---

## 6. `/candidates`

Purpose: candidate inbox and review surface.

Required behavior:

- list candidates with status, candidate_type, target entity, confidence, created_by, created_at;
- replace candidate IDs in the default list/detail with candidate summaries, type, status,
  confidence, target summary, and timestamps;
- filter by status/type;
- show candidate detail drawer/panel with evidence excerpts and suggested action;
- render `merge` candidates with a source/target comparison panel, merge fields, risk warnings,
  target confirmation, and audit acknowledgement;
- show `supersedes_record_ref` for `profile_field` candidates in the candidate detail surface so a
  reviewer can see when acceptance will promote and supersede an existing `entity_facts` row;
- keep raw/edit payload JSON behind an explicit raw payload affordance so internal entity IDs are not
  visible by default;
- actions:
  - accept;
  - edit-accept;
  - reject;
  - archive;
  - needs-clarification.

Expected action semantics:

- accept/edit-accept call explicit action endpoints and may create canonical records;
- `profile_field` accept/edit-accept with `supersedes_record_ref` promotes the referenced general
  fact into a structured replacement and marks the source fact superseded through the API.
- merge accept calls the same candidate accept endpoint, returns a canonical `entities` record ref,
  and does not expose edit-accept for merge candidates;
- reject/archive/needs-clarification update candidate workflow state;
- supersede links candidate replacement through API/CLI and Web candidate detail controls.

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
  - relation_type from ontology edge types, plus an all-types option;
  - status;
- node click opens person detail side panel;
- edge click opens edge detail/evidence side panel.
- detail panels show names, relationship labels, direction, status, and confidence
  without raw entity or edge IDs by default.

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
  - focal entity selector;
  - candidate entity selector / entity_hints;
- call `POST /api/context/retrieve`;
- call `POST /api/context/pack`;
- display:
  - matched entities;
  - matched observations;
  - score breakdown;
  - confidence band;
  - suggested_response_policy;
  - context buckets;
  - debug metadata keyed by display names where practical;
  - raw retrieval payload only behind an explicit raw/debug affordance.

MVP non-goals:

- prompt engineering lab;
- LLM response generation;
- automatic candidate extraction UI.

---

## 9. `/agent-operations`

Purpose: inspect and export AI-agent write attempts, direct edge relation-type write diagnostics,
and their outcomes.

Required behavior:

- list recent agent write operations from `GET /api/agent-operations`;
- filter by actor, source path, operation type, result status, diagnostic/error status, and optional time range;
- show operation type, result, actor, candidate/correction/canonical refs where available, submitted
  `relation_type`, edge-type diagnostic status where available, and bounded excerpt;
- provide an Export action that downloads the current filter from `GET /api/agent-operations/export`;
- keep export bounded and redacted.

Non-goals:

- retrieval/context-pack read history;
- full prompt archive;
- raw conversation transcript viewer;
- general Docker/container log viewer;
- full audit timeline across manual UI actions.

---

## 10. `/settings`

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
  - ai_use_policies.

MVP non-goals:

- full auth/user management;
- token value display after save;
- full ontology editor;
- connector setup wizard.

---

## 11. UX Priorities

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
## Periodic Curation Boundary

Repository Phases 1-4 use API and CLI as the canonical control surface. No state-changing curation UI
is implemented. A future Web surface may provide read-only run/decision audit views through the same
API, never a second execution path.

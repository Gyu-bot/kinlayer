# PRD v0.3 — Kinlayer

> Current decisions: [save-first memory schema](../plans/save-first-memory-schema.md).
> Immediate canonical storage replaces candidate-first approval and AI-use-policy gating.
> Embeddings remain in scope. Existing CLI/Web/candidate descriptions below also document deployed
> compatibility surfaces; frontend replacement is [planning only](../plans/frontend-rebuild.md).


- Status: save-first revision, 2026-10-01
- Product name: Kinlayer
- Audience: Codex, Claude Code, and future implementation agents
- Last major rewrite: aligned with decision ledger through MVP API/Web/CLI/retrieval/embedding decisions

---

## 1. Product Summary

Kinlayer is a local-first relationship context layer for AI agents.

It helps AI agents accumulate, retrieve, and safely use person/relationship context while giving the user a control plane to inspect and correct that context.

Kinlayer is not a generic CRM, not a social network analyzer, and not a relationship counseling app. It is agent memory infrastructure for relationship-aware workflows.

Core definition:

> Kinlayer is a correctable, source-attributed relationship memory layer for AI agents, with a lightweight human control plane.

Core product loop:

```text
User talks with an AI agent
→ agent retrieves relationship context from Kinlayer
→ agent answers using source-attributed context with explicit claim basis
→ conversation reveals new people/relationships/observations/corrections
→ agent immediately saves atomic claims with human sources through /api/memories
→ user points out errors in conversation; exact records are corrected, retracted or reattributed
```

The primary usage path is AI-agent conversation. Web UI and CLI are supporting control/debug/bootstrap channels.

---

## 2. Product Positioning

Kinlayer sits between three categories:

- Personal CRM
  - people, notes, and relationships;
  - usually weak AI runtime retrieval and provenance.

- AI memory layer
  - long-term memory for agents;
  - usually not relationship-specific and not user-review/control-plane-first.

- Temporal context graph
  - provenance, temporal relationships, hybrid retrieval;
  - usually not packaged as a relationship context product for agent use.

Kinlayer's position:

> A local-first relationship context store and control plane for AI agents, using immediate writes, provenance, correction history, and hybrid retrieval.

---

## 3. Target Users and Actors

### Primary user

A local-first AI-agent power user who wants agents to remember and use relationship context across conversations while retaining control over what is trusted, corrected, retrieved, and surfaced.

Examples:

- users running personal AI agents locally or self-hosted;
- users who want relationship-aware assistants without giving up control over sensitive relationship context;
- developers integrating relationship memory into agent runtimes.

### AI agent

An AI runtime that can:

- retrieve relationship context during interaction;
- resolve/create people and immediately store atomic profile facts, relationships, and observations;
- apply human-source corrections, retractions and reattributions with exact old record refs;
- provide evidence/provenance for submitted context;
- preserve reported/inferred basis, uncertainty, participant roles and source timing.

### Connector / importer

An optional adapter that submits bounded episode/candidate payloads. Examples:

- local chat transcript importer;
- calendar/contact importer;
- Markdown/YAML relationship-map importer;
- future macOS Messages/KakaoTalk connector.

Connectors are not core MVP behavior. They feed Kinlayer through explicit API contracts.

---

## 4. Product Principles

### P1. Agent conversation first

People, relationships, observations, recent context, and corrections should mostly accumulate through AI-agent conversations.

Manual Web/CLI entry exists, but mainly for:

- initial bootstrap seed;
- inspection;
- manual cleanup;
- correction and change-history inspection;
- retrieval debugging.

### P2. API is canonical

The HTTP API is the canonical capability layer.

```text
HTTP API = canonical capability
Web UI = human-friendly API client
CLI = ops/debug/agent-callable API client
AI agent = API client or CLI caller
```

No Web-only state-changing capability is allowed.

### P3. Correctability beats raw archive

Kinlayer is not a raw conversation archive.

MVP episodes store:

- source metadata;
- bounded excerpt;
- body hash;
- occurred_at / ingested_at;
- retention policy.

Full raw body retention is out of MVP. Reliability should come from correction, supersede, deprecate, evidence links, and retrieval updates.

### P4. Save now; correct during conversation

Registration means the memory is available to the agent. No AI-use policy or pre-save approval is
required. Source admission and schema validation still apply. `claim_basis` distinguishes reported,
inferred and unknown claims; a saved report is not an externally verified fact.

Each independently correctable claim has its own record. A common change ledger preserves
creation, correction, retraction and reattribution. Existing policy/confirmation fields are retained
only for old-client compatibility and must not gate current storage or retrieval.

### P5. Kinlayer packages context; agents reason

Kinlayer does not generate final relationship advice, message drafts, or natural-language briefings.

Kinlayer retrieves, scores, filters, labels, and packages context. The AI agent performs final interpretation and response generation.

---

## 5. MVP Product Surface

### CLI-first + Minimal Web UI

Kinlayer MVP is CLI-first with a minimal Web UI.

CLI responsibilities:

- init/migrate/status;
- raw API escape hatch;
- people/bootstrap commands;
- candidate operations;
- context/retrieval commands;
- correction apply;
- graph/debug;
- embedding status/backfill.

Web UI responsibilities:

- bootstrap person entry;
- candidate inbox;
- person detail/context card;
- evidence/provenance view;
- 1-hop ego graph;
- retrieval debug;
- settings/status.

MVP Web screens:

```text
/people
/people/new
/people/:id
/candidates
/graph
/retrieval-debug
/settings
```

---

## 6. MVP Integration Contract

MVP integration is local HTTP API + CLI wrapper.

- Backend exposes a local/Dockerized HTTP API.
- CLI wraps the same API.
- Web UI consumes the same API.
- AI agents can call HTTP directly or invoke CLI.
- MCP, Hermes plugin/tool adapters, and runtime memory hooks are later integration work.

Future integration notes are tracked in `../agents/agent-integration-notes.md` and are non-blocking for MVP implementation.

---

## 7. Technical Stack

### Backend

```text
Python 3.11+
FastAPI
SQLAlchemy 2.x
Alembic
Pydantic
Typer CLI
httpx for OpenAI-compatible embedding calls
sentence-transformers for local embeddings
```

### Database

```text
Postgres 16+
pg_trgm
pgvector
```

Postgres remains the canonical source for:

- relationship context;
- correction/provenance;
- correction and change-history inspection;
- policy control;
- fuzzy name/alias search;
- observation vector search.

Use a Docker image with pgvector available, e.g.:

```text
pgvector/pgvector:pg16
```

No separate vector database in MVP.

### Embeddings

Embedding/vector search is MVP-required, scoped narrowly to observations.

MVP embeds:

```text
observations.content
query, plus optional pack-only situation, at retrieval time
```

MVP does not embed:

```text
edges
entity_facts
candidates
episodes/full conversations
```

Supported embedding providers:

1. OpenAI-compatible embeddings.
2. Local sentence-transformers.

Local default:

```text
dragonkue/multilingual-e5-small-ko-v2
384-dim
lightweight Korean retrieval
```

Local high-quality option:

```text
nlpai-lab/KURE-v1
1024-dim
stronger Korean retrieval, heavier
```

Local provider may lazy-load in the FastAPI process for MVP. A separate embedding worker is later.

### Frontend

```text
React
Vite
TypeScript
React Flow for graph rendering
```

API returns generic graph data; React Flow shape is a frontend adapter concern.

---

## 8. Workspace, Auth, and Safety Defaults

MVP is single-user local workspace.

```text
one local Kinlayer instance
one relationship context workspace
one protected self entity
no users/sessions/login UI
```

Docker Compose network exposure:

```text
Web/API published on host ports 5173/8765 for same-LAN access
Postgres published on 127.0.0.1:15432 only
```

Optional bearer token:

```text
KINLAYER_API_TOKEN
```

If no token is configured:

```text
auth middleware disabled for local dev convenience
```

If token is configured:

- `/api/system/health` and `/api/system/version` remain public;
- all other API endpoints require a bearer API token;
- GET endpoints are protected too, because relationship context is sensitive to read.

---

## 9. Core Data Model

Full data model is specified in `data-model.md`.

Core tables/concepts:

```text
entities
entity_aliases
entity_facts
entity_edges
observations
observation_entities
episodes
candidates
candidate_evidence
entity_fact_evidence
edge_evidence
observation_evidence
ontology registry tables
```

### Protected self entity

Kinlayer initializes a protected `self` person entity.

Relationships to the user are represented as normal edges from/to this entity.

```text
self --friend--> person
self --client_contact--> person
```

Self entity:

- cannot be deleted;
- cannot be freely merged;
- is displayed as Self/You in UI.

### Entity model

Entity schema is generic, but MVP is person-first.

```text
person = first-class MVP
organization/place/event/topic/account = reserved/experimental
```

### Entity facts

Use hybrid model:

```text
entities.properties = lightweight UI metadata
entity_facts = provenance/policy/confidence-backed stable facts
```

`entity_facts.fact_type` is registry-backed. Ambiguous context stays as observations until repeated structure justifies a new fact type.

### Relationship edges

Edges model structural relationships only.

Examples:

```text
friend
family
coworker
former_coworker
client_contact
introduced_by
dating_interest
romantic_partner
matched_on_app
```

Advice, feelings, caution, strategy, and relationship patterns belong in observations, not edges.

### Observations

Observations are sentence-like context units used by agents.

Single observations table covers:

```text
stable_fact
preference
communication_preference
relationship_pattern
care_point
caution
recent_interaction
user_feeling
follow_up_context
```

Recent/stable/caution context is separated through type/status/time fields, not separate tables.

### Evidence

Use typed evidence tables:

```text
candidate_evidence
entity_fact_evidence
edge_evidence
observation_evidence
```

No polymorphic evidence_links table in MVP.

---

## 10. Immediate Memory and Correction Model

[Agent Write Contract](../agents/agent-write-instruction-pack.md) specifies the exact envelope.
`POST /api/memories` handles one atomic `create|correct|retract|reattribute` operation, with a stable
request ID, human source and typed record payload. Canonical records, Episode evidence and change
history commit together. A same-body retry is idempotent; conflicting key reuse fails.

```text
conversation reveals a useful claim → agent saves it → current retrieval includes it
user points out an error → agent identifies the old record → atomic correct/retract/reattribute
→ old row stays in history → current retrieval reflects the result
```

No replacement is required for retraction. Reattribution can move a claim to the intended person.
Keep old candidates, curation runs and reconciliation history inspectable as compatibility data;
those interfaces are not a prerequisite for new writes. The legacy candidate lifecycle remains in
`candidate-lifecycle-and-payload.md`.

## 11. Retrieval and Context Packaging

Full context output contract is specified in `context-output-contract.md` and API details in `api-spec.md`.

### Context API endpoints

```http
POST /api/context/retrieve
POST /api/context/pack
GET  /api/entities/{id}/context-card
```

Avoid `/context/situation`; it sounds like storage or LLM briefing. Use `/context/pack`.

### Request shape

Agents send:

```text
query
entity_hints
focal_entity_id optional
query_embedding optional
include_debug
limit
situation optional, context-pack only
include_provisional, context-pack only
```

`situation` is combined with `query` for context-pack retrieval. Request schemas use
`extra = forbid`: legacy fields such as `situation_text`, `retrieval_intent`, `desired_context`,
`candidate_entities`, `time_window`, `include_pending_recent`, `max_results`, and `debug` are
rejected with HTTP 422 rather than silently ignored.

Raw retrieval returns `matched_entities`, `observations`, `provenance`, `scores`, `match_reasons`,
`score_breakdown`, `ambiguity_detected`, and wrapper-level `debug`. Context pack returns
`{context_pack, debug}`; the inner pack contains `confidence`, `suggested_response_policy`,
`ambiguity_detected`, `matched_entities`, `buckets`, `recent_context`, `stable_context`, `cautions`,
`provenance`, and the separate opt-in `provisional_context`. Person context cards use the exact keys
listed in `context-output-contract.md`.

### Hybrid retrieval signals and response guidance

Retrieval combines explicit entity hints, aliases/names, semantic observation similarity, recency,
and graph proximity. Inspect current service/debug output for effective weights. Retired
AI-use-policy or confirmation flags must not suppress a current claim or reduce its score.

Returned records expose topic, basis, confidence, people/roles, known event and validity times, and
structured source provenance. Ambiguous identities still require clarification. Inactive,
superseded and retracted records belong in history rather than current context. Disputed records
remain labeled; known validity bounds are returned for interpretation.

Legacy surface bucket keys may remain in response shapes for compatibility. They do not authorize
or prohibit memory use. Kinlayer packages records; the agent writes the final answer.

---

## 12. API Scope

API is domain-grouped REST.

Groups:

```text
/api/memories
/api/system
/api/entities
/api/aliases
/api/entity-facts
/api/edges
/api/observations
/api/episodes
/api/candidates
/api/corrections
/api/context
/api/graph
/api/ontology
/api/embeddings
```

The default write endpoint is `POST /api/memories`. Retained legacy action endpoints include:

```http
POST /api/candidates/{id}/accept
POST /api/candidates/{id}/edit-accept
POST /api/candidates/{id}/reject
POST /api/candidates/{id}/archive
POST /api/candidates/{id}/needs-clarification
POST /api/candidates/{id}/supersede
POST /api/corrections/apply
```

CRUD endpoints exist for core resources, but DELETE uses safe semantics:

```text
canonical resources -> soft delete/deprecate
candidates -> archive
physical purge -> out of MVP / later admin-only
```

---

## 13. Minimal Web UI Scope

Existing screen behavior is specified in `web-ui-spec.md`. This is the compatibility UI; the
replacement is planned in `../plans/frontend-rebuild.md` and is not implemented in this change.

MVP UI optimizes for:

```text
bootstrap
review
inspect
debug
1-hop graph viewing
```

MVP graph:

```text
person-first 1-hop ego graph
generic graph API
React Flow frontend rendering
```

No full-network graph analytics in MVP.

---

## 14. CLI Scope

Detailed commands are specified in `cli-spec.md`.

MVP CLI covers:

```text
ops/status
raw API escape hatch
people bootstrap
memory apply (create/correct/retract/reattribute)
legacy candidate workflows
context/retrieval
legacy correction apply
graph/debug
embedding status/backfill
```

Advanced edits not wrapped by polished CLI commands remain reachable through:

```bash
kinlayer api METHOD /api/path --data file.json
```

---

## 15. Ontology Registry

Kinlayer uses an active ontology registry, not formal RDF/OWL in MVP.

Registry validates and drives:

```text
entity types
edge types
observation types
entity_fact types
claim basis and participant roles
legacy claim types, ai_use_policy values and candidate types
retrieval/UI filters
```

`/api/ontology` is read-only in MVP. Full ontology admin editing is later.

MVP seed values include:

- social/professional/dating structural edge types;
- observation types for stable/recent/pattern/caution context;
- profile fact types such as role, job, organization, birthday, external_handle and location_hint;
- legacy generic note types remain discoverable for compatibility but are rejected by new memory writes.

---

## 16. MVP Non-goals

MVP does not include:

- full CRM replacement;
- contacts/calendar/message ingestion as core behavior;
- macOS Messages/KakaoTalk connector implementation;
- automatic person merge without review;
- unconfirmed AI-agent person merge execution;
- graph database as canonical source;
- separate vector database;
- community detection / graph analytics;
- full-network polished graph exploration;
- SaaS multi-user/team collaboration;
- built-in login/session auth;
- full raw transcript archive;
- full ontology editor;
- full event-sourced database reconstruction (the bounded memory change ledger is in scope);
- separate embedding worker unless lazy-load proves unusable;
- Hermes plugin/tool/MCP adapter implementation.

---

## 17. Acceptance Criteria

Journey-level acceptance scenarios are specified in `acceptance-scenarios.md`.

MVP is not done until these pass in a local Docker Compose environment:

```text
A. Bootstrap seed
B. Agent conversation immediately creates canonical memory (replaces candidate-first criterion, 2026-10-01)
C. Conversation correction, retraction and reattribution with source/history
D. Ambiguous implicit person retrieval
E. Basis/source-aware retrieval (replaces AI-use-policy gating, 2026-10-01)
F. Ego graph view
G. Embedding-backed Korean semantic retrieval
H. Optional API token protection
I. Soft delete semantics
```

Minimum verification artifacts:

- migrations succeed from empty DB;
- API server starts;
- Web UI loads;
- CLI can call API;
- embedding provider can be smoke-tested;
- A-I scenarios verified.

---

## 18. Implementation Plan

The current implementation plan lives in
`../plans/save-first-memory-schema.md`, with frontend implementation deferred to
`../plans/frontend-rebuild.md`. The archived vertical-slice baseline is preserved at
`../archive/planning/implementation-plan-2026-06-27.md` for historical context
only.

Slices:

```text
0. Project scaffold
1. Core entity bootstrap
2. Edges, observations, episodes, evidence, embeddings
3. Candidates and corrections
4. Retrieval and context APIs
5. Web control plane and graph
6. Acceptance hardening
```

Each slice must leave the product runnable and verify at least one real workflow.

---

## 19. Related Specification Documents

- `../archive/planning/interview-ledger.md` — historical decision ledger.
- `ontology-design.md` — ontology registry, edge-vs-observation boundary, and seed registry values.
- `context-output-contract.md` — retrieval output layers, Context Pack, Person Context Card, recent context, basis and source contract.
- `candidate-lifecycle-and-payload.md` — candidate statuses, accept behavior, common envelope, typed payload schemas, and candidate actions.
- `data-model.md` — canonical MVP tables, status fields, evidence tables, correction implications, and retrieval implications.
- `api-spec.md` — OpenAPI-like Markdown endpoint contract.
- `cli-spec.md` — MVP CLI command set and raw API escape hatch.
- `web-ui-spec.md` — minimal Web UI screens and behavior.
- `acceptance-scenarios.md` — journey-level MVP acceptance scenarios and exit bar.
- `../plans/save-first-memory-schema.md` — current schema, agent-write and live-conversion contract.
- `../plans/frontend-rebuild.md` — frontend plan only.
- `../plans/relationship-curation-cycle.md` — superseded curation requirements and compatibility history.
- `../archive/planning/implementation-plan-2026-06-27.md` — historical vertical implementation baseline.
- `../agents/agent-integration-notes.md` — future skill/plugin/tool/MCP/runtime-hook integration notes; non-blocking for MVP.

---

## 20. Current Source of Truth

For implementation work, use this PRD together with:

```text
api-spec.md
data-model.md
../plans/save-first-memory-schema.md
acceptance-scenarios.md
```

If a conflict exists, prefer the more specific spec document and update the PRD accordingly. Historical rationale can remain in `../archive/planning/interview-ledger.md`.

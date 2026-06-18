# PRD v0.3 — Kinlayer

- Status: Draft v0.3
- Product name: Kinlayer
- Audience: Codex, Claude Code, and future implementation agents
- Last major rewrite: aligned with decision ledger through MVP API/Web/CLI/retrieval/embedding decisions

---

## 1. Product Summary

Kinlayer is a local-first relationship context layer for AI agents.

It helps AI agents accumulate, retrieve, and safely use person/relationship context while giving the user a control plane to inspect, correct, review, and constrain that context.

Kinlayer is not a generic CRM, not a social network analyzer, and not a relationship counseling app. It is agent memory infrastructure for relationship-aware workflows.

Core definition:

> Kinlayer is a correctable, policy-aware relationship memory layer for AI agents, with a lightweight human control plane.

Core product loop:

```text
User talks with an AI agent
→ agent retrieves relationship context from Kinlayer
→ agent answers using policy-labeled context
→ conversation reveals new people/relationships/observations/corrections
→ agent submits candidates or trusted explicit corrections
→ user reviews ambiguous candidates and can inspect/correct anything
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

> A local-first relationship context store and control plane for AI agents, using candidates, provenance, correction flows, policy-aware surface rules, and hybrid retrieval.

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
- submit detected people, aliases, relationships, observations, and conflicts as candidates;
- submit explicit user corrections through a trusted correction API;
- provide evidence/provenance for submitted context;
- obey surface policies returned by Kinlayer.

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
- candidate review;
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
- sensitivity / retention policy.

Full raw body retention is out of MVP. Reliability should come from correction, supersede, deprecate, evidence links, and retrieval updates.

### P4. AI use and AI surface are different

AI agents may use context internally without directly surfacing it.

Kinlayer separates:

```text
sensitivity = information sensitivity
ai_use_policy = stored default usage policy
surface_visibility = retrieval-time computed bucket
```

Surface buckets:

```text
direct_surface
conditional_surface
internal_only
blocked
```

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
- candidate review;
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
query / situation_text at retrieval time
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

## 10. Candidate and Correction Model

Full candidate lifecycle is specified in `candidate-lifecycle-and-payload.md`.

Candidate statuses:

```text
pending
accepted
edited_accepted
rejected
archived
needs_clarification
superseded
```

Candidate accept behavior:

```text
accept/edit-accept immediately writes canonical record
candidate stores canonical_record_ref as <record_type>:<uuid>
```

Canonical record refs allowed:

```text
entities:<uuid>
entity_aliases:<uuid>
entity_facts:<uuid>
entity_edges:<uuid>
observations:<uuid>
```

Explicit user correction flow:

```text
user explicitly corrects agent in conversation
→ agent calls /api/corrections/apply
→ old canonical record superseded/deprecated
→ new canonical record active
→ correction episode/evidence stored
→ retrieval updates immediately
```

Agent-inferred corrections/conflicts must go through candidate review.

---

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
situation_text
retrieval_intent
desired_context
candidate_entities
focal_entity_id optional
time_window
include_pending_recent
max_results
debug
```

`situation_text` is the semantic embedding target / normalized situation description.

`situation_tags`, if present, are optional weak hints only. Specific situation understanding should not depend on enum tags.

### Hybrid retrieval signals

Initial score weights are MVP constants:

```text
entity_hint_score: 0.25
alias_name_score: 0.20
semantic_observation_score: 0.20
recency_score: 0.15
graph_proximity_score: 0.10
confirmation_policy_score: 0.10
```

Penalties include:

```text
ambiguity
sensitivity/surface constraints
stale/deprecated status
policy blocks
```

These weights are not assumed optimal. They should be tuned after dogfood/evaluation. Debug output must expose score breakdown.

### Confidence and response policy

Base thresholds:

```text
high >= 0.75
medium >= 0.45
low < 0.45
```

Ambiguity guard prevents/downgrades high confidence when:

- top1-top2 score gap is small;
- reference resolution confidence is low;
- focal_entity_id is absent with pronoun/implicit reference;
- policy/sensitivity conflicts exist.

Suggested response policy is based on confidence + surface buckets:

```text
no_relevant_context
blocked_by_policy
natural_use
conditional_use
ask_clarifying_question
```

Kinlayer gives policy labels; the AI agent writes the final answer.

---

## 12. API Scope

API is domain-grouped REST.

Groups:

```text
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

Use explicit workflow action endpoints where side effects matter:

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

Detailed screen behavior is specified in `web-ui-spec.md`.

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
candidate workflows
context/retrieval
correction apply
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
claim types
sensitivity values
ai_use_policy values
candidate types
retrieval/UI filters
```

`/api/ontology` is read-only in MVP. Full ontology admin editing is later.

MVP seed values include:

- social/professional/dating structural edge types;
- observation types for stable/recent/pattern/caution context;
- entity_fact types such as role, job, organization, birthday, contact_note, relationship_note, important_context, external_handle, location_hint.

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
- event-sourced audit trail;
- separate embedding worker unless lazy-load proves unusable;
- Hermes plugin/tool/MCP adapter implementation.

---

## 17. Acceptance Criteria

Journey-level acceptance scenarios are specified in `acceptance-scenarios.md`.

MVP is not done until these pass in a local Docker Compose environment:

```text
A. Bootstrap seed
B. Agent conversation creates candidate
C. Explicit correction direct apply
D. Ambiguous implicit person retrieval
E. Policy-aware surface
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

Implementation is vertical-slice based, specified in `../../implementation-plan.md`.

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
- `context-output-contract.md` — retrieval output layers, Context Pack, Person Context Card, recent context, and surface policy contract.
- `candidate-lifecycle-and-payload.md` — candidate statuses, accept behavior, common envelope, typed payload schemas, and candidate actions.
- `data-model.md` — canonical MVP tables, status fields, evidence tables, correction implications, and retrieval implications.
- `api-spec.md` — OpenAPI-like Markdown endpoint contract.
- `cli-spec.md` — MVP CLI command set and raw API escape hatch.
- `web-ui-spec.md` — minimal Web UI screens and behavior.
- `acceptance-scenarios.md` — journey-level MVP acceptance scenarios and exit bar.
- `../../implementation-plan.md` — vertical implementation slices and execution baseline.
- `../agents/agent-integration-notes.md` — future skill/plugin/tool/MCP/runtime-hook integration notes; non-blocking for MVP.

---

## 20. Current Source of Truth

For implementation work, use this PRD together with:

```text
api-spec.md
data-model.md
../../implementation-plan.md
acceptance-scenarios.md
```

If a conflict exists, prefer the more specific spec document and update the PRD accordingly. Historical rationale can remain in `../archive/planning/interview-ledger.md`.

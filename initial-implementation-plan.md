# Kinlayer Implementation Plan

- Status: Draft v0.1
- Parent PRD: `prd.md`
- Related docs: `api-spec.md`, `data-model.md`, `cli-spec.md`, `web-ui-spec.md`, `acceptance-scenarios.md`

---

## 1. Principle

Implement Kinlayer as vertical slices, not as isolated layers.

Each slice should leave the product in a runnable state and verify at least one real workflow.

Avoid building all schemas, then all APIs, then all UI without exercising end-to-end behavior.

---

## Slice 0 — Project Scaffold

### Goal

A local developer can start the app stack and see health checks pass.

### Scope

- repo structure;
- Docker Compose;
- Postgres with pgvector and pg_trgm;
- FastAPI app;
- Alembic setup;
- SQLAlchemy/Pydantic base;
- Typer CLI skeleton;
- React/Vite/TypeScript Web UI skeleton;
- config file + env override loader;
- optional API token middleware;
- system health/version/config endpoints.

### Verification

- `docker compose up` starts Postgres/API/Web.
- `GET /api/system/health` returns ok.
- `kinlayer status` works.
- Alembic can run empty initial migration.

---

## Slice 1 — Core Entity Bootstrap

### Goal

The user can bootstrap people and basic profile data.

### Scope

- protected self entity creation on init;
- entities table/API;
- aliases table/API;
- entity_facts table/API;
- registry-backed fact types;
- people CLI commands;
- `/people`, `/people/new`, basic `/people/:id`.

### Verification

- Self entity exists and cannot be deleted.
- User can create person with alias and entity_fact.
- Person appears in CLI and Web UI.
- Person detail loads from API.

Acceptance coverage:

- Scenario A partial.

---

## Slice 2 — Edges, Observations, Episodes, Evidence, Embeddings

### Goal

Kinlayer can store relationship structure and agent-usable observations with provenance and embeddings.

### Scope

- entity_edges table/API;
- observations table/API;
- observation_entities join table;
- episodes table/API;
- typed evidence tables:
  - candidate_evidence later in Slice 3;
  - entity_fact_evidence;
  - edge_evidence;
  - observation_evidence;
- embedding provider abstraction;
- OpenAI-compatible embedding provider;
- local sentence-transformers provider;
- default local model `dragonkue/multilingual-e5-small-ko-v2`;
- HQ local option `nlpai-lab/KURE-v1`;
- sync-first embedding generation;
- embedding_status/backfill/status;
- CLI embedding commands.

### Verification

- User can create edge and observation.
- Observation embedding becomes ready with configured provider.
- If embedding fails, observation is still saved as pending/failed.
- `kinlayer embedding status` works.
- `kinlayer embedding backfill` processes pending rows.

Acceptance coverage:

- Scenario A complete.
- Scenario G partial.

---

## Slice 3 — Candidates and Corrections

### Goal

AI agents can submit candidates, users can review them, and explicit corrections can directly update canonical context.

### Scope

- candidates table/API;
- candidate_evidence table;
- typed candidate payload validation;
- candidate action endpoints:
  - accept;
  - edit-accept;
  - reject;
  - archive;
  - needs-clarification;
  - supersede;
- candidate CLI commands;
- `/candidates` Web UI;
- correction apply endpoint;
- supersede/deprecate canonical behavior;
- soft delete semantics for core resources.

### Verification

- Agent can submit observation candidate with evidence.
- Candidate appears in Web/CLI inbox.
- Accept creates canonical observation and stores canonical_record_ref.
- Edit-accept creates canonical record from edited payload.
- Explicit correction supersedes old edge and creates new active edge.
- Soft delete removes records from default retrieval but does not purge rows.

Acceptance coverage:

- Scenario B.
- Scenario C.
- Scenario I.

---

## Slice 4 — Retrieval and Context APIs

### Goal

Kinlayer can retrieve and package relationship context for AI agents.

### Scope

- pg_trgm name/alias fuzzy matching;
- pgvector semantic observation search;
- hybrid scoring constants;
- score breakdowns;
- confidence thresholds + ambiguity guard;
- surface bucket computation;
- suggested_response_policy mapping;
- `POST /api/context/retrieve`;
- `POST /api/context/pack`;
- `GET /api/entities/{id}/context-card`;
- CLI retrieval/context commands;
- `/retrieval-debug` Web UI.

### Verification

- Name/alias query finds correct person.
- Korean semantic query finds relevant observation without exact keyword overlap.
- Ambiguous implicit-person request returns medium/low or conditional/clarifying policy.
- `never_surface` context does not appear in direct_surface.
- Debug output shows score breakdown and semantic metadata.

Acceptance coverage:

- Scenario D.
- Scenario E.
- Scenario G complete.

---

## Slice 5 — Web Control Plane and Graph

### Goal

The Web UI supports bootstrap, review, inspection, graph viewing, settings, and debug workflows.

### Scope

- complete `/people/:id` sections;
- evidence/provenance panel;
- candidate inbox refinements;
- generic ego graph API;
- React Flow adapter;
- `/graph` view;
- `/settings` view;
- API token-aware Web client config;
- embedding status display.

### Verification

- Person detail shows aliases, facts, edges, observations, context card, evidence.
- Candidate actions work from Web UI.
- Graph shows 1-hop ego network and node/edge detail panels.
- Settings shows health, embedding provider/model/dim, ontology read-only values.

Acceptance coverage:

- Scenario F.
- Scenario H partial.

---

## Slice 6 — Acceptance Hardening

### Goal

The MVP passes documented scenarios in a local Docker Compose environment.

### Scope

- scenario fixtures/seed data;
- smoke scripts;
- API tests;
- CLI smoke tests;
- Web sanity tests if feasible;
- docs cleanup;
- README runbook;
- final consistency pass against PRD/spec files.

### Verification

- Acceptance scenarios A-I pass.
- Fresh clone can run migrations and start stack.
- CLI can call local API.
- Web UI loads and uses API.
- Embedding provider smoke test succeeds.
- Optional token mode behaves correctly.

---

## 2. Explicit Non-goals During MVP Implementation

Do not spend MVP time on:

- multi-user auth;
- workspace membership;
- full raw conversation archive;
- macOS Messages/Kakao connector implementation;
- full ontology editor;
- community detection/graph analytics;
- separate embedding worker unless FastAPI lazy-load proves unusable;
- formal OpenAPI YAML before Pydantic models stabilize;
- Hermes plugin/tool/MCP adapter implementation.

---

## 3. Handoff Rule

A slice is not complete until it is verified with real commands/API calls, not just code written.

Every slice should update docs if implementation changes the agreed contract.

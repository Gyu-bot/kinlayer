# Kinlayer Implementation Handoff

- Status: Active implementation handoff
- Product: Kinlayer
- Audience: Codex, Claude Code, and future coding agents
- Primary source of truth: this file plus the referenced specification documents in this directory

---

## 0. How to Use This Handoff as a Prompt

When giving this to a coding agent, prepend one short task-scope instruction, then paste this whole file.

Example:

```text
Implement Kinlayer Slice 0 only. Do not implement future slices.
Read and follow the handoff below exactly. After implementation, run the documented verification commands and report the real results.

[PASTE handoff.md]
```

For later work, change only the first scope line:

```text
Implement Kinlayer Slice 1 only.
[PASTE handoff.md]
```

or:

```text
Implement only the /api/context/pack endpoint from Slice 4. Do not touch Web UI.
[PASTE handoff.md]
```

The scope line wins over any broader roadmap language in this document.

---

## 1. Project Identity

Kinlayer is a local-first relationship context layer for AI agents.

It helps AI agents accumulate, retrieve, and safely use person/relationship context while giving the user a control plane to inspect, correct, review, and constrain that context.

Core definition:

```text
Kinlayer is a correctable, policy-aware relationship memory layer for AI agents, with a lightweight human control plane.
```

Core product loop:

```text
User talks with an AI agent
→ agent retrieves relationship context from Kinlayer
→ agent answers using policy-labeled context
→ conversation reveals new people/relationships/observations/corrections
→ agent submits candidates or trusted explicit corrections
→ user reviews ambiguous candidates and can inspect/correct anything
```

Kinlayer is not:

- a generic CRM;
- a social network analytics platform;
- a raw conversation archive;
- a relationship counseling app;
- a multi-user SaaS product in MVP.

---

## 2. Repository / Workspace

Current planning workspace:

```text
/Users/gyurin/dev/kinlayer/
```

If an implementation repository already exists, work there. If not, create the implementation files in this project directory or in a clearly named repository directory chosen by the user.

Do not overwrite specification documents unless the implementation reveals a real contract change. If contract changes are needed, update the relevant spec file in the same commit/diff.

---

## 3. Source-of-Truth Documents

Read these before implementing a slice:

```text
prd.md                         Product definition and principles
implementation-plan.md          Slice order and verification expectations
data-model.md                   Postgres schema, enums, records, relationships
api-spec.md                     HTTP API contract
cli-spec.md                     Typer CLI contract
web-ui-spec.md                  Minimal Web UI/control plane behavior
context-output-contract.md      Retrieval/context pack output contract
candidate-lifecycle-and-payload.md Candidate lifecycle and typed payload rules
acceptance-scenarios.md         End-to-end acceptance scenarios
agent-integration-notes.md      Future agent integration notes; not MVP plugin work
interview-ledger.md             Decision ledger; use when resolving ambiguity
```

Priority when documents appear to conflict:

1. `prd.md` for product principles.
2. `implementation-plan.md` for current slice scope.
3. `api-spec.md`, `data-model.md`, `cli-spec.md`, `web-ui-spec.md` for implementation contracts.
4. `interview-ledger.md` for design rationale and ambiguity resolution.

If a conflict remains, do not silently choose a direction. Make the smallest reasonable implementation choice, document it in the final report, and update the relevant spec if the change is clearly necessary.

---

## 4. Non-Negotiable Product Constraints

### 4.1 Local-first, single-user MVP

MVP assumes one local Kinlayer instance owns one relationship context workspace.

Do not add full multi-user auth, accounts, organizations, workspace membership, billing, or cloud sync.

Optional API token mode is allowed:

```text
KINLAYER_API_TOKEN configured     → Bearer token required for relationship data endpoints
KINLAYER_API_TOKEN not configured → auth disabled
```

Health/version endpoints remain public.

### 4.2 API is canonical

The HTTP API is the canonical capability layer.

```text
HTTP API = canonical capability
Web UI   = human-friendly API client
CLI      = ops/debug/agent-callable API client
AI agent = API client or CLI caller
```

No state-changing capability may exist only in the Web UI.

### 4.3 Agent conversation first

People, relationships, observations, recent context, and corrections should primarily accumulate through AI-agent conversations.

Manual Web/CLI entry exists mostly for:

- initial bootstrap;
- inspection;
- manual cleanup;
- candidate review;
- retrieval debugging.

### 4.4 Correctability beats raw archive

Kinlayer is not a raw conversation archive.

MVP episodes store:

- source metadata;
- bounded excerpt;
- body hash;
- occurred_at / ingested_at;
- sensitivity / retention policy.

Full raw conversation body retention is out of MVP.

Reliability comes from:

- correction;
- supersede;
- deprecate;
- evidence links;
- retrieval updates.

### 4.5 Candidate vs trusted correction

AI-inferred context must not become trusted canonical context automatically.

Default AI-detected people, aliases, relationships, observations, conflicts, and uncertain corrections go through candidate review.

But explicit user correction during an AI-agent conversation is trusted input and should directly update canonical context through the correction apply API.

Rule:

```text
User explicitly corrects the agent/context → direct apply, no extra UI review
Agent infers a correction/conflict by itself → candidate review
```

Example explicit correction:

```text
"아니, 그 사람은 직장 동료가 아니라 거래처 사람이야."
```

Expected behavior:

```text
old edge/status → deprecated or superseded
new corrected edge → active
retrieval immediately reflects corrected context
```

### 4.6 Policy-aware retrieval and surface

Kinlayer separates:

```text
sensitivity        = information sensitivity
ai_use_policy      = stored default usage policy
surface_visibility = retrieval-time computed bucket
```

Surface buckets:

```text
direct_surface
conditional_surface
internal_only
blocked
```

Agents may use some context internally without directly surfacing it.

`never_surface` or blocked context must not appear in direct user-facing agent phrasing.

### 4.7 Kinlayer packages context; agents reason

Kinlayer does not generate final relationship advice, message drafts, or natural-language briefings.

Kinlayer returns structured Context Packs with evidence, confidence, score breakdowns, and policy labels.

The AI agent does final reasoning, tone, and natural-language response generation.

---

## 5. Technical Stack

Use the agreed stack unless there is a strong implementation blocker:

```text
Backend: FastAPI
DB: Postgres
Extensions: pgvector, pg_trgm
ORM/Migrations: SQLAlchemy + Alembic
API schemas: Pydantic
CLI: Typer
Web UI: React + Vite + TypeScript
Graph UI: React Flow
Deployment: Docker Compose, local-first
Embeddings: local sentence-transformers by default, OpenAI-compatible option supported
```

Default local embedding model:

```text
dragonkue/multilingual-e5-small-ko-v2
```

High-quality optional model:

```text
nlpai-lab/KURE-v1
```

MVP semantic retrieval is required, not merely a later nice-to-have. Keep embedding generation sync-first with failure/backfill support unless this proves unusable.

---

## 6. Implementation Order

Implement vertical slices. Do not build a huge isolated layer without exercising end-to-end behavior.

### Slice 0 — Project Scaffold

Goal: local developer can start the stack and see health checks pass.

Scope:

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

Verification:

- `docker compose up` starts Postgres/API/Web.
- `GET /api/system/health` returns ok.
- `kinlayer status` works.
- Alembic can run empty initial migration.

### Slice 1 — Core Entity Bootstrap

Goal: user can bootstrap people and basic profile data.

Scope:

- protected self entity creation on init;
- entities table/API;
- aliases table/API;
- entity_facts table/API;
- registry-backed fact types;
- people CLI commands;
- `/people`, `/people/new`, basic `/people/:id`.

Verification:

- Self entity exists and cannot be deleted.
- User can create person with alias and entity_fact.
- Person appears in CLI and Web UI.
- Person detail loads from API.

### Slice 2 — Edges, Observations, Episodes, Evidence, Embeddings

Goal: Kinlayer can store relationship structure and agent-usable observations with provenance and embeddings.

Scope:

- entity_edges table/API;
- observations table/API;
- observation_entities join table;
- episodes table/API;
- typed evidence tables;
- embedding provider abstraction;
- local and OpenAI-compatible embedding providers;
- embedding status/backfill.

Verification:

- User can create edge and observation.
- Observation embedding becomes ready with configured provider.
- If embedding fails, observation is still saved as pending/failed.
- `kinlayer embedding status` works.
- `kinlayer embedding backfill` processes pending rows.

### Slice 3 — Candidates and Corrections

Goal: AI agents can submit candidates, users can review them, and explicit corrections can directly update canonical context.

Scope:

- candidates table/API;
- candidate_evidence table;
- typed candidate payload validation;
- candidate action endpoints;
- candidate CLI commands;
- `/candidates` Web UI;
- correction apply endpoint;
- supersede/deprecate canonical behavior;
- soft delete semantics for core resources.

Verification:

- Agent can submit observation candidate with evidence.
- Candidate appears in Web/CLI inbox.
- Accept creates canonical observation and stores canonical_record_ref.
- Edit-accept creates canonical record from edited payload.
- Explicit correction supersedes old edge and creates new active edge.
- Soft delete removes records from default retrieval but does not purge rows.

### Slice 4 — Retrieval and Context APIs

Goal: Kinlayer can retrieve and package relationship context for AI agents.

Scope:

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

Verification:

- Name/alias query finds correct person.
- Korean semantic query finds relevant observation without exact keyword overlap.
- Ambiguous implicit-person request returns medium/low or conditional/clarifying policy.
- `never_surface` context does not appear in direct_surface.
- Debug output shows score breakdown and semantic metadata.

### Slice 5 — Web Control Plane and Graph

Goal: Web UI supports bootstrap, review, inspection, graph viewing, settings, and debug workflows.

Scope:

- complete `/people/:id` sections;
- evidence/provenance panel;
- candidate inbox refinements;
- generic ego graph API;
- React Flow adapter;
- `/graph` view;
- `/settings` view;
- API token-aware Web client config;
- embedding status display.

Verification:

- Person detail shows aliases, facts, edges, observations, context card, evidence.
- Candidate actions work from Web UI.
- Graph shows 1-hop ego network and node/edge detail panels.
- Settings shows health, embedding provider/model/dim, ontology read-only values.

### Slice 6 — Acceptance Hardening

Goal: MVP passes documented scenarios in local Docker Compose.

Scope:

- scenario fixtures/seed data;
- smoke scripts;
- API tests;
- CLI smoke tests;
- Web sanity tests if feasible;
- docs cleanup;
- README runbook;
- final consistency pass against PRD/spec files.

Verification:

- Acceptance scenarios A-I pass.
- Fresh clone can run migrations and start stack.
- CLI can call local API.
- Web UI loads and uses API.
- Embedding provider smoke test succeeds.
- Optional token mode behaves correctly.

---

## 7. Current Recommended First Task

Unless the user gives a different scope, start with Slice 0 only.

Do not implement entities, candidates, retrieval, graph UI, or embeddings during Slice 0 except for placeholders needed to keep the app structure clean.

Slice 0 should produce a runnable scaffold, not a fake product.

Expected Slice 0 deliverables:

```text
backend FastAPI app
Postgres Docker service with pgvector and pg_trgm available
Alembic initialized
Typer CLI with status command
React/Vite app shell
config/env loader
optional token middleware skeleton
system health/version/config endpoints
README/run commands if missing
```

Expected Slice 0 verification commands should include equivalents of:

```bash
docker compose up -d
curl http://localhost:<api-port>/api/system/health
kinlayer status
alembic upgrade head
```

Use actual project commands if names/ports differ.

---

## 8. Hard Non-goals During MVP Implementation

Do not spend MVP time on:

- multi-user auth;
- workspace membership;
- cloud sync;
- billing;
- full raw conversation archive;
- macOS Messages/Kakao connector implementation;
- complete contact/calendar import;
- full ontology editor;
- community detection or graph analytics;
- RDF/OWL formal ontology;
- Neo4j/Kuzu canonical database;
- separate embedding worker unless FastAPI lazy-load proves unusable;
- formal OpenAPI YAML before Pydantic models stabilize;
- Hermes plugin/tool/MCP adapter implementation.

---

## 9. Data Model Guardrails

Follow `data-model.md`.

Important guardrails:

- MVP is person-first, but schema is entity-generic.
- A protected `self` entity must exist after initialization:
  - `entity_type = person`
  - `system_role = self`
  - `is_system = true`
- The self entity cannot be deleted.
- Use soft delete/deprecate/supersede semantics, not physical deletion, for relationship records.
- Keep edges and observations separate:
  - edges = structural relationship facts;
  - observations = agent-usable sentence/context units.
- Store provenance through episodes and evidence tables.
- Do not store full raw conversation bodies in MVP.

---

## 10. API Guardrails

Follow `api-spec.md`.

Important guardrails:

- API paths are under `/api/...`.
- Health/version endpoints are public.
- Optional Bearer token protects relationship data endpoints when configured.
- Common error shape:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Human-readable error message",
    "details": {}
  }
}
```

- DELETE means soft delete/archive semantics in MVP.
- Context APIs retrieve/package context; they do not generate final advice.
- Use `/api/context/retrieve` for raw retrieval.
- Use `/api/context/pack` for agent-facing packaged context.

---

## 11. CLI Guardrails

Follow `cli-spec.md`.

The CLI is primarily for ops, debugging, bootstrap, and agent-callable workflows.

Do not make CLI behavior diverge from API behavior. CLI should call or mirror API contracts.

Important expected commands over time include:

```text
kinlayer status
kinlayer person ...
kinlayer candidate ...
kinlayer context retrieve ...
kinlayer context pack ...
kinlayer embedding status
kinlayer embedding backfill
```

Slice 0 only needs the CLI skeleton and `kinlayer status`.

---

## 12. Web UI Guardrails

Follow `web-ui-spec.md`.

The Web UI is a control plane, not the primary agent experience.

Prioritize:

- bootstrap;
- candidate review;
- person/context inspection;
- provenance visibility;
- retrieval debugging;
- 1-hop graph viewing.

Do not overbuild a CRM UI.

---

## 13. Context Pack Guardrails

Follow `context-output-contract.md`.

Context Pack is the preferred term.

Avoid old terms unless explaining migration from older drafts:

```text
Situation Context Bundle
Situation Briefing Bundle
```

Kinlayer packages context. The AI agent reasons and writes final natural language.

Context output must preserve:

- matched entities;
- observations/facts/edges;
- confidence;
- score breakdowns where relevant;
- provenance references;
- policy/surface buckets;
- suggested response policy.

---

## 14. Candidate and Correction Guardrails

Follow `candidate-lifecycle-and-payload.md`.

Candidate statuses include:

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
accept candidate → write canonical record immediately → store canonical_record_ref
edit-accept → validate edited payload → write canonical record → store canonical_record_ref
```

Evidence uses join tables, not only array fields.

Explicit user correction flow is direct apply, not candidate review.

Agent-inferred correction flow is candidate review.

---

## 15. Verification Discipline

A slice is not complete until it is verified with real commands/API calls.

Do not report success based only on code written.

For every implementation task, final report must include:

```text
1. What changed
2. Files changed
3. Commands run
4. Actual command output summary
5. Any failing checks or blockers
6. Any spec deviations or doc updates
7. Recommended next slice/task
```

If tests cannot be run, say exactly why and what was attempted.

Never fabricate command output.

---

## 16. Expected Coding-Agent Behavior

The coding agent should:

1. Read this handoff and the relevant source-of-truth docs.
2. Inspect the existing repository/workspace before creating files.
3. Implement only the user-specified slice or task scope.
4. Keep the app runnable after each slice.
5. Prefer simple, explicit code over premature abstraction.
6. Add tests or smoke scripts appropriate to the slice.
7. Run real verification commands.
8. Report actual results and blockers.

The coding agent should not:

- implement future slices without instruction;
- silently change product contracts;
- replace local-first design with SaaS assumptions;
- add full auth/multi-user systems;
- store raw conversation archives;
- treat AI-inferred candidates as automatically confirmed;
- generate final relationship advice inside Kinlayer;
- skip verification.

---

## 17. Final Report Template

Use this final report shape after each coding-agent run:

```markdown
## Summary
- ...

## Files Changed
- `path`: reason

## Verification
- `command`: result
- `command`: result

## Notes / Deviations
- ...

## Next Recommended Task
- ...
```

If there are blockers:

```markdown
## Blockers
- What failed
- Exact error/output
- What was tried
- What decision/input is needed
```

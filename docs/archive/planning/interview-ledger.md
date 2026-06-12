# Kinlayer Interview Ledger

- Status: Active interview loop
- Goal: Clarify Kinlayer until Codex / Claude Code can begin implementation without guessing.
- Update cadence: Every 2–3 interview turns, update `prd.md` and this ledger.

## Fixed Decisions

1. Product name: **Kinlayer**.
2. Product framing: local-first relationship context layer for AI agents.
3. Core actors: user, AI agent, optional connector/import source.
4. PRD language must be generic/open-source: avoid project-specific personal names except in dogfood/reference sections.
5. AI agents may create detected person/relationship/observation candidates; user control determines what becomes trusted and what can be surfaced.
6. MVP priority: candidate/control loop + provenance + retrieval/context cards before broad message ingestion or pretty graph views.
7. MVP product surface: **CLI-first + minimal Web UI**.
   - CLI owns init, migration, import, retrieval/debug, and candidate operations.
   - Minimal Web UI owns candidate review, person detail, context card inspection, and provenance/evidence view.
   - Full graph and polished CRM-style UI are not first-slice priorities.
8. MVP data entry scope: **manual entry + AI-generated candidate API**.
   - Users can create/edit relationship context directly.
   - AI agents can submit detected person, alias, relationship, observation, conflict, or merge candidates.
   - AI-submitted information defaults to candidate status and must include confidence/provenance.
   - Relationship-map import is useful later but not required for the first core loop.
9. MVP agent integration contract: **local HTTP API + CLI wrapper**.
   - Docker/local server exposes the canonical HTTP API.
   - CLI wraps the same API for init, migration, candidate submission/review, retrieval, and debug workflows.
   - Web UI also uses the same API.
   - MCP is a later adapter, not core MVP infrastructure.
10. Initial creation ownership nuance:
   - User and AI agent can both create/register people, relationships, and some stable fields.
   - Episodes/provenance-like records are expected to be primarily AI-agent/connector registered, not manually authored as the normal path.
   - This needs a later dedicated clarification pass.
11. MVP technical stack: **FastAPI + Postgres(pg_trgm, pgvector) + Alembic + SQLAlchemy/Pydantic + Typer + React/Vite + Docker Compose**.
   - Postgres remains the canonical source for correction, provenance, candidate review, policy control, fuzzy search, and vector search.
   - Use `pg_trgm` from day one for name/alias fuzzy match.
   - Use `pgvector` from day one for semantic observation retrieval.
   - Embedding layer supports OpenAI-compatible embeddings via HTTP client and local sentence-transformers.
   - Local default embedding model: `dragonkue/multilingual-e5-small-ko-v2`; local high-quality option: `nlpai-lab/KURE-v1`.
   - Use `pgvector/pgvector:pg16` or equivalent Postgres image with pgvector available in Docker Compose.
   - Local sentence-transformers provider may lazy-load inside the FastAPI process in MVP; separate embedding worker is later.
   - Graph view can be served through API projections to React Flow.
   - Ontology registry starts as active DB-backed validation/filtering, not RDF/OWL.
12. Canonical model: **entity-generic schema, person-first MVP behavior**.
   - `person` is fully supported in MVP.
   - organization/place/event/topic/account are reserved or experimental, not first-class MVP workflows.
13. Ontology approach: **active ontology registry**, not formal RDF/OWL in MVP.
   - Registry validates entity types, edge types, claim types, candidate types, policy values, and retrieval/UI filters.
   - Formal ontology export/reasoning is later optional.
14. Context output contract: **Raw Retrieval Result + Person Context Card + Context Pack**.
   - Kinlayer packages policy-labeled context; the AI agent performs final reasoning and response composition.
   - Recent context includes confirmed context plus policy-safe pending candidates.
   - Pending recent context can only be conditional, never stated as confirmed fact.
15. Candidate lifecycle: **practical MVP lifecycle**.
   - Statuses: `pending`, `accepted`, `edited_accepted`, `rejected`, `archived`, `needs_clarification`, `superseded`.
   - Candidate event/history table is later, not MVP.
   - MVP candidates should still track `resolved_at`, `resolved_by`, `resolution_note`, and `canonical_record_ref`.
16. Candidate accept behavior: **accept immediately writes canonical records**.
   - Accepting one candidate immediately creates/updates the corresponding canonical table row.
   - Candidate stores the resulting `canonical_record_ref`.
   - Batch review / changeset apply is later, not MVP.
17. Candidate payload contract: **common envelope + typed payload schemas**.
   - DB stores candidate `payload` as JSONB.
   - API/Pydantic layer validates payload by `candidate_type`.
   - This keeps storage flexible while making agent submissions and canonical writes predictable.
   - Avoid fully untyped payloads and avoid separate candidate tables in MVP.
18. Candidate evidence model: **`candidate_evidence` join table**.
   - Avoid `candidates.evidence_episode_ids` arrays as the canonical model.
   - Evidence rows should store candidate_id, episode_id, excerpt, confidence, and created_at.
   - This keeps candidate/edge/observation provenance consistent.
19. Episode retention policy: **metadata/excerpt/hash only in MVP; no full raw archive**.
   - Kinlayer is a correctable relationship memory layer, not a raw conversation archive.
   - MVP episodes store source metadata, bounded excerpts, body hashes, occurred_at, ingested_at, sensitivity, and retention policy.
   - `full_body` retention is out of MVP and may be added later only as explicit adapter-level opt-in.
   - Strong correction/supersede/deprecate flows are more important than storing full raw source text.
20. Correction flow: **agent-conversation-first correction, with explicit user correction as trusted direct apply**.
   - Primary correction path is conversation with an AI agent, not manual UI editing.
   - If the user explicitly corrects the agent in conversation, the agent may submit a trusted correction apply request that immediately supersedes/deprecates the old canonical record.
   - If the agent merely infers a possible correction/conflict, it must create a review candidate.
   - Explicit correction should still create an episode/excerpt/hash and correction provenance, but should not force an extra inbox review step.
   - UI/CLI direct edits are secondary/supporting paths for initial seed, inspection, and occasional manual cleanup.
21. Primary usage path: **agent conversation is the main product loop**.
   - People, relationships, observations, recent context, and corrections should accumulate mostly through AI-agent conversations.
   - UI is primarily a control/inspection/review plane, not the main daily data-entry interface.
   - Manual UI/CLI entry exists for initial seeding and auxiliary correction.
   - Minimal Web UI must still include manual bootstrap data entry for known people/relationships because users need a practical way to seed their graph without forcing everything through conversation.
22. Minimal Web UI includes an MVP ego graph view.
   - Graph view is not the core success metric, but it is included as a product/UX affordance.
   - Scope must stay narrow: person-first 1-hop ego graph, relation/status/sensitivity filters, click node/edge for detail panel.
   - No advanced graph analytics, community detection, or polished full-network visualization in MVP.
23. MVP API scope: **screen/agent-loop explicit API surface**.
   - Define endpoints for health/config, entities/people, aliases, edges, observations, episodes, candidates, correction apply, retrieval/context, and ego graph.
   - Do not stop at minimal CRUD + retrieve because Web UI and agent loop need explicit contracts.
   - Full OpenAPI-like `api-spec.md` is written near handoff after core model, CLI, UI, retrieval, and acceptance scenarios are clarified.
24. Capability ownership: **HTTP API is canonical; Web UI and CLI are clients**.
   - No Web-only state-changing capability.
   - AI agents, CLI, and Web UI should all rely on the same HTTP API.
   - Web UI is a human-friendly control/inspection/review/bootstrap client.
25. MVP CLI scope: **ops + agent/debug core CLI + raw API/JSON escape hatch**.
   - CLI wraps setup/status, basic seed, candidate handling, retrieval/context, correction apply, graph/debug.
   - CLI does not need polished flags for every advanced edit in MVP.
   - `kinlayer api` or equivalent raw JSON passthrough should provide access to any API capability not wrapped by a first-class command.
26. Minimal Web UI scope: **bootstrap + review + inspect + 1-hop graph**.
   - Screens: `/people`, `/people/new`, `/people/:id`, `/candidates`, `/graph`, `/retrieval-debug`, `/settings`.
   - UI supports manual bootstrap entry for people/aliases/basic relationships/observations.
   - Candidate inbox supports accept/edit-accept/reject/archive/needs-clarification review.
   - Graph is person-first 1-hop ego graph with narrow filters and detail panels.
   - Ontology/settings are read-only or basic defaults in MVP; no full ontology admin UI.
   - No standalone episodes/imports/connectors/audit admin screens in MVP.
27. MVP retrieval strategy: **hybrid architecture with required embedding/vector search over observations**.
   - Day-one required: exact alias/name match, pg_trgm fuzzy match, recent entity mention, status filtering, sensitivity/policy filtering, recency scoring, basic edge proximity, and semantic observation search.
   - Embed `observations.content` and retrieval-time `query`/`situation_text`; use pgvector similarity as `semantic_observation_score` in hybrid ranking.
   - Supported MVP embedding providers: OpenAI-compatible embeddings and local sentence-transformers.
   - Local default model: `dragonkue/multilingual-e5-small-ko-v2` (lightweight Korean retrieval, 384-dim). Local high-quality option: `nlpai-lab/KURE-v1` (stronger Korean retrieval, 1024-dim, heavier).
   - Only observations are embedded in MVP; exclude edges, entity_facts, candidates, and full episodes from embedding scope.
   - Avoid vector-only retrieval; relationship context needs name/alias/recency/graph/policy signals.
28. Retrieval confidence contract: **numeric score + confidence band + suggested response policy**.
   - Return numeric score plus `high|medium|low` confidence band.
   - Return suggested response policy: `natural_use`, `conditional_use`, `ask_clarifying_question`, `no_relevant_context`, `blocked_by_policy`.
   - Kinlayer should not author the final agent response, but it should provide policy labels for consistent agent behavior.
29. Policy model: **stored sensitivity/use policy + retrieval-time surface visibility**.
   - Store `sensitivity`: `low`, `medium`, `high`.
   - Store `ai_use_policy`: `freely_use`, `cautious_use`, `ask_before_use`, `never_surface`.
   - Compute retrieval-time buckets: `direct_surface`, `conditional_surface`, `internal_only`, `blocked`.
   - Purpose is not to stop AI use, but to distinguish internal judgment from direct user-facing mention.
30. Self model: **protected `self` person entity**.
   - Kinlayer initializes a special `person` entity with `system_role = self` or equivalent.
   - Relationships to the owner are represented as normal edges: `self --relation_type--> other_person`.
   - UI/API must prevent deletion of the protected self entity.
   - Future multi-user can add one protected self/person entity per user/workspace owner instead of changing the edge model.
31. MVP workspace/auth scope: **single-user local workspace, no built-in auth**.
   - One local Kinlayer instance owns one relationship context workspace.
   - No login/user account/workspace membership in MVP.
   - No `workspace_id` on every table for MVP unless implementation needs an internal constant later.
   - Local exposure should be safe by default: bind to localhost unless explicitly configured otherwise.
   - Future multi-user/multi-workspace is later and should not complicate first-slice data model.
32. Observation model: **single observations table with type/status/time fields**.
   - Use one observations table for stable facts, preferences, patterns, cautions, recent interactions, user feelings, and follow-up context.
   - Distinguish behavior with `observation_type`, `status`, `valid_from`, `valid_to`, `occurred_at`, and recency scoring fields.
   - Retrieval output buckets observations into stable_context vs recent_context at query time.
   - Repeated recent interactions can later produce pattern observations through candidate flow.
33. Entity profile fields: **`entities.properties` for lightweight UI metadata + `entity_facts` for provenance/policy/confidence-backed stable info**.
   - `entities.properties` stores display-oriented lightweight metadata such as UI tags, colors, short notes, and non-critical presentation fields.
   - `entity_facts` stores relationship-relevant stable facts that need claim_type, confidence, sensitivity, ai_use_policy, status, and evidence.
   - `profile_field` candidates should usually canonicalize into `entity_facts`, not opaque JSON properties.
34. Evidence model: **typed evidence tables for core context records**.
   - Use `candidate_evidence`, `observation_evidence`, `edge_evidence`, and `entity_fact_evidence`.
   - Avoid a polymorphic `evidence_links` table in MVP because FK integrity matters and Codex implementation should stay explicit.
   - Evidence links are needed because Kinlayer does not store full raw conversation archives; bounded excerpts and episode links provide explainability.
35. Observation related entities: **use `observation_entities` join table**.
   - Keep `observations.subject_entity_id` as the primary subject FK.
   - Remove `observations.related_entity_ids` array shortcut.
   - Add `observation_entities(observation_id, entity_id, role, confidence, created_at)` for related/mentioned/speaker/target links.
   - Avoid duplicate array + join-table state.
36. Ontology seed values: **MVP structural seed set plus narrow dating relationship edge types**.
   - Edge types include structural/professional/social relations plus dating-specific structural states.
   - Use dating edge types like `dating_interest`, `dating`, `former_dating`, `romantic_partner`, `former_partner`, `introduced_for_dating`, `matched_on_app`.
   - Avoid advisory/emotional dating concepts as edges; keep them as observations.
37. Entity fact types: **registry-backed seed/config values in MVP**.
   - `entity_facts.fact_type` must use allowed seed/config values, not arbitrary free text.
   - Initial values: `role`, `job`, `organization`, `birthday`, `contact_note`, `relationship_note`, `important_context`, `external_handle`, `location_hint`.
   - Ambiguous context should go to observations first; promote/add fact types later only when repeated structure justifies it.
   - MVP does not need full Web UI ontology editing for fact types.
38. Canonical record references: **string ref format `<record_type>:<uuid>` in MVP**.
   - Allowed record types: `entities`, `entity_aliases`, `entity_facts`, `entity_edges`, `observations`.
   - This keeps candidate resolution simple and flexible.
   - API may parse/return structured `{record_type, id}` helpers, but DB stores the string ref.
39. MVP indexes/constraints: **core retrieval/control-loop indexes + essential constraints**.
   - Add primary keys, foreign keys, status/type/time indexes, trgm indexes for entity/alias search, and uniqueness for protected self entity.
   - Use registry/Pydantic validation for controlled values; DB-level enum/check constraints are preferred but not required everywhere in MVP.
   - Avoid overbuilding strict DB constraints that make registry evolution painful.
40. MVP CLI command set: **ops + raw API escape hatch + people bootstrap + candidates + context/retrieval + correction + graph/debug**.
   - Use command set documented in `cli-spec.md`.
   - First-class CLI commands cover core local/agent/debug workflows.
   - Advanced unwrapped API capabilities stay reachable through `kinlayer api`.
41. API namespace: **domain-grouped REST**.
   - Groups: `/api/system`, `/api/entities`, `/api/aliases`, `/api/entity-facts`, `/api/edges`, `/api/observations`, `/api/episodes`, `/api/candidates`, `/api/corrections`, `/api/context`, `/api/graph`, `/api/ontology`.
   - Use REST resources plus explicit action endpoints where needed, e.g. `/api/candidates/{id}/accept`, `/api/corrections/apply`, `/api/context/pack`.
   - `/api/ontology` is read-only/seed registry lookup in MVP; editing is later.
42. API CRUD scope: **full CRUD endpoints for core resources, with safe delete semantics**.
   - Core resources should expose create/list/get/patch/delete-style endpoints for consistency and implementation clarity.
   - Because Kinlayer is a memory/correction system, DELETE should be specified carefully: default to soft delete/deprecate for canonical context unless an explicit hard-delete/admin path is later added.
   - Retrieval must exclude deleted/deprecated records by default.
43. DELETE semantics: **soft delete by default; hard purge later/admin-only**.
   - `DELETE` endpoints set canonical records to `deleted`/deprecated-equivalent state and remove them from default retrieval; rows remain for references/history.
   - For temporal records such as edges/observations, set `valid_to = now` where applicable.
   - Protected self entity deletion returns 403.
   - `DELETE /api/candidates/{id}` maps to archive semantics in MVP rather than adding a separate `deleted` candidate lifecycle state.
   - True physical purge is out of MVP and may become explicit admin/internal tooling later.
44. Candidate API actions: **explicit workflow action endpoints**.
   - Use `POST /api/candidates/{id}/accept`, `/edit-accept`, `/reject`, `/archive`, `/needs-clarification`, and `/supersede`.
   - Do not model candidate resolution as a simple status PATCH because accept/edit-accept have canonical-write side effects.
   - Action endpoints map directly to CLI/Web UI workflows and make OpenAPI behavior clearer.
45. Context API request shape: **query + situation_text + structured hints**.
   - Use `query` for original user text and `situation_text` as the semantic embedding target / normalized situation description.
   - Agents should send `retrieval_intent`, `desired_context`, `candidate_entities`, optional `focal_entity_id`, `time_window`, `include_pending_recent`, `max_results`, and `debug`.
   - `situation_tags` may exist only as optional weak hints, not as the main situation understanding mechanism.
   - Endpoint names: `POST /api/context/retrieve`, `POST /api/context/pack`, `GET /api/entities/{id}/context-card`; avoid `/context/situation` because it sounds like storage or LLM briefing.
46. Context API response shape: **retrieve = low-level scored retrieval, pack = agent-facing policy buckets**.
   - `/api/context/retrieve` returns matched entities/observations with scores, score breakdowns, semantic/debug metadata, and retrieval diagnostics.
   - `/api/context/pack` returns `context_pack` with matched entities, confidence, suggested_response_policy, `direct_surface`, `conditional_surface`, `internal_only`, `blocked`, recent/stable context, cautions, provenance, and optional debug.
   - `/api/context/pack` must not author final natural-language advice or briefing; final reasoning remains the AI agent's job.
47. Person Context Card: **agent/UI shared curated card, not full dossier**.
   - `GET /api/entities/{id}/context-card` returns entity, aliases, profile_facts, relationship_edges, stable_context, recent_context, communication_context, cautions, provenance_summary, and retrieval_hints.
   - Each context item should include content, claim_type, confidence, sensitivity, ai_use_policy, computed surface_visibility, and source episode/evidence references.
   - Apply sensible default limits rather than dumping all records; full lists use paginated resource endpoints.
48. Graph API response: **generic ego graph, not React Flow-specific API format**.
   - `GET /api/graph/ego/{entity_id}` returns neutral nodes/edges with entity ids, edge ids, relation types, status, sensitivity, confidence, direction, and filters applied.
   - MVP officially supports person-first `depth=1`; depth 2 may be later/experimental.
   - Web UI may render the generic response with React Flow, but React Flow node/edge shape is a frontend adapter concern.
49. Web UI screen behavior: **screen-level MVP behavior is specified in `web-ui-spec.md`**.
   - Screens: `/people`, `/people/new`, `/people/:id`, `/candidates`, `/graph`, `/retrieval-debug`, `/settings`.
   - UI optimizes for bootstrap, review, inspect, debug, and 1-hop graph viewing.
   - No Web-only state-changing capability; Web UI uses canonical HTTP API.
50. Retrieval scoring formula: **code constants in MVP, with debug breakdown exposed**.
   - Initial weights: entity_hint 0.25, alias_name 0.20, semantic_observation 0.20, recency 0.15, graph_proximity 0.10, confirmation_policy 0.10.
   - Apply penalties for ambiguity, sensitivity/surface constraints, stale/deprecated status, and policy blocks.
   - Do not make scoring runtime-configurable in MVP; keep it deterministic and testable.
   - These initial weights are not assumed optimal; dogfood/evaluation should tune them after MVP.
   - `/api/context/retrieve` and `/retrieval-debug` must expose score breakdowns for later tuning.
51. Confidence band thresholds: **thresholds plus ambiguity guard**.
   - Base thresholds: `high >= 0.75`, `medium >= 0.45`, `low < 0.45`.
   - Downgrade/prevent `high` when top1-top2 score gap is too small, reference_resolution confidence is low, focal_entity_id is absent with pronoun/implicit reference, or policy/sensitivity conflicts exist.
   - This prevents Kinlayer from overconfidently resolving the wrong person/context.
52. Suggested response policy mapping: **confidence + surface bucket based**.
   - No matched entity/context -> `no_relevant_context`.
   - All relevant context blocked -> `blocked_by_policy`.
   - High confidence with direct_surface -> `natural_use`.
   - Medium confidence or only conditional_surface -> `conditional_use`.
   - Low confidence or ambiguity guard triggered -> `ask_clarifying_question`.
   - If only internal_only context exists, agent may use it for reasoning but must not directly surface it.
53. Embedding generation: **sync first, fallback to pending/backfill**.
   - On observation create/update, try to generate embedding synchronously.
   - If embedding succeeds, save embedding and mark ready.
   - If embedding fails or times out, save the observation anyway with `embedding_status=pending` or `failed`; lexical/structured retrieval still works.
   - Add fields: `embedding_status`, `embedding_error`, `embedding_model`, `embedding_dim`, `embedding_created_at`.
   - Provide backfill/status operations for embeddings in CLI/API.
54. Embedding/provider configuration: **config file + env override**.
   - Use local config for non-secret settings such as provider, model, dim, timeout, and batch size.
   - Support env overrides for Docker/deployment: `KINLAYER_EMBEDDING_PROVIDER`, `KINLAYER_EMBEDDING_MODEL`, `KINLAYER_EMBEDDING_DIM`, `KINLAYER_EMBEDDING_BASE_URL`, `KINLAYER_EMBEDDING_API_KEY`.
   - API keys/secrets should be env-first, not stored in config by default.
   - Settings UI/CLI status should display active provider/model/dim without exposing secrets.
55. API access protection: **no login/auth, optional local bearer API token**.
   - MVP has no users, sessions, or login UI.
   - Server binds to `127.0.0.1` by default.
   - If `KINLAYER_API_TOKEN` is configured, write endpoints and sensitive read endpoints require a bearer API token.
   - CLI/Web UI may pass the token from config/env; settings must not expose token value.
   - This is a minimal local-first safety boundary, not multi-user auth.
56. API token protection scope: **health/version public, all other API endpoints token-protected when token is configured**.
   - If no `KINLAYER_API_TOKEN` is configured, auth middleware is disabled for local dev convenience.
   - If configured, only basic system health/version endpoints remain public.
   - Relationship data reads/writes, context retrieval, graph, candidates, corrections, episodes, and ontology endpoints require bearer token.
   - GET endpoints are protected too because relationship context is sensitive to read, not only to write.
57. MVP acceptance scenarios: **journey-level user/agent scenarios plus technical checks**.
   - Use `acceptance-scenarios.md` as the MVP exit-bar document.
   - Scenarios cover bootstrap seed, agent candidate creation, explicit correction, ambiguous retrieval, policy-aware surface, ego graph, Korean semantic retrieval, optional API token protection, and soft delete semantics.
   - Expected JSON/fixture-level assertions should be added after `api-spec.md` is finalized.
58. API spec format: **OpenAPI-like Markdown first, optional formal YAML later**.
   - Use `api-spec.md` as the implementation-facing endpoint contract.
   - Each endpoint should include purpose, auth, request, response, side effects, errors, and acceptance notes.
   - Generate or hand-write `openapi.yaml` later only after FastAPI/Pydantic models stabilize.
59. Implementation slicing: **vertical slices documented in `implementation-plan.md`**.
   - Use slices 0-6: scaffold, entity bootstrap, edges/observations/evidence/embeddings, candidates/corrections, retrieval/context, Web+graph, acceptance hardening.
   - Each slice must leave the product runnable and verify at least one real workflow.
   - Avoid layer-first implementation that delays end-to-end validation.
60. PRD v0.3 rewrite: **completed and aligned with current spec documents**.
   - `prd.md` now reflects Kinlayer naming, open-source/generic actors, agent-conversation-first loop, API canonicality, embedding-required retrieval, context pack naming, local workspace/auth/token defaults, MVP scope/non-goals, acceptance scenarios, and vertical implementation slices.
   - Specific spec docs remain the detailed source for API/data/CLI/Web/acceptance/implementation contracts.

## Working Product Thesis

Kinlayer is a local-first relationship context layer for AI agents. It helps agents store, review, retrieve, and explain person/relationship context while keeping users in control of what is trusted, retrieved, and surfaced.

## Current Open Decisions

Most MVP product/API/data/retrieval/Web/CLI decisions are now closed through PRD v0.3 and companion specs.

Remaining handoff work:

1. Final consistency check after any further edits.
2. Optional fixture-level expected JSON examples for `acceptance-scenarios.md` after implementation begins.
3. Optional formal `openapi.yaml` after FastAPI/Pydantic models stabilize.
4. Repository/bootstrap handoff prompt for Codex/Claude Code.

## Next Question

Decide whether to create a concise `handoff.md` / implementation prompt for Codex/Claude Code now, or continue tightening individual specs.

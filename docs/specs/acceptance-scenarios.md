# Kinlayer MVP Acceptance Scenarios

- Status: Draft v0.1
- Parent PRD: `prd.md`
- Related docs: `data-model.md`, `context-output-contract.md`, `candidate-lifecycle-and-payload.md`, `cli-spec.md`, `web-ui-spec.md`, `../agents/agent-write-instruction-pack.md`

---

## 1. Purpose

This document defines journey-level MVP acceptance scenarios for Kinlayer.

These scenarios are not exhaustive unit tests. They describe the minimum end-to-end behavior that must work before the MVP can be considered usable by a user and AI agent.

Fixture-level assertions are covered by the acceptance smoke scripts in `scripts/`.

---

## Scenario A — Bootstrap Seed

### Goal

A user can manually seed a person and basic relationship context through Web UI or CLI, and Kinlayer can retrieve it.

### Steps

1. Create a person entity.
2. Add one alias.
3. Add one relationship edge from protected self entity to the person.
4. Add one initial observation.
5. Open person context card.
6. Run context retrieval for a query mentioning the person/alias.

### Pass Criteria

- Person is visible in `/people` or `kinlayer person list`.
- Alias appears on person detail/context card.
- Edge appears in relationship section and graph response.
- Observation appears in context card.
- Retrieval returns the person as a top matched entity.
- Context pack includes the observation in an appropriate surface bucket.

---

## Scenario B — Agent Conversation Creates Candidate

### Goal

An AI agent can submit relationship context as a candidate with provenance, and user review promotes it to canonical context.

### Steps

1. Agent creates an episode with bounded excerpt/hash.
2. Agent submits an observation candidate referencing that episode.
3. Candidate appears in candidate inbox.
4. User accepts candidate.
5. Kinlayer writes canonical observation.
6. Retrieval/context card includes accepted observation.

### Pass Criteria

- Candidate status starts as `pending`.
- Candidate evidence links to episode/excerpt.
- Accept endpoint creates canonical observation.
- Candidate stores `canonical_record_ref`.
- Accepted observation has evidence/provenance.
- Retrieval excludes pending candidate as confirmed fact before accept.
- Retrieval includes accepted observation after accept.

---

## Scenario C — Explicit Correction Direct Apply

### Goal

A user explicitly correcting the AI agent in conversation updates canonical context without an extra inbox review.

### Setup

Existing edge:

```text
self --former_coworker--> Alex
```

### Steps

1. User says to AI agent: "No, Alex is not a former coworker; Alex is a client contact."
2. Agent calls correction apply API with explicit user correction evidence.
3. Kinlayer creates correction episode/provenance.
4. Old edge is superseded/deprecated.
5. New edge is active.
6. Context card/retrieval reflect the new relationship.

### Pass Criteria

- No candidate inbox approval is required for explicit user correction.
- Old edge is excluded from default retrieval.
- New edge is active and visible.
- Correction provenance points to bounded excerpt/hash.
- Graph response uses the updated edge.

---

## Scenario D — Ambiguous Implicit Person Retrieval

### Goal

Kinlayer supports agent-assisted retrieval for ambiguous references without overconfidently guessing.

### Steps

1. Agent sends context request with:
   - `query` containing an implicit reference such as "that person";
   - optional `entity_hints`;
   - no confirmed `focal_entity_id`.
2. Kinlayer performs hybrid retrieval.
3. Kinlayer applies ambiguity guard.
4. Kinlayer returns context pack.

### Pass Criteria

- Matched entities include scores and match reasons.
- If ambiguity is high, confidence is not `high` even if raw score is strong.
- Suggested response policy is `conditional_use` or `ask_clarifying_question`.
- Agent-facing pack does not force a false confirmed identity.

---

## Scenario E — Policy-Aware Surface

### Goal

Sensitive or restricted context can be retrieved for internal use without being directly surfaced.

### Steps

1. Create observation with `ai_use_policy = never_surface` or high sensitivity.
2. Run context retrieval/pack for a semantically relevant query.
3. Inspect context buckets.

### Pass Criteria

- Observation may be matched internally if policy allows retrieval.
- Observation is not placed in `direct_surface`.
- It appears in `internal_only` or `blocked` according to policy.
- Suggested response policy respects the restricted context.
- Debug/provenance still explains why it was considered.

---

## Scenario F — Ego Graph View

### Goal

Kinlayer exposes a person-first 1-hop ego graph and Web UI can render it.

### Steps

1. Ensure protected self entity exists.
2. Create two person entities.
3. Create edges from self to both people.
4. Call `GET /api/graph/ego/{self_id}`.
5. Open `/graph` and select self.

### Pass Criteria

- Graph API returns generic nodes/edges.
- Focal self node is marked `is_focal`.
- Both people appear as 1-hop nodes.
- Edges include relation type, direction, status, confidence.
- Web UI renders graph through React Flow adapter.
- Node/edge click opens detail panel.

---

## Scenario G — Embedding-Backed Korean Semantic Retrieval

### Goal

Kinlayer uses embeddings to retrieve semantically relevant Korean observations even when exact keywords differ.

### Steps

1. Configure embedding provider:
   - OpenAI-compatible provider, or
   - local sentence-transformers model `dragonkue/multilingual-e5-small-ko-v2`.
2. Create an observation with nuanced Korean content.
3. Ensure embedding status becomes `ready` or backfill succeeds.
4. Query with semantically similar Korean `query` text using different wording.
5. Inspect retrieval result/debug.

### Pass Criteria

- Observation has embedding metadata.
- Debug output includes retrieval score weights and thresholds.
- `semantic_observation` contributes to `score_breakdown` when embeddings are available.
- Relevant observation is returned despite weak exact keyword overlap.
- Hybrid scoring still respects entity hints, policy, status, and recency.

---

## Scenario H — Optional API Token Protection

### Goal

Optional local bearer token protects relationship data endpoints when configured.

### Steps

1. Start Kinlayer with `KINLAYER_API_TOKEN` set.
2. Call `/api/system/health` without token.
3. Call `/api/entities` without token.
4. Call `/api/entities` with correct bearer token.

### Pass Criteria

- Health/version endpoint works without token.
- Relationship data endpoint returns 401 without token.
- Same endpoint succeeds with valid token.
- Settings/CLI status never displays token value.

---

## Scenario I — Soft Delete Semantics

### Goal

DELETE endpoints remove records from default retrieval without breaking provenance/history.

### Steps

1. Create observation with evidence.
2. Confirm it appears in context card/retrieval.
3. Call DELETE for the observation.
4. Query context again.
5. Inspect record directly if include-deleted/debug mode exists.

### Pass Criteria

- Observation row is not physically purged in MVP.
- Status becomes deleted/deprecated-equivalent.
- `valid_to` is set where applicable.
- Default retrieval excludes it.
- Evidence/provenance references remain intact.

---

## Scenario J — Agent Write Instruction Pack Boundary

### Goal

An AI agent follows the write instruction pack and does not submit schema-polluting relationship types.

### Steps

1. Agent receives a user-authored statement such as "Minji is my former coworker."
2. Agent fetches ontology edge types and confirms `former_coworker` is active for the endpoint entity types.
3. Agent creates an episode with bounded user-authored excerpt/hash.
4. Agent submits a `relationship_edge` candidate using canonical `relation_type: "former_coworker"`.
5. Agent receives a second user-authored statement such as "Minji prefers short replies."
6. Agent does not submit `relation_type: "prefers_short_replies"` or any other invented edge type.
7. Agent submits an `observation` candidate only if an active observation type supports it; otherwise it produces no write or asks for clarification.
8. Agent receives a pronoun-only statement such as "그 사람이 또 연락했어" and does not create or update an entity without a reliable current-turn user-provided identifier.
9. Agent sees a public figure, fictional character, hypothetical example, generic profession, AI bot/model, or the protected self used as an ordinary person entity and produces no Kinlayer write.
10. Agent records dry-run/audit diagnostics with found mentions, exclusions, entity-resolution results, planned candidates, no-op reasons, and redacted metadata when the adapter supports diagnostics.

### Pass Criteria

- Relationship candidate uses an active ontology edge type.
- UI relationship type, API `relation_type`, candidate `relationship_edge.relation_type`, and graph label semantics are consistent.
- Observation-like statements do not become relationship edges.
- Invalid or missing edge types are rejected before canonical persistence.
- Evidence uses bounded user-authored excerpts, not assistant/tool/retrieval output.
- Assistant messages, tool output, retrieved context, system/developer/skill prompts, logs, compacted summaries, and previous memory output are not accepted as write evidence.
- Agent-side extraction thresholds are treated as adapter configuration, not Kinlayer core behavior.

---

## Scenario K — Post-Turn Agent Write Flow

### Goal

After a user turn, an AI agent can choose between entity resolution, candidate submission, direct
explicit correction, clarification, and no-write outcomes without polluting canonical memory.

### Steps

1. User says: `민지한테 답장 뭐라 하지?`
2. Agent calls entity resolve for `민지`; a single existing person match allows retrieval and any
   newly inferred context becomes a candidate, not a direct canonical write.
3. User says: `그 사람이 또 연락했어`
4. Agent treats the pronoun-only reference as no-op or `needs_clarification` unless current-turn
   evidence unambiguously identifies one person.
5. User says: `Alex는 직장 동료가 아니라 사촌이야`
6. Agent applies correction directly only when `Alex` and exactly one old canonical record are
   unambiguous; otherwise it asks for clarification or submits a review candidate.
7. User mentions a public figure/news subject, fictional/example character, or generic group.
8. Agent produces no Kinlayer candidate for those no-write subjects.

### Pass Criteria

- Entity resolve returns matched entity IDs, scores, match reasons, and an ambiguity label.
- Agent-submitted candidates include current-turn user-authored evidence and episode provenance.
- Pronoun-only ambiguity never creates a new person.
- Direct correction apply records `source_actor = user` and submitter identity separately.
- Rejected, ambiguous, or no-write outcomes do not surface as trusted confirmed context in retrieve
  or pack responses.
- Acceptance API/CLI smoke scripts exercise resolve, candidate submit/list/show, accept, reject,
  clarify, correction apply, corrected retrieval, and provenance inspection.

---

## Scenario L — Duplicate Person Merge

### Goal

Duplicate AI-created person records can be detected, reviewed, merged into one canonical target,
and then treated as a single active person by retrieval, context cards, and graph views.

### Steps

1. Fixture data contains two active people for the same real person, with overlapping aliases and
   at least one conflicting profile fact.
2. Duplicate detection runs for the source person and recommends a merge candidate for the target.
3. Reviewer inspects source and target summaries side by side in CLI or Web, including aliases,
   facts, relationships, observations, evidence, and risk notes.
4. Reviewer explicitly confirms the target and accepts the merge candidate.
5. Source aliases, facts, edges, observations, and provenance-safe context move to the target.
6. Source person becomes `merged` and stores `properties.merged_entity_ref = entities:<target>`.
7. Target remains active and canonical.
8. Retrieval, context-card, and graph responses surface the target as canonical and do not show the
   source as a separate active person.
9. Protected-self, missing-target, same-source-target, and ambiguous multi-target attempts reject or
   remain clarification/review flows.

### Pass Criteria

- `POST /api/entities/duplicate-candidates` finds the fixture pair by alias overlap.
- Accepting the merge candidate returns `canonical_record_ref = entities:<target>`.
- Direct source inspection shows `status = merged`, `confirmation_status = merged`, and the target
  merge reference.
- Default people lists hide the merged source; the source remains inspectable by direct ID or merged
  status filtering.
- API and CLI smoke scripts verify duplicate detection, merge accept, target context continuity,
  retrieval canonicalization, graph continuity, and no active duplicate source node.
- Web smoke verifies side-by-side merge review, risk acknowledgement, target confirmation, and
  post-merge people/context behavior.

---

## MVP Exit Bar

The MVP is not done until scenarios A through L pass in a local Docker Compose environment.

Minimum verification artifacts:

- migration succeeds from empty DB;
- API server starts;
- Web UI loads;
- CLI can call API;
- embedding provider can be smoke-tested;
- `python3 scripts/load-acceptance-fixtures.py` creates protected self, fixture people including a duplicate merge pair, aliases, facts, edges, observations, episodes, evidence, one pending candidate, one accepted candidate, and one correction;
- `python3 scripts/smoke-acceptance-api.py` verifies API scenarios including entity resolve, duplicate detection, merge candidate acceptance, canonical evidence linkage, explicit correction provenance, corrected context pack behavior, policy buckets, graph, ontology, embeddings, and optional token boundary when `KINLAYER_API_TOKEN` is set;
- `scripts/smoke-acceptance-cli.sh` verifies CLI status, people, entity resolve, duplicate detection, merge candidate show/accept, candidate submit/list/show/accept/reject/clarify, correction, context/retrieval, graph/debug, and embedding workflows.
- scenarios A-L are manually or automatically verified.

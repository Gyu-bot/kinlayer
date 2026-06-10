# Kinlayer MVP Acceptance Scenarios

- Status: Draft v0.1
- Parent PRD: `prd.md`
- Related docs: `data-model.md`, `context-output-contract.md`, `candidate-lifecycle-and-payload.md`, `cli-spec.md`, `web-ui-spec.md`

---

## 1. Purpose

This document defines journey-level MVP acceptance scenarios for Kinlayer.

These scenarios are not exhaustive unit tests. They describe the minimum end-to-end behavior that must work before the MVP can be considered usable by a user and AI agent.

Expected JSON examples and fixture-level assertions should be added after `api-spec.md` is finalized.

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
   - `situation_text`;
   - `candidate_entities` with confidence;
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
4. Query with semantically similar Korean `situation_text` using different wording.
5. Inspect retrieval result/debug.

### Pass Criteria

- Observation has embedding metadata.
- `semantic_enabled = true` in debug output.
- `semantic_observation_score` contributes to final score.
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

## MVP Exit Bar

The MVP is not done until scenarios A through I pass in a local Docker Compose environment.

Minimum verification artifacts:

- migration succeeds from empty DB;
- API server starts;
- Web UI loads;
- CLI can call API;
- embedding provider can be smoke-tested;
- scenarios A-I are manually or automatically verified.

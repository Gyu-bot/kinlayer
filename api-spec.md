# Kinlayer API Specification

- Status: Draft v0.1
- Style: OpenAPI-like Markdown
- Parent PRD: `prd.md`
- Related docs: `data-model.md`, `context-output-contract.md`, `candidate-lifecycle-and-payload.md`, `acceptance-scenarios.md`

---

## 1. API Principles

Kinlayer's HTTP API is the canonical capability layer.

Clients:

- AI agents;
- CLI;
- Web UI;
- future plugins/tools/MCP adapters.

Rules:

- No Web-only state-changing capability.
- No built-in user login/session auth in MVP.
- Optional bearer token protects all relationship data endpoints when configured.
- Health/version remain public.
- DELETE means soft delete/archive semantics in MVP, not physical purge.
- Context APIs retrieve/package context; they do not write final advice or natural-language briefings.

---

## 2. Auth

### Optional token mode

If `KINLAYER_API_TOKEN` is not configured:

```text
auth disabled
```

If configured:

```http
Bearer API token required
```

is required for all endpoints except:

```http
GET /api/system/health
GET /api/system/version
```

Missing/invalid token:

```http
401 Unauthorized
```

---

## 3. Common Error Shape

```json
{
  "error": {
    "code": "validation_error",
    "message": "Human-readable error message",
    "details": {}
  }
}
```

Common codes:

```text
validation_error
not_found
unauthorized
forbidden
conflict
policy_blocked
embedding_unavailable
internal_error
```

---

## 4. System

### `GET /api/system/health`

Purpose: public health/readiness endpoint.

Response:

```json
{
  "status": "ok",
  "database": "ok",
  "embedding": "ready|pending|disabled|error"
}
```

### `GET /api/system/version`

Purpose: public version endpoint.

Response:

```json
{
  "name": "kinlayer",
  "version": "0.1.0",
  "api_version": "v1"
}
```

### `GET /api/system/config`

Purpose: protected, non-secret effective config summary.

Response:

```json
{
  "bind_host": "127.0.0.1",
  "auth_token_configured": true,
  "embedding": {
    "provider": "local_sentence_transformers",
    "model": "dragonkue/multilingual-e5-small-ko-v2",
    "dim": 384,
    "status": "ready"
  }
}
```

---

## 5. Entities / People

### `POST /api/entities`

Purpose: create an entity. MVP first-class workflow is `person`.

Request:

```json
{
  "entity_type": "person",
  "display_name": "Alex",
  "canonical_name": "alex",
  "properties": {
    "short_note": "Met through work"
  },
  "confirmation_status": "confirmed",
  "sensitivity": "medium",
  "ai_use_policy": "cautious_use",
  "created_by": "user"
}
```

Response: entity object.

Side effects:

- Creates row in `entities`.
- If this is system self entity creation during init, marks protected system role.

Errors:

- `validation_error` for invalid entity_type/policy.
- `conflict` for duplicate protected self entity.

### `GET /api/entities`

Purpose: list/search entities.

Query params:

```text
q
entity_type
status
sensitivity
limit
offset
```

Response:

```json
{
  "items": [],
  "limit": 50,
  "offset": 0,
  "total": 1
}
```

### `GET /api/entities/{id}`

Purpose: get one entity.

Response: entity object.

### `PATCH /api/entities/{id}`

Purpose: update entity lightweight metadata/policies.

Request: partial entity fields.

Protected self constraints:

- Cannot remove system role.
- Cannot soft-delete via patch.

### `DELETE /api/entities/{id}`

Purpose: soft delete entity.

Semantics:

- Protected self entity returns 403.
- Normal entity becomes deleted/deprecated-equivalent.
- Default retrieval excludes it.

---

## 6. Aliases

### `POST /api/entities/{id}/aliases`

Request:

```json
{
  "alias": "알렉스",
  "status": "confirmed",
  "confidence": 1.0,
  "created_by": "user"
}
```

Response: alias object.

### `GET /api/entities/{id}/aliases`

Response:

```json
{"items": []}
```

### `PATCH /api/aliases/{id}`

Purpose: edit alias/status/confidence.

### `DELETE /api/aliases/{id}`

Purpose: soft delete/deprecate alias.

---

## 7. Entity Facts

### `POST /api/entity-facts`

Purpose: create provenance/policy-backed stable profile field.

Request:

```json
{
  "entity_id": "uuid",
  "fact_type": "organization",
  "content": "Example Corp",
  "claim_type": "fact",
  "confidence": 0.95,
  "sensitivity": "low",
  "ai_use_policy": "freely_use",
  "status": "active",
  "created_by": "user",
  "source_candidate_id": null
}
```

Response: entity_fact object.

Validation:

- `fact_type` must be registry-backed seed/config value.
- Ambiguous contextual notes should be observations, not entity_facts.

### `GET /api/entity-facts`

Query params:

```text
entity_id
fact_type
status
limit
offset
```

### `GET /api/entity-facts/{id}`

### `PATCH /api/entity-facts/{id}`

### `DELETE /api/entity-facts/{id}`

Soft delete semantics.

---

## 8. Edges

### `POST /api/edges`

Request:

```json
{
  "from_entity_id": "uuid",
  "to_entity_id": "uuid",
  "relation_type": "client_contact",
  "directed": true,
  "claim_text": "Alex is a client contact.",
  "claim_type": "fact",
  "properties": {},
  "confidence": 0.95,
  "status": "active",
  "valid_from": "2026-06-10T00:00:00Z",
  "sensitivity": "medium",
  "ai_use_policy": "cautious_use",
  "created_by": "user"
}
```

Response: edge object.

Validation:

- `relation_type` must be allowed edge type.
- Edge represents structural relationship, not advice/feeling/pattern.

### `GET /api/edges`

Query params:

```text
entity_id
from_entity_id
to_entity_id
relation_type
status
limit
offset
```

### `GET /api/edges/{id}`

### `PATCH /api/edges/{id}`

### `DELETE /api/edges/{id}`

Soft delete semantics:

- Set status deleted/deprecated-equivalent.
- Set `valid_to = now` where applicable.

---

## 9. Observations

### `POST /api/observations`

Purpose: create agent-usable contextual memory.

Request:

```json
{
  "subject_entity_id": "uuid",
  "related_entities": [
    {"entity_id": "uuid", "role": "related", "confidence": 0.9}
  ],
  "observation_type": "recent_interaction",
  "content": "Alex contacted the user again and the user felt unsure how to respond.",
  "claim_type": "fact",
  "confidence": 0.86,
  "sensitivity": "medium",
  "ai_use_policy": "cautious_use",
  "status": "active",
  "valid_from": null,
  "valid_to": null,
  "occurred_at": "2026-06-10T00:00:00Z",
  "recency_weight": 0.9,
  "created_by": "ai_agent",
  "source_candidate_id": null
}
```

Response: observation object with embedding metadata.

Side effects:

- Writes `observations`.
- Writes `observation_entities` join rows.
- Attempts synchronous embedding generation.
- If embedding fails/timeouts, saves observation with `embedding_status=pending|failed`.

### `GET /api/observations`

Query params:

```text
subject_entity_id
related_entity_id
observation_type
status
claim_type
limit
offset
```

### `GET /api/observations/{id}`

### `PATCH /api/observations/{id}`

Side effects:

- If `content` changes, mark embedding stale/pending and regenerate sync-first.

### `DELETE /api/observations/{id}`

Soft delete semantics; set `valid_to = now` where applicable.

---

## 10. Episodes

### `POST /api/episodes`

Purpose: create provenance unit; not raw archive.

Request:

```json
{
  "source_type": "agent_conversation",
  "source_ref": "discord-thread:...",
  "source_description": "Agent conversation excerpt",
  "body_excerpt": "No, Alex is a client contact.",
  "body_hash": "sha256:...",
  "actor": "user",
  "occurred_at": "2026-06-10T00:00:00Z",
  "sensitivity": "medium",
  "retention_policy": "excerpt_only"
}
```

Response: episode object.

### `GET /api/episodes/{id}`

Returns metadata/excerpt/hash only. Full raw body is out of MVP.

### `GET /api/episodes`

Query params:

```text
source_type
actor
limit
offset
```

---

## 11. Candidates

### `POST /api/candidates`

Purpose: AI/connector/import submits reviewable candidate.

Request:

```json
{
  "candidate_type": "observation",
  "target_entity_id": "uuid",
  "payload": {},
  "confidence": 0.86,
  "sensitivity": "medium",
  "suggested_action": "accept",
  "created_by": "ai_agent",
  "evidence": [
    {
      "episode_id": "uuid",
      "excerpt": "...",
      "confidence": 0.9
    }
  ]
}
```

Response: candidate object.

Validation:

- `payload` validated by `candidate_type` using typed schemas.
- Evidence writes to `candidate_evidence` join table.

### `GET /api/candidates`

Query params:

```text
status
candidate_type
target_entity_id
sensitivity
limit
offset
```

### `GET /api/candidates/{id}`

### `PATCH /api/candidates/{id}`

Purpose: edit metadata only; do not resolve candidate through generic patch.

### `DELETE /api/candidates/{id}`

Semantics: archive candidate.

### `POST /api/candidates/{id}/accept`

Purpose: accept candidate and immediately write canonical record.

Response:

```json
{
  "candidate": {},
  "canonical_record_ref": "observations:uuid"
}
```

### `POST /api/candidates/{id}/edit-accept`

Request:

```json
{
  "payload": {},
  "resolution_note": "Edited wording before accepting."
}
```

Semantics:

- Validate edited payload.
- Write canonical record using edited payload.
- Mark candidate `edited_accepted`.

### `POST /api/candidates/{id}/reject`

Request:

```json
{"resolution_note": "Incorrect person."}
```

### `POST /api/candidates/{id}/archive`

### `POST /api/candidates/{id}/needs-clarification`

Request:

```json
{"resolution_note": "Need to ask who this refers to."}
```

### `POST /api/candidates/{id}/supersede`

Request:

```json
{
  "supersedes_candidate_id": "uuid",
  "resolution_note": "Replaced by clearer candidate."
}
```

---

## 12. Corrections

### `POST /api/corrections/apply`

Purpose: direct trusted apply for explicit user corrections in agent conversation.

Request:

```json
{
  "old_record_ref": "entity_edges:uuid",
  "new_record": {
    "record_type": "entity_edges",
    "payload": {}
  },
  "correction_source": {
    "source_type": "agent_conversation",
    "user_explicit": true,
    "excerpt": "No, Alex is a client contact, not a former coworker.",
    "occurred_at": "2026-06-10T00:00:00Z"
  },
  "created_by": "ai_agent"
}
```

Response:

```json
{
  "old_record_ref": "entity_edges:old_uuid",
  "new_record_ref": "entity_edges:new_uuid",
  "episode_id": "uuid"
}
```

Side effects:

- Creates correction episode with excerpt/hash.
- Supersedes/deprecates old record.
- Creates new active canonical record.
- Links evidence.
- Retrieval immediately reflects new record.

Validation:

- Requires `user_explicit = true` for direct apply.
- Agent-inferred corrections must use candidates instead.

---

## 13. Context APIs

### Shared request shape

```json
{
  "query": "그 사람이랑 또 연락 왔는데 애매해",
  "situation_text": "그 사람이 다시 연락했고, 사용자가 답장을 해야 할지 애매해하는 상황.",
  "retrieval_intent": "relationship_advice",
  "desired_context": [
    "recent_interactions",
    "relationship_patterns",
    "communication_preferences",
    "cautions"
  ],
  "candidate_entities": [
    {
      "entity_id": "uuid",
      "confidence": 0.72,
      "reason": "recently discussed person"
    }
  ],
  "focal_entity_id": null,
  "time_window": {"recent_days": 60},
  "include_pending_recent": true,
  "max_results": 8,
  "debug": false
}
```

### `POST /api/context/retrieve`

Purpose: low-level scored retrieval/debug.

Response:

```json
{
  "query": "...",
  "matched_entities": [
    {
      "entity_id": "uuid",
      "display_name": "Alex",
      "score": 0.82,
      "confidence": "high",
      "match_reasons": ["candidate_entity", "recent_mention"],
      "score_breakdown": {
        "entity_hint_score": 0.25,
        "alias_name_score": 0.18,
        "semantic_observation_score": 0.16,
        "recency_score": 0.12,
        "graph_proximity_score": 0.08,
        "confirmation_policy_score": 0.09,
        "penalties": 0.0
      }
    }
  ],
  "matched_observations": [],
  "debug": {
    "semantic_enabled": true,
    "embedding_model": "dragonkue/multilingual-e5-small-ko-v2"
  }
}
```

### `POST /api/context/pack`

Purpose: agent-facing context pack with policy buckets.

Response:

```json
{
  "type": "context_pack",
  "query": "...",
  "confidence": "medium",
  "suggested_response_policy": "conditional_use",
  "matched_entities": [],
  "context_buckets": {
    "direct_surface": [],
    "conditional_surface": [],
    "internal_only": [],
    "blocked": []
  },
  "recent_context": [],
  "stable_context": [],
  "cautions": [],
  "provenance": [],
  "debug": {}
}
```

Rules:

- Does not produce final natural-language advice.
- Uses confidence + surface bucket mapping.
- High confidence may be downgraded by ambiguity guard.

### `GET /api/entities/{id}/context-card`

Purpose: agent/UI shared curated person card.

Response includes:

```text
entity
aliases
profile_facts
relationship_edges
stable_context
recent_context
communication_context
cautions
provenance_summary
retrieval_hints
```

Default limits apply; full data via paginated resources.

---

## 14. Graph

### `GET /api/graph/ego/{entity_id}`

Purpose: generic person-first ego graph.

Query params:

```text
depth=1
relation_type
status
sensitivity
```

Response:

```json
{
  "focal_entity_id": "uuid",
  "depth": 1,
  "nodes": [
    {
      "entity_id": "uuid",
      "display_name": "Self",
      "entity_type": "person",
      "status": "active",
      "sensitivity": "medium",
      "is_focal": true
    }
  ],
  "edges": [
    {
      "edge_id": "uuid",
      "from_entity_id": "uuid",
      "to_entity_id": "uuid",
      "relation_type": "client_contact",
      "directed": true,
      "status": "active",
      "confidence": 0.9
    }
  ],
  "filters_applied": {}
}
```

MVP officially supports `depth=1`.

---

## 15. Ontology

Read-only in MVP.

### `GET /api/ontology`

Returns all seed registries.

### `GET /api/ontology/edge-types`

### `GET /api/ontology/observation-types`

### `GET /api/ontology/entity-fact-types`

### `GET /api/ontology/policies`

---

## 16. Embeddings

### `GET /api/embeddings/status`

Purpose: inspect provider and pending/failed counts.

Response:

```json
{
  "provider": "local_sentence_transformers",
  "model": "dragonkue/multilingual-e5-small-ko-v2",
  "dim": 384,
  "status": "ready",
  "observations": {
    "ready": 10,
    "pending": 2,
    "failed": 1
  }
}
```

### `POST /api/embeddings/backfill`

Purpose: regenerate pending/failed/stale observation embeddings.

Request:

```json
{
  "status": ["pending", "failed"],
  "limit": 100
}
```

Response:

```json
{
  "processed": 10,
  "ready": 9,
  "failed": 1
}
```

---

## 17. Handoff Notes

This spec is intentionally Markdown-first. After implementation stabilizes, generate `openapi.yaml` from FastAPI/Pydantic models or convert this file into formal OpenAPI.

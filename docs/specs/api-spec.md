# Kinlayer API Specification

- Status: Draft v0.1
- Style: OpenAPI-like Markdown
- Parent PRD: `prd.md`
- Related docs: `data-model.md`, `context-output-contract.md`, `candidate-lifecycle-and-payload.md`, `acceptance-scenarios.md`, `../agents/agent-write-instruction-pack.md`

---

## 1. API Principles

Kinlayer's HTTP API is the canonical capability layer.

Product boundary: AI agents interpret current-turn user-authored text and propose candidates or
explicit corrections; Kinlayer validates, stores, retrieves, reviews, and canonicalizes relationship
context.

Agent-facing write behavior is specified in `../agents/agent-write-instruction-pack.md`. In
particular, agent-visible relationship type, API `relation_type`, candidate
`relationship_edge.relation_type`, and graph edge labels are ontology edge types from
`allowed_edge_types`.

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
- Kinlayer does not run an LLM for post-turn extraction and does not classify open-ended
  personhood, fictional/public-figure status, or relationship relevance.
- Agent-submitted write evidence must come from current-turn user-authored source text. Assistant
  messages, tool output, retrieved context packs/cards, system/developer/skill prompts, logs,
  compacted summaries, and previous memory output are not valid evidence.
- Agent-side confidence thresholds and extraction policies are adapter configuration, not core API
  behavior.

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

Docker Compose 기본 실행에서는 `bind_host`가 `0.0.0.0`으로 보고됩니다. CLI `kinlayer serve`의 기본 host는 CLI spec을 따릅니다.

Response:

```json
{
  "bind_host": "0.0.0.0",
  "auth_token_configured": true,
  "embedding": {
    "provider": "local_sentence_transformers",
    "model": "dragonkue/multilingual-e5-small-ko-v2",
    "dim": 384,
    "status": "ready",
    "api_url_configured": false,
    "api_key_configured": false
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

### `POST /api/entities/resolve`

Purpose: agent-facing deterministic entity resolution before candidate/correction planning.

Request:

```json
{
  "surface": "민지",
  "aliases": ["Minji"],
  "relation_hint": "회의 전 한국어 요약",
  "entity_type": "person",
  "source": {
    "kind": "agent",
    "include_self": false
  },
  "limit": 5
}
```

Response:

```json
{
  "surface": "민지",
  "ambiguity": "single_strong_match",
  "matches": [
    {
      "entity_id": "uuid",
      "display_name": "민지",
      "entity_type": "person",
      "score": 1.0,
      "match_reasons": ["alias_exact"]
    }
  ]
}
```

Semantics:

- Matching is deterministic: display name, canonical name, aliases, normalized tokens, and fuzzy
  name/alias similarity.
- Ambiguity values are `no_match`, `single_strong_match`, `multiple_close_matches`, and
  `low_confidence_match`.
- The endpoint does not call an LLM and does not decide whether a mention is fictional, public,
  generic, or relationship-relevant.
- Protected `self` is excluded unless the request explicitly sets `source.include_self = true` or
  uses `source.system_role = self`.

### `POST /api/entities/duplicate-candidates`

Purpose: explicit duplicate-person check that can optionally create a pending `merge` candidate. It
does not mutate canonical entity references or perform an automatic merge.

Request:

```json
{
  "source_entity_id": "uuid",
  "limit": 5,
  "create_candidate": true,
  "evidence": [
    {
      "episode_id": "uuid",
      "excerpt": "Alex K. and 알렉스 refer to the same person.",
      "confidence": 0.85
    }
  ],
  "created_by": "ai_agent"
}
```

Response:

```json
{
  "source_entity_id": "uuid",
  "recommended_action": "create_merge_candidate",
  "candidates": [
    {
      "source_entity_id": "uuid",
      "target_entity_id": "uuid",
      "display_name": "Alex Kim",
      "score": 1.0,
      "match_reasons": ["exact_alias_overlap"],
      "recommended_action": "create_merge_candidate",
      "reason": "Alex K. and Alex Kim share duplicate signals: exact_alias_overlap.",
      "fields_to_merge": ["aliases", "profile_facts", "edges", "observations"],
      "risk_notes": ["Review before merging; Kinlayer never auto-merges duplicate people."]
    }
  ],
  "created_candidate": null
}
```

Semantics:

- Recommended actions are `no_match`, `create_merge_candidate`, and `needs_clarification`.
- Exact alias/name overlap is strong; fuzzy name similarity can rank possible duplicates but still
  requires review.
- `create_candidate = true` requires traceable evidence and persists a pending `merge` candidate.
- Agents may accept the resulting merge candidate only after explicit current-turn user confirmation
  for the exact source-target pair.
- Protected `self` cannot be source or target for normal person duplicate/merge flow.

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
- `created_by = ai_agent` candidates require at least one evidence item.
- `created_by = ai_agent` candidates pass the deterministic agent write filter before persistence.
- Evidence must reference an existing episode with supported source type, non-empty excerpt,
  confidence in `[0, 1]`, source ref, body hash, and actor.
- Candidate responses include evidence source metadata when available: `source_type`, `source_ref`,
  `source_description`, `body_hash`, and `actor`.
- `merge` candidate accept executes the person merge workflow. `conflict` and `supersede` remain
  review-only until their specific execution workflows exist.

### `POST /api/agent-writes/validate`

Purpose: dry-run deterministic validation for agent candidate/correction payloads without
persisting candidates or canonical records.

Request:

```json
{
  "write_type": "candidate",
  "payload": {
    "candidate_type": "relationship_edge",
    "payload": {
      "from_entity_id": "uuid",
      "to_entity_id": "uuid",
      "relation_type": "Former coworker",
      "claim_text": "They worked together.",
      "claim_type": "fact"
    },
    "evidence": [{"episode_id": "uuid", "excerpt": "..."}],
    "confidence": 0.8,
    "created_by": "ai_agent"
  }
}
```

Response:

```json
{
  "accepted": true,
  "validated_payload": {},
  "normalizations_applied": [],
  "warnings": [],
  "errors": [],
  "diagnostics": {},
  "controlled_values_checked": [],
  "audit_ref": null
}
```

Filter rules:

- no LLM calls, keyword intent rewriting, fuzzy semantic classification, translation, or synonym guessing;
- low-risk normalization only for controlled values that map to exactly one active registry value
  or label after trimming, casefolding, whitespace collapse, and space/hyphen-to-underscore;
- unknown edge types return `relation_type_not_allowed` with the allowed edge-type list;
- the filter validates evidence, entity refs, endpoint entity-type compatibility, and explicit
  user correction requirements for agent-submitted writes.

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

Request:

```json
{
  "resolved_by": "ai_agent",
  "resolution_note": "User explicitly confirmed merging Alex K. into Alex Kim in the current turn."
}
```

Both fields are optional; clients should send them when an agent accepts a candidate after explicit
user confirmation.

Response:

```json
{
  "id": "uuid",
  "candidate_type": "observation",
  "status": "accepted",
  "canonical_record_ref": "observations:uuid",
  "payload": {},
  "evidence": []
}
```

Merge candidate accept:

- Executes in one service transaction.
- Repoints selected source aliases, non-conflicting facts, active relationship edges, observation
  subjects, and related observation entity refs to the target.
- Marks the source entity `status = merged`, `confirmation_status = merged`, and stores
  `properties.merged_entity_ref = entities:<target_id>`.
- Creates an `entity_merges` audit row linked to the candidate, source, target, merge plan,
  conflict decisions, actor, canonical record ref, and previous refs.
- Rejects source equals target and any normal merge involving protected `self`.
- Default active entity lists, retrieval, context pack/retrieve, context card, and graph treat the
  target as canonical after merge.

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
- Response is the same flat candidate object shape as `accept`.

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
    "source_actor": "user",
    "user_explicit": true,
    "excerpt": "No, Alex is a client contact, not a former coworker.",
    "source_ref": "source_message_id:source_turn_id",
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
  "episode_id": "uuid",
  "source_actor": "user",
  "submitted_by": "ai_agent"
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
- Requires exactly one supported `old_record_ref`; ambiguous targets must be clarified before direct apply.
- Records the user-authored correction source separately from the submitting agent/runtime.
- Agent-inferred corrections must use candidates instead.

---

## 13. Context APIs

### Shared request shape

```json
{
  "query": "그 사람이랑 또 연락 왔는데 애매해",
  "entity_hints": ["uuid"],
  "focal_entity_id": null,
  "query_embedding": null,
  "include_debug": false,
  "limit": 8
}
```

### `POST /api/context/retrieve`

Purpose: low-level scored retrieval/debug.

Response:

```json
{
  "matched_entities": [
    {
      "entity_id": "uuid",
      "display_name": "Alex",
      "entity_type": "person",
      "score": 0.82,
      "confidence_band": "high",
      "match_reasons": ["entity_hint", "recent"],
      "score_breakdown": {
        "entity_hint": 0.25,
        "alias_name": 0.2,
        "semantic_observation": 0.2,
        "recency": 0.15,
        "graph_proximity": 0.1,
        "confirmation_policy": 0.1
      },
      "penalties": {},
      "surface_bucket": "direct_surface",
      "sensitivity": "medium",
      "ai_use_policy": "cautious_use",
      "confirmation_status": "confirmed",
      "observations": []
    }
  ],
  "observations": [],
  "scores": {"uuid": 0.82},
  "match_reasons": {"uuid": ["entity_hint", "recent"]},
  "score_breakdown": {"uuid": {"entity_hint": 0.25}},
  "ambiguity_detected": false,
  "debug": {
    "score_weights": {}
  }
}
```

### `POST /api/context/pack`

Purpose: agent-facing context pack with policy buckets.

Response:

```json
{
  "context_pack": {
    "confidence": "medium",
    "suggested_response_policy": "conditional_use",
    "ambiguity_detected": false,
    "matched_entities": [],
    "buckets": {
      "direct_surface": [],
      "conditional_surface": [],
      "internal_only": [],
      "blocked": []
    },
    "recent_context": [],
    "stable_context": [],
    "cautions": [],
    "provenance": []
  },
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

Returns active ontology edge types. UI-visible relationship type, API `relation_type`, candidate
`relationship_edge.relation_type`, and graph edge labels must all derive from these values.

### `GET /api/ontology/edge-type-diagnostics`

Purpose: inspect existing `entity_edges.relation_type` values and find legacy rows whose relation
type is missing from active `allowed_edge_types`.

Response:

```json
{
  "relation_types": [
    {
      "relation_type": "client_contact",
      "exists_in_allowed_edge_types": true,
      "edge_count": 3,
      "active_edge_count": 2
    }
  ],
  "invalid_edges": [
    {
      "edge_id": "edge-id",
      "relation_type": "reply_strategy",
      "edge_type_match": "missing_allowed_edge_type",
      "from_entity_id": "person-1",
      "to_entity_id": "person-2",
      "from_entity_type": "person",
      "to_entity_type": "person",
      "status": "active",
      "created_by": "ai_agent",
      "source_candidate_id": "candidate-id",
      "created_at": "2026-06-12T00:00:00Z",
      "updated_at": "2026-06-12T00:00:00Z"
    }
  ]
}
```

This endpoint is read-only. It reports invalid legacy rows with either
`missing_allowed_edge_type` or `endpoint_type_mismatch`, but does not repair or rewrite them.

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
    "total": 13,
    "pending": 2,
    "ready": 10,
    "failed": 1,
    "stale": 0
  }
}
```

### `POST /api/embeddings/backfill`

Purpose: regenerate pending/failed/stale observation embeddings.

Query params: `limit` (default `100`, max `500`).

Response:

```json
{
  "processed": 10,
  "failed": 1,
  "skipped": 0
}
```

---

## 17. Agent Write Operations

Purpose: inspect and export what AI agents attempted to write into Kinlayer and what happened to
those attempts. Direct edge create/update attempts are also included when Kinlayer can identify the
submitting actor because relation-type enforcement is part of the same write-integrity audit trail.

Scope is write-only. These endpoints do not export context-pack/retrieval reads, full prompts, raw conversation transcripts, bearer tokens, API keys, or ordinary container logs.

### `GET /api/agent-operations`

Query params:

- `actor`
- `source_path`
- `operation_type`
- `result_status`
- `has_error`
- `created_from`
- `created_to`
- `limit`
- `offset`

Response:

```json
{
  "items": [
    {
      "id": "audit-id",
      "audit_id": "audit-id",
      "operation_type": "candidate_submit",
      "source_path": "/api/candidates",
      "actor": "ai_agent",
      "result_status": "success",
      "api_error_code": null,
      "request_summary": {"candidate_type": "relationship_edge", "relation_type": "client_contact"},
      "diagnostics": {},
      "related_refs": {
        "edge_type_match": "active_allowed_edge_type",
        "from_entity_id": "person-1",
        "to_entity_id": "person-2"
      },
      "candidate_id": "candidate-id",
      "correction_id": null,
      "episode_id": "episode-id",
      "canonical_record_ref": "observations:record-id",
      "bounded_excerpt": "User-authored bounded excerpt.",
      "created_at": "2026-06-12T00:00:00Z",
      "updated_at": "2026-06-12T00:00:00Z"
    }
  ],
  "limit": 50,
  "offset": 0,
  "total": 1
}
```

### `GET /api/agent-operations/export`

Returns newline-delimited JSON with a manifest first, then bounded operation records. `format=jsonl` and `format=ndjson` are accepted aliases.

```jsonl
{"record_type":"manifest","schema_version":"agent_write_operations.v1","scope":"agent_write_operations_only"}
{"record_type":"agent_write_operation","schema_version":"agent_write_operations.v1","audit_id":"audit-id","operation_type":"candidate_submit"}
```

---

## 18. Handoff Notes

This spec is intentionally Markdown-first. After implementation stabilizes, generate `openapi.yaml` from FastAPI/Pydantic models or convert this file into formal OpenAPI.

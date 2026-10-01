# Kinlayer API Specification

> Sensitivity is retired. See [retirement and compatibility contract](sensitivity-retirement.md).

Authenticated reconciliation actions may carry up to six deterministically ordered typed context claims.
Each targets only the resulting primary person and derives content from an exact native-reply span or
candidate-bound original user evidence. Identity and context commit in one transaction.

- Status: Draft v0.1
- Style: OpenAPI-like Markdown
- Parent PRD: `prd.md`
- Related docs: `data-model.md`, `context-output-contract.md`, `candidate-lifecycle-and-payload.md`, `acceptance-scenarios.md`, `../agents/agent-write-instruction-pack.md`

---

## Current memory write API — 2026-10-01

`POST /api/memories` is the canonical agent write contract. It stores one independently correctable
claim immediately; no candidate accept, curation run or human approval is required. See the full
[agent request contract and JSON examples](../agents/agent-write-instruction-pack.md).

| Request field | Meaning |
| --- | --- |
| `request_id` | Stable logical operation ID; same-body retry returns the original change. |
| `action` | `create`, `correct`, `retract`, `reattribute`. |
| `old_record_ref` | Required for non-create actions; exact fact/edge/observation ref. |
| `record` | Required except for retract: `record_type` plus its typed `payload`. |
| `source` | `source_type`, actual human `actor`, 1–4,000-character `excerpt`, optional `source_ref` and statement `occurred_at`. |
| `reason` | Optional bounded change rationale, not evidence. |
| `created_by` | Defaults to `ai_agent`; distinct from the source author. |
| `expected_updated_at` | Optional concurrency precondition for the old record. |

Accepted record types are `entity_facts`, `entity_edges`, `observations`. New payloads require
`claim_basis: reported|inferred|unknown` and `confidence` from 0 to 1. Legacy `claim_type`,
`ai_use_policy`, and `confirmation_status` are not accepted in this new payload.

New text profile facts require matching `content` and `value: {text}`. Birth date/birthday facts
use known date components with explicit `precision`. Generic note fact types are rejected; use an
observation with an appropriate topic. The agent splits multi-claim paragraphs before submission.

Ordinary `source_type` is `agent_conversation` or `manual_entry`. Import/connector material must
use its separately authorized import API. Invalid/missing source, malformed type/value/reference,
conflicting request-ID reuse, and stale record changes fail without partial canonical/evidence/
history writes. A receipt identifies `change_id`, `action`, `old_record_ref`, `new_record_ref`, and
`source_episode_id`; a retraction has no new record. The endpoint returns HTTP 200 on initial success and replay.
All new-memory timestamp fields require a timezone offset; unknown values are omitted/null and naive
values are HTTP 422. Active/disputed old records can be changed; superseded/deleted targets conflict.

Episode hashing, evidence linkage, old-record status change, replacement and common change history
are one transaction. Replacement observation embeddings remain reindexable; provider absence must
not prevent storage. AI-use-policy and confirmation values retained on old APIs are inert
compatibility metadata. A fact/edge/observation referenced by `memory_changes`, including migrated
records, rejects legacy PATCH/DELETE with HTTP 409 `memory_change_required`. Its changes must use
`/api/memories` correct/retract/reattribute. Legacy GET remains valid, and untracked historical data
retains compatibility behavior. Old CRUD/candidate/correction examples below document retained interfaces;
new agents must use the memory endpoint so source and history remain atomic.

History reads:

- `GET /api/memory-changes?record_ref=<type:id>&limit=50&offset=0`: filter either old or new ref;
  limit is 1–100. Returns `{items,total,limit,offset}`.
- `GET /api/memory-changes/{change_id}`: exact change row or HTTP 404.

Change rows expose `id`, `request_id`, `change_kind`, `old_record_ref`, `new_record_ref`,
`source_episode_id`, writer `actor`, `reason`, and `created_at`. They do not dump source excerpts or
internal request hashes. Original source details are read through the linked Episode.

The running `/openapi.json` is the machine-readable contract. Do not infer new endpoint support from
older Markdown examples. Frontend replacement is [planned separately](../plans/frontend-rebuild.md).

---

## 1. API Principles

Kinlayer's HTTP API is the canonical capability layer.

Explicit user-authorized source imports use `POST /api/material-imports/validate`,
`POST /api/material-imports/submit`, and `GET /api/material-imports/{import_id}`.
They require a separate token and bounded manifest; see the
[authorized material import contract](authorized-material-imports.md).
Ordinary post-turn source admission and retained correction/reconciliation identity guards remain;
immediate storage does not grant arbitrary material-import authorization.

Product boundary: agents interpret current human source and split atomic claims; Kinlayer
validates and stores canonical records, evidence, and change history immediately. Corrections,
retractions and reattributions use the same memory contract.

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
  "embedding": "disabled"
}
```

`embedding` reports the same effective configuration status as `/api/system/config`:
`ready`, `configured`, `misconfigured`, `disabled`, or `unsupported`. This checks configuration,
not a live provider request or index completeness. Overall health `status` remains based on DB
health; use embedding status/backfill and an actual provider operation to verify index/provider use.

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
  "auth_token_configured": false,
  "memory_write": {
    "endpoint": "/api/memories",
    "review_required": false,
    "contract_version": "2"
  },
  "embedding": {
    "provider": "disabled",
    "model": null,
    "dim": null,
    "status": "disabled",
    "api_url_configured": false,
    "api_key_configured": false
  }
}
```

When `KINLAYER_EMBEDDING_API_KEY` is configured without an explicit provider, the
effective provider becomes `openai_compatible`, with the default OpenAI-compatible
API URL, model, and dimension from `Settings`.

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

Purpose: agent-facing deterministic entity resolution before memory writes or retrieval.

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

Purpose: low-level compatibility profile CRUD. Agents use /api/memories for atomic source/history.

Request:

```json
{
  "entity_id": "uuid",
  "fact_type": "organization",
  "content": "Example Corp",
  "claim_type": "fact",
  "confidence": 0.95,
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
- Structured profile fact validators currently apply to `legal_name`, `birth_date`, `phone`,
  `email`, `address`, `organization`, and `role`.
- Structured validator rules:
  - all supported structured fact content must be a string and cannot be blank after trimming;
  - `birth_date` must be ISO `YYYY-MM-DD`;
  - `email` must contain exactly one `@`, a non-empty local part, a dotted non-empty domain, and no
    whitespace; the domain is normalized to lowercase;
  - `phone` must contain at least seven decimal digits;
  - `legal_name`, `address`, `organization`, and `role` trim surrounding whitespace.
- Other registry-backed fact types, such as `memo`, remain valid profile facts but do not receive
  the structured validator rules above unless code adds them to the structured validator set.

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

### `POST /api/entity-facts/{id}/promote`

Purpose: promote an active general profile fact into a structured profile fact while preserving
provenance and superseding the source record.

Request:

```json
{
  "entity_id": "uuid",
  "fact_type": "email",
  "content": "alex@example.com",
  "field_path": "profile.email",
  "value": "alex@example.com",
  "ai_use_policy": "ask_before_use"
}
```

Response:

```json
{
  "source_record_ref": "entity_facts:old_uuid",
  "replacement_record_ref": "entity_facts:new_uuid",
  "source": {},
  "replacement": {}
}
```

Semantics:

- Source fact must exist, belong to the request `entity_id`, have status `active`, belong to an
  active entity, and must not already be one of the structured validator fact types.
- Target `fact_type` must be one of the supported structured profile fact validator types listed
  under `POST /api/entity-facts`.
- Target content is normalized and validated by the structured validator rules.
- A replacement `entity_facts` row is created. The source fact becomes `status = superseded`.
- Replacement `value` stores `field_path`, `value`, and
  `supersedes_record_ref = entity_facts:<source_id>`.
- Replacement preserves source `claim_type`, confidence, validity window, and copied evidence.
  `ai_use_policy` defaults from the source unless provided.
- Errors include `validation_error` for invalid target type/content, entity mismatch, or already
  structured source; `conflict` for inactive/stale source paths; and `not_found` for missing facts.

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
- `profile_field` candidates may include top-level `supersedes_record_ref`. When present it must
  be `entity_facts:<id>`, point to an active fact on the same entity, and accept/edit-accept uses
  the fact promotion path instead of creating an unrelated new fact.
- Structured `profile_field` candidates use the same validation rules as direct `entity_facts`
  writes. If `content` is omitted for a structured `fact_type`, validation uses `value` as content.
- `observation` candidate payload supports `occurred_at`, `valid_from`, and `valid_to`; accept
  and edit-accept preserve those fields into canonical `observations`.
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
- `profile_field` validation checks structured fact content, same-entity
  `supersedes_record_ref`, and stale superseded-source refs before persistence.
- observation candidates may return non-blocking warnings for content quality issues such as
  overlong content, dangling references, missing temporal scope, or typed-record boundary review;
  the filter does not rewrite observation prose into facts or edges.

### `GET /api/candidates`

Query params:

```text
status
candidate_type
target_entity_id
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
        "graph_proximity": 0.1
      },
      "penalties": {},
      "surface_bucket": "direct_surface",
      "profile_facts": [],
      "observations": []
    }
  ],
  "observations": [],
  "provenance": [],
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

Purpose: agent-facing context pack with basis, participants, timestamps and provenance. Legacy bucket keys remain for compatibility, without AI-use-policy gating.

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

## 19. Periodic Relationship Curation

`KINLAYER_CURATION_MODE=disabled|shadow|apply` is authoritative and is returned by
`GET /api/system/config` with `policy_version`.

```text
POST /api/curation/source-packs
POST /api/curation/runs
GET  /api/curation/runs
GET  /api/curation/runs/{run_id}
POST /api/curation/runs/{run_id}/execute
POST /api/curation/runs/{run_id}/resume
```

Source packs use an exclusive `(created_at,candidate_id)` cursor, fixed `as_of`, and explicit
candidate/evidence/excerpt budgets. They contain bounded user-authored excerpts, compact target
context, validation diagnostics, and exact duplicate/conflict signals, never episode bodies or raw
provider/session data. Candidate payloads are bounded typed projections. The first pack returns a
server-derived lower-bound `cursor_started`; non-empty plans must echo that start, the completed
cursor, and input count. The deduplicated union of all decision `candidate_ids` must equal the exact
server-derived pending candidate set, and every candidate must appear in exactly one decision.
Partial coverage, duplicate membership, out-of-window IDs, and count drift return HTTP 409 before
any run or decision is persisted. A consolidate decision may contain multiple candidates, but those
candidates cannot appear in another decision. An empty window requires zero count and zero decisions.
Every non-empty decision also carries the exact reviewed candidate status, `updated_at`, payload
digest, and evidence digest. Kinlayer compares those snapshots before run persistence and again
after execution locks are acquired; drift returns `source_pack_candidate_changed` or blocks the
decision as `source_candidate_changed` before canonical mutation.
Reason codes are `source_pack_candidate_coverage_mismatch`, `duplicate_candidate_membership`,
`candidate_outside_source_pack`, `source_pack_count_mismatch`,
`source_pack_snapshot_mismatch`, `source_pack_candidate_changed`, and
`source_pack_empty_run_mismatch`.

`POST /api/curation/source-packs` accepts optional `upper_cursor`. Selection is the full tuple window
`cursor < (created_at,candidate_id) <= upper_cursor`; `upper_cursor` must be greater than the effective
lower cursor. `has_more` and the limit+1 probe are computed only inside that window, so same-timestamp
IDs greater than the upper ID cannot widen results. Run validation applies the completed cursor as the
same tuple-inclusive upper bound.

An auditable empty replay checkpoint is an apply-mode run with zero input/decisions, complete start
and completed cursor pairs, and exactly `diagnostics.replay_checkpoint=true`. Before persistence,
Kinlayer re-queries the exact `(start,end]` tuple window and requires zero pending candidates. A valid
checkpoint is created, evaluated, and executed to an empty `completed` apply run; repeated execute or
resume is idempotent and performs no candidate/canonical mutation. Missing/reversed bounds, non-apply
mode, decisions, or pending rows fail with `replay_checkpoint_invalid` or
`replay_checkpoint_not_empty`. Ordinary empty runs remain cursorless and are not auto-executed.
Run diagnostics/proposals reject nested reserved raw/session/transcript/tool keys and over-limit JSON.
Run submission persists proposals and recomputes `allowed`/`blocked` from
stored state. `shadow` never executes. `apply` commits canonical writes, source states, evidence,
and an `executing/verification_unknown` decision atomically, then marks `executed/verified` only after
fresh exact post-commit reconciliation. Phone/email/address/contact-like content is never automatic.

`POST .../resume` has two strictly separated roles. With curation enabled and the stored
`policy_version` matching current configuration, persisted `pending` or `planning` runs are
deterministically re-evaluated to `ready` with `allowed|blocked` decisions and fresh DB readback;
this recovery performs no candidate or canonical writes. It may recover a stored shadow run while
the server is configured as either `shadow` or `apply`. Repeating resume on a ready shadow run is a
read-only no-op. Apply-run execution/reconciliation from `ready|executing|partial|failed|completed`
still requires server mode `apply`; disabled mode and stale policy versions fail closed.

Context-card query `include_provisional=true` and context-pack field `include_provisional=true`
return eligible pending observations only in a separate `provisional_context` array.

## Reconciliation actions

```text
GET  /api/reconciliation/entity-snapshots?limit=200&offset=0
GET  /api/reconciliation/candidate-evidence-snapshots?candidate_id=<id>
POST /api/reconciliation/actions
GET  /api/reconciliation/actions/{action_id}

POST /api/reconciliation/enrichment-authorizations
POST /api/reconciliation/enrichment-answers
GET  /api/reconciliation/enrichment-answers/{action_id}
```

These routes are disabled unless `KINLAYER_RECONCILIATION_TOKEN` is configured. Stage and existing
identity-reconciliation routes require that dedicated bearer credential. A successful or idempotent
stage returns a deterministic opaque per-authorization answer capability. Answer POST and GET require
that exact capability in `X-Kinlayer-Enrichment-Capability`; the broad reconciliation bearer alone is
not sufficient and the capability cannot stage. Missing, wrong, and cross-authorization capabilities
fail closed without disclosing action existence. The capability is derived by server-secret HMAC and
is never stored in plaintext. Rotating `KINLAYER_RECONCILIATION_TOKEN` invalidates outstanding
capabilities; recovery is a same-body stage retry
while the authorization remains open, or a fresh stage after expiry. Authorization expiry
independently ends answer authority.

Conversational enrichment is a separate closed surface and does not overload reconciliation
actions. A trusted PCR/compiler stages an authorization for one active confirmed person (including
protected self) and one to three append-only slots for one topic. The backend resolves and snapshots
all entity IDs. Each immutable authorization entity snapshot contains exactly `id`, `entity_type`,
`display_name`, nullable `canonical_name`, nullable `system_role`, `confirmation_status`, `status`,
`updated_at`, and `entity_digest`. The existing digest/stale comparison remains exact. Snapshots do
not contain aliases, raw context, properties, question/reply text, or capabilities. The backend fixes
policy/claim type, validates the small proactive ontology
allowlists, rejects duplicate semantic slot authority, and rejects already-filled gaps. A gap is
also filled when an exact semantically matching candidate for the subject is `pending` or
`needs_clarification`; stage and answer-time revalidation return `409 pending_gap_filled` before any
authorization, action, Episode, candidate, canonical, or slot mutation. The stage body contains no
question or reply text.

At stage and answer-time revalidation, the main subject must also be unambiguous among active
confirmed people. The backend normalizes each nonempty display name, canonical name, and active alias
with the canonical `normalize_name` helper and rejects any overlap with another such person as
`409 subject_ambiguous` before authorization, action, Episode, candidate, canonical, or slot mutation.
Empty or malformed identifiers do not match; there is no fuzzy matching. Protected self is identified
by the unique `system_role=self` invariant and bypasses ordinary name-collision checks. Inactive or
unconfirmed people do not create ambiguity.

An answer contains only a resolution ID, authorization ID, bounded explicit-user source metadata,
an optional bounded known-evidence bundle, and sorted closed slot answers. The bundle is required iff
at least one answer is known and must be absent for all-unknown/skip actions. Known answers supply a slot-permitted
text value, an optional selection from the slot's stored ontology allowlist, and exact evidence
contained in that bundle. Unknown closes a slot without writing; skip leaves it open. An all-unknown/
skip action creates no Episode, candidate, canonical, or evidence row. Mixed actions create one Episode
containing only the bounded known-evidence bundle and evidence only for known slots. The
backend compiles candidates and accepts them atomically as the user. POST retry and GET perform only
fresh readback after the first commit; they never replay canonical writes.

`GET .../entity-snapshots` returns a bounded page of active person entities with only `id`,
entity/name fields, status, `updated_at`, and the backend-computed exact entity digest used by
reconciliation preconditions. It rejects pages larger than 200; a caller that cannot review the
complete bounded set must fail closed instead of silently comparing a partial person graph.

`GET .../candidate-evidence-snapshots` is reconciliation-token gated and accepts one to fifty
unique candidate IDs. It returns exact candidate status/`updated_at`/payload/evidence digests plus
only eligible user-authored `agent_conversation` evidence: candidate/evidence/episode IDs, the exact
bounded excerpt (maximum 500 code points), body hash, actor/source type, and server-derived effective
AI-use policy. It never returns `source_ref`, an Episode body, record summaries, or
assistant/system evidence. This is a private stage-validation surface, not generic CLI/session output.
If any requested candidate has more than twenty attached evidence rows, the whole request fails
closed with deterministic `409 candidate_evidence_limit_exceeded`; evidence is never silently
truncated and schema validation never becomes a 500.

POST accepts a closed, bounded request containing a unique `resolution_id`, one allowlisted action,
the exact candidate ID set and reviewed status/`updated_at`/canonical-payload and evidence SHA-256
digests, optional target/name fields, an optional closed bounded `relationship_to_self` object
containing only `relation_type` and `claim_text`, a bounded resolution note, and a user-explicit confirmation
source. Unknown fields, unbounded collections/text, non-user sources, and malformed hashes are
rejected. Durable rows contain only those bounded controls and compact outcomes; raw Discord
questions or replies, transcripts, prompts, provider payloads, and model output are forbidden.
Every action also carries exactly one `answer_bindings` entry authenticated by a separate
`KINLAYER_RECONCILIATION_COMMITMENT_KEY` of at least 32 UTF-8 bytes, enforced at settings startup.
Its HMAC commits the actual PCR
question ID, answer item and fingerprint, full agenda digest, resolution/action digest, and exact
context-claim digest. Kinlayer verifies it before idempotency lookup or mutation. Possession of the
reconciliation bearer alone cannot forge or substitute a binding. Omitted, duplicate, cross-item,
cross-question, cross-agenda, cross-claim, and cross-action bindings return 422.
The commitment key must differ from the reconciliation bearer token; equal configured values are
invalid. Do not rotate it while an action is pending fresh readback.
An action may carry at most six sorted, semantically unique typed context claims. Current-reply
claims use exact code-point spans and are fixed to `cautious_use`. Prepared claims carry
only candidate/evidence/episode IDs, exact body/excerpt commitments, and server-validated offsets;
their AI-use policy preserves the more restrictive of `cautious_use` and the original candidate policy. The backend re-derives these values under the same transaction and fresh
readback verifies candidate payload, manifest, and canonical AI-use policy without downgrade.

The actions are `reject_candidates`, `map_to_existing_entity`, `confirm_new_entity_group`,
`accept_existing_entity_observation_group`, `rename_and_accept_new_entity`,
`merge_existing_entities`, and `archive_existing_entity`. Existing
candidate action shapes remain unchanged and lock candidates in ID order. Entity cleanup actions
use empty candidate lists plus bounded exact entity status/`updated_at`/entity digests and lock
entities in ID order. Mapping requires one exact reviewed active non-self target snapshot and locks
that target in the same transaction. Group confirmation deterministically retains one pending
`new_entity`, creates exactly one person through the canonical candidate writer, and supersedes the
rest. Rename does the same after validating the supplied stable person name. Only rename may include
`relationship_to_self`: the service resolves the single active protected-self person internally,
creates one user-authored `relationship_edge` candidate from self to the new person with
`claim_type=fact`, empty properties, and confirmation-episode-only evidence, and accepts it before
the same commit. The caller cannot supply either endpoint ID. No profile field is produced.
`accept_existing_entity_observation_group` requires exact snapshots for one or more pending
observation candidates plus exactly one exact snapshot for the supplied active non-system, non-self
person target. Candidate targets and payload subjects must all equal that target. It accepts every
candidate through the canonical observation writer in one transaction, preserving one
`observations:<id>` record and exact source-evidence linkage per candidate; it never creates, renames,
merges, maps, or supersedes an entity or candidate. Before canonical writes, the service derives the
union of the target, every observation subject, and every related entity from the locked candidate
snapshots and locks that full entity set once in globally sorted ID order.
Protected-self names
and aliases, pronouns, relationship nouns, honorific-only labels, and role/title-only labels cannot
be created, renamed, or mapped as people.

Existing-entity merge requires distinct active non-system person source and target IDs. It creates
exactly one internal user-explicit typed merge candidate with the canonical merge defaults, accepts
it atomically, and records candidate, merge, evidence, audit, canonical, and context readback.
Archive requires one active non-self person created through the reviewed `new_entity` path and no
active aliases, facts, edges, observations, related-observation memberships, or merge dependencies;
otherwise the request fails closed and requires merge or correction. Archive uses canonical entity
soft-delete semantics and verifies deletion/deprecation and absence from active context.

The unique resolution ID is also the idempotency key. Reuse with the same normalized fingerprint
returns the same action; reuse with different input returns `409`. Any mismatch in the locked
candidate snapshot returns `409` without mutation. Mutation commits with
`committed_unverified`, after which a fresh database session reads candidates, canonical entity,
candidate evidence, and context projection. Readback failure preserves `committed_unverified`;
POST retry and GET perform readback only and never replay canonical writes. Successful readback
returns `verified` plus every candidate type/status/target/reference and exact payload/evidence
digests, bounded derived-candidate summaries, and compact entity/evidence/context data. Merge and
archive also return the post-action source-entity state and digest so adapters can verify the retired
source independently. Relationship verification requires the accepted user-resolved
derived candidate, exact confirmation episode, canonical edge source-candidate linkage, self/person
endpoints, relation type, claim text, and canonical reference to all match. Any mismatch remains
`committed_unverified` with `readback_unavailable`.
The same transaction stores the safe signed binding in the existing action ledger summary. Fresh
readback revalidates its HMAC and returns the exact `answer_binding`; a retry cannot replay writes or
change the binding. It contains only IDs, digests, version, action name, and MAC—never prior excerpts
or source handles.

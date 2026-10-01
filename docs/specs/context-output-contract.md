# Kinlayer Context Output Contract

- Status: save-first read-contract revision, 2026-10-01
- Wire schema: `backend/src/kinlayer_backend/schemas/context.py`
- Related: `api-spec.md`, `data-model.md`, `candidate-lifecycle-and-payload.md`

## Purpose and safety boundary

Kinlayer retrieves, scores, filters, labels, and packages relationship context. It does not author
final advice, message drafts, or natural-language briefings.

Context output is never write evidence. Agents must not reuse context cards/packs, retrieval debug,
logs, summaries, assistant/tool output, or earlier memory output as candidate or correction evidence.

Request models reject unknown fields with HTTP 422. There are no silent legacy aliases.

## Raw retrieval

`POST /api/context/retrieve`

Request:

```json
{
  "query": "Casey scheduling",
  "entity_hints": ["entity-id"],
  "focal_entity_id": "entity-id",
  "query_embedding": null,
  "include_debug": false,
  "limit": 10
}
```

Response:

```json
{
  "matched_entities": [{
    "entity_id": "entity-id",
    "display_name": "Casey",
    "entity_type": "person",
    "score": 0.82,
    "confidence_band": "high",
    "match_reasons": ["entity_hint"],
    "score_breakdown": {},
    "penalties": {},
    "surface_bucket": "direct_surface",
    "profile_facts": [],
    "observations": []
  }],
  "observations": [],
  "provenance": [],
  "scores": {"entity-id": 0.82},
  "match_reasons": {"entity-id": ["entity_hint"]},
  "score_breakdown": {"entity-id": {}},
  "ambiguity_detected": false,
  "debug": {}
}
```

Observation results carry the exact record ID, content, topic (`observation_type`), `claim_basis`,
confidence, subject and related people/roles, relevance score/reasons, status, and known temporal
fields. Agent context outputs omit legacy `claim_type`, `ai_use_policy`, and entity
`confirmation_status`; low-level CRUD compatibility responses may still carry them. The stored `reported` basis means a source stated the claim,
not that Kinlayer independently verified it.

Raw retrieval also returns a top-level `provenance` array, with the same structured source fields
as `context_pack.provenance` and `provenance_summary.evidence`. Agents need not call a second pack
endpoint merely to obtain source author and statement time.

## Context pack

`POST /api/context/pack`

The request accepts every raw-retrieval field plus:

```json
{
  "situation": "Optional text combined with query for deterministic retrieval.",
  "include_provisional": false
}
```

`situation` is pack-only and is combined with `query`; it is not silently ignored. Legacy fields
such as `situation_text`, `retrieval_intent`, `desired_context`, `candidate_entities`, `time_window`,
`include_pending_recent`, `max_results`, and `debug` are rejected.

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
    "provenance": [],
    "provisional_context": []
  },
  "debug": {}
}
```

Response guidance reflects match confidence and identity ambiguity. Compatibility bucket and
policy keys remain for older clients, but stored AI-use policies do not block current records.
New integrations must read record basis, subject/roles, times and provenance rather than treating
`direct_surface` or `confirmed` as proof of factual truth.

## Person context card

`GET /api/entities/{entity_id}/context-card?include_provisional=false`

Response keys are:

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
provisional_context
```

`provenance_summary` contains fact/edge/observation/evidence counts and bounded evidence records.
Structured attribution includes `source_type`, `source_ref`, actual human `actor`, and
`source_occurred_at` when available. A source statement timestamp is not the described event time. An absent historical source
is reported as absent, never synthesized from an existing claim.
`retrieval_hints` contains `entity_id`, `canonical_name`, aliases, and entity type. Merged source IDs
resolve to the active target entity.

## Legacy provisional context

Provisional context is retained for old candidate clients; new immediately saved memories use
ordinary canonical fields without waiting for promotion. Provisional context is opt-in and
structurally separate from every canonical field. It contains at
most five recent pending observation candidates for one exactly resolved active entity, after
user-authored evidence, content, temporal, contact/high-impact, and policy checks.

Each item contains:

```text
candidate_id
content
observation_type
valid_from / valid_to / occurred_at
created_at
label = provisional
review_status = unreviewed
write_evidence_eligible = false
```

It never enters provenance, canonical stable/recent/caution fields, retrieval evidence, or later
writes. Identity, structural, contact-like, warned, ambiguous, or non-user-grounded
candidates are excluded.

## Temporal, basis and compatibility rules

- `occurred_at` is described event time.
- `valid_from` and `valid_to` are applicability bounds.
- `created_at` is storage time only.
- Retired AI-use-policy values, including `never_surface`, do not hide current records.
- Superseded, retracted and deprecated records are excluded from current context; inspect history separately.
- Active/disputed records expose validity bounds for interpretation; the current read path does not
  turn missing dates into known event times or infer validity from creation time.
- Low confidence or ambiguity yields `ask_clarifying_question`.
- Kinlayer returns basis, provenance and ambiguity metadata, not polished clarification wording.
- Full episode bodies and conversations are never context outputs.

## Current relationship profile

Person context cards and matched entities in retrieval/context packs include
`relationship_profile: {version,entity_id,perspective_entity_id,axes}`. Each axis contains value,
label and the full source-backed MemoryRead record, or explicit nulls when unset. Consumers retain
record_ref, updated_at, perspective and sources, including when compacting output. Structured
relationship assessments do not also appear in generic stable-context observation lists.

The profile describes the user's perspective, not a global trait of the person or the other
person's feelings. All axes are explicitly reported; absence is not low closeness/importance or
no contact/disconnection. Importance may only break ties among already relevant matches and must
not create relevance, increase confidence or exclude less-important/unset people. This projection
adds no meeting history, frequency counter, automatic decay or relationship-type changes.

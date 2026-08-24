# Kinlayer Context Output Contract

- Status: Implemented v0.3
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
    "sensitivity": "low",
    "ai_use_policy": "cautious_use",
    "confirmation_status": "confirmed",
    "profile_facts": [],
    "observations": []
  }],
  "observations": [],
  "scores": {"entity-id": 0.82},
  "match_reasons": {"entity-id": ["entity_hint"]},
  "score_breakdown": {"entity-id": {}},
  "ambiguity_detected": false,
  "debug": {}
}
```

Observation results carry `observation_id`, content, score, match reasons, sensitivity, AI-use
policy, status, and any `valid_from`, `valid_to`, `occurred_at`, and `created_at` values.

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

Suggested response policies are `natural_use`, `conditional_use`, `ask_clarifying_question`,
`no_relevant_context`, and `blocked_by_policy`. Surface buckets are deterministic and policy-driven.

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
`retrieval_hints` contains `entity_id`, `canonical_name`, aliases, and entity type. Merged source IDs
resolve to the active target entity.

## Provisional context

Provisional context is opt-in and structurally separate from every canonical field. It contains at
most five recent pending observation candidates for one exactly resolved active entity, after
user-authored evidence, content, temporal, sensitivity, contact/high-impact, and policy checks.

Each item contains:

```text
candidate_id
content
observation_type
sensitivity
valid_from / valid_to / occurred_at
created_at
label = provisional
review_status = unreviewed
write_evidence_eligible = false
```

It never enters provenance, canonical stable/recent/caution fields, retrieval evidence, or later
writes. Identity, structural, high-sensitivity, contact-like, warned, ambiguous, or non-user-grounded
candidates are excluded.

## Temporal and policy rules

- `occurred_at` is described event time.
- `valid_from` and `valid_to` are applicability bounds.
- `created_at` is storage time only.
- `never_surface` records remain blocked.
- Low confidence or ambiguity yields `ask_clarifying_question`.
- Kinlayer returns policy metadata, not polished clarification wording.
- Full episode bodies and conversations are never context outputs.

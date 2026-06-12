# Kinlayer Context Output Contract

- Status: Draft v0.2
- Parent PRD: `prd.md`
- Related docs: `api-spec.md`, `data-model.md`, `../archive/planning/interview-ledger.md`

---

## 1. Purpose

Kinlayer retrieval must return relationship context that an AI agent can use safely and consistently while preserving policy, provenance, confidence, and recency boundaries.

Kinlayer does not author final advice, message drafts, or natural-language briefings. It retrieves, scores, filters, labels, and packages context. The AI agent performs final interpretation and response generation.

Core principle:

> Kinlayer is a deterministic context packager, not an LLM situation-reasoning engine.

---

## 2. Output Layers

Kinlayer exposes three output layers.

### 2.1 Raw Retrieval Result

Low-level scored retrieval/debug layer.

Endpoint:

```http
POST /api/context/retrieve
```

Includes:

- matched entities;
- matched aliases/name signals;
- matched observations;
- semantic observation scores;
- match reasons;
- score breakdowns;
- policy filtering decisions;
- debug metadata such as active embedding model.

This is not the primary agent-facing response format. It is for debugging, scoring inspection, and retrieval UI.

### 2.2 Person Context Card

Reusable curated card for one person/entity.

Endpoint:

```http
GET /api/entities/{id}/context-card
```

Includes:

- entity identity summary;
- aliases;
- profile_facts;
- relationship_edges;
- stable_context;
- recent_context;
- communication_context;
- cautions;
- provenance_summary;
- retrieval_hints.

A Person Context Card is not a full dossier. It uses sensible default limits; full lists are served by paginated resource endpoints.

### 2.3 Context Pack

Agent-facing context package for a current user request.

Endpoint:

```http
POST /api/context/pack
```

Examples:

- “Help me reply to Alex.”
- “I’m meeting Dana tomorrow.”
- “That person contacted me again.”

Includes:

- matched focal entity/entities;
- why they were matched;
- confidence and ambiguity state;
- suggested response policy;
- direct/conditional/internal/blocked context buckets;
- recent and stable context;
- cautions;
- provenance references;
- optional debug.

A Context Pack is not a Situation Briefing Bundle. It must not contain final user-facing advice written by Kinlayer.

---

## 3. Context Pack Request Shape

Agents should send both free text and structured hints.

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

Field meanings:

- `query`: original user text.
- `situation_text`: normalized free-text situation description; primary embedding target.
- `retrieval_intent`: broad purpose such as relationship_advice, message_drafting, meeting_prep, person_lookup, graph_exploration, correction, debug.
- `desired_context`: categories to prioritize in context assembly.
- `candidate_entities`: agent-side reference resolution hints.
- `focal_entity_id`: agent-confirmed target entity, if known.
- `situation_tags`: optional weak hints only; not the main situation understanding mechanism.

---

## 4. Person Context Card Draft Schema

```json
{
  "type": "person_context_card",
  "entity": {
    "entity_id": "uuid",
    "display_name": "Alex",
    "entity_type": "person",
    "aliases": ["Alex", "알렉스"],
    "confirmation_status": "confirmed",
    "sensitivity": "medium",
    "ai_use_policy": "cautious_use"
  },
  "profile_facts": [],
  "relationship_edges": [],
  "stable_context": [],
  "recent_context": [],
  "communication_context": [],
  "cautions": [],
  "provenance_summary": [],
  "retrieval_hints": {
    "common_aliases": [],
    "recently_referenced": true,
    "last_referenced_at": "2026-06-10T00:00:00Z"
  }
}
```

Each context item should include at least:

```text
content
claim_type
confidence
sensitivity
ai_use_policy
surface_visibility
source_episode_ids or evidence refs
```

---

## 5. Raw Retrieval Result Draft Schema

```json
{
  "query": "그 사람이랑 또 연락 왔는데 애매해",
  "matched_entities": [
    {
      "entity_id": "uuid",
      "display_name": "Alex",
      "score": 0.82,
      "confidence": "high",
      "match_reasons": ["candidate_entity", "recent_mention", "alias_match"],
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
  "matched_observations": [
    {
      "observation_id": "uuid",
      "subject_entity_id": "uuid",
      "content": "...",
      "score": 0.77,
      "semantic_score": 0.83,
      "recency_score": 0.62,
      "status": "active"
    }
  ],
  "debug": {
    "semantic_enabled": true,
    "embedding_model": "dragonkue/multilingual-e5-small-ko-v2",
    "embedding_dim": 384
  }
}
```

---

## 6. Context Pack Draft Schema

```json
{
  "type": "context_pack",
  "query": "그 사람이랑 또 연락 왔는데 애매해",
  "confidence": "medium",
  "suggested_response_policy": "conditional_use",
  "matched_entities": [
    {
      "entity_id": "uuid",
      "display_name": "Alex",
      "score": 0.74,
      "confidence": "medium",
      "match_reasons": ["candidate_entity", "recent_interaction", "semantic_observation"]
    }
  ],
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
  "clarification": {
    "needed": true,
    "reason": "medium_confidence_reference_resolution"
  },
  "debug": {}
}
```

The `clarification` object may contain the reason for a clarification need, but Kinlayer should not generate polished final wording. The AI agent decides how to ask the user.

---

## 7. Surface Contract

Kinlayer must separate what the agent may retrieve from what the agent may say.

This separation is deterministic and policy-driven in MVP.

Inputs to surface computation:

```text
confirmation_status
candidate status
claim_type
confidence
sensitivity
ai_use_policy
recency
retrieval score
explicit user confirmation
```

Surface buckets:

```text
direct_surface
conditional_surface
internal_only
blocked
```

Definitions:

- `direct_surface`: safe to directly mention in response.
- `conditional_surface`: can be mentioned with uncertainty/confirmation language.
- `internal_only`: can shape the agent's reasoning but should not be stated directly.
- `blocked`: should not be used or surfaced for this request.

---

## 8. Recent Context Requirements

Recent context can include confirmed context plus policy-safe pending candidates.

Pending candidates may appear only with:

```text
status: pending
surface_mode: conditional_only
```

They must not be presented as confirmed facts.

Recent context items should have:

```text
summary/content
occurred_at or approximate_time
source_episode_id or evidence ref
claim_type
confidence
recency_score or recency_label
surface_visibility
retention_policy
```

Recent context should not be treated as permanent stable relationship knowledge unless separately accepted as an observation/pattern.

---

## 9. Retrieval Response Policy

Kinlayer suggests how the AI agent should use the result.

Allowed values:

```text
natural_use
conditional_use
ask_clarifying_question
no_relevant_context
blocked_by_policy
```

Mapping:

- No matched entity/context → `no_relevant_context`.
- All relevant context blocked → `blocked_by_policy`.
- High confidence + direct_surface exists → `natural_use`.
- Medium confidence or only conditional_surface exists → `conditional_use`.
- Low confidence or ambiguity guard triggered → `ask_clarifying_question`.
- If only internal_only context exists, agent may use it for reasoning but must not directly surface it.

---

## 10. Confidence and Scoring Notes

Initial MVP scoring weights are code constants, not runtime config:

```text
entity_hint_score: 0.25
alias_name_score: 0.20
semantic_observation_score: 0.20
recency_score: 0.15
graph_proximity_score: 0.10
confirmation_policy_score: 0.10
```

These weights are not assumed optimal. Dogfood/evaluation should tune them after MVP.

Base confidence thresholds:

```text
high >= 0.75
medium >= 0.45
low < 0.45
```

Ambiguity guard prevents/downgrades high confidence when:

- top1-top2 score gap is too small;
- reference_resolution confidence is low;
- focal_entity_id is absent with pronoun/implicit reference;
- policy/sensitivity conflicts exist.

---

## 11. Embedding Scope

MVP embedding/vector retrieval is required and scoped to observations.

Embed:

```text
observations.content
query / situation_text at retrieval time
```

Do not embed in MVP:

```text
edges
entity_facts
candidates
episodes/full conversations
```

Supported providers:

```text
OpenAI-compatible embeddings
local sentence-transformers
```

Local default:

```text
dragonkue/multilingual-e5-small-ko-v2
```

Local high-quality option:

```text
nlpai-lab/KURE-v1
```

---

## 12. Closed Decisions

- `Context Pack` replaces older `Situation Context Bundle` / `Situation Briefing Bundle` terminology.
- `/api/context/pack` replaces older `/api/context/situation` naming.
- Kinlayer does not perform open-ended LLM situation understanding.
- Agents provide structured hints plus free-text `situation_text`; Kinlayer uses deterministic hybrid retrieval and policy packaging.

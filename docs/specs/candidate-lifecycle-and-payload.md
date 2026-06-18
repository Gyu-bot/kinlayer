# Kinlayer Candidate Lifecycle and Payload Contract

- Status: Draft v0.1
- Parent PRD: `prd.md`
- Related docs: `ontology-design.md`, `context-output-contract.md`, `../agents/agent-write-instruction-pack.md`

---

## 1. Purpose

Kinlayer allows AI agents, connectors, importers, and users to propose relationship context changes without immediately polluting canonical context.

The candidate system is the control boundary between detected context and trusted context.

Agents and adapters should follow `../agents/agent-write-instruction-pack.md` when selecting
candidate types, controlled ontology values, evidence excerpts, and no-write behavior.

Core principle:

> AI agents may propose relationship context, but candidate review determines what becomes canonical and what can be retrieved or surfaced as trusted context.

Product boundary:

> AI agents interpret current-turn user-authored text and propose candidates or explicit corrections; Kinlayer validates, stores, retrieves, reviews, and canonicalizes relationship context.

Kinlayer does not run an LLM for post-turn extraction or decide open-ended personhood,
fictional/public-figure status, or relationship relevance. Agent-submitted candidates and
corrections must use current-turn user-authored evidence excerpts. Do not use assistant messages,
tool output, retrieved context packs/cards, system/developer/skill prompts, logs, compacted
summaries, previous memory output, or agent-generated interpretations as evidence.

Agents should produce no write or a clarification path for fictional characters, public figures,
hypothetical examples, generic groups/professions, AI agents/bots/models, the protected self as an
ordinary person entity, and pronoun-only mentions without a reliable current-turn user-provided
identifier.

---

## 2. Candidate Granularity

Candidates are proposed change items, not only proposed entities.

A candidate may propose:

- a new entity;
- a new alias for an existing entity;
- a profile/property field update;
- a relationship edge;
- an observation/claim;
- a merge;
- a conflict/dispute;
- a supersede/replacement of existing context.

A confirmed entity can still receive pending candidate aliases, observations, edges, conflicts, or supersede proposals.

---

## 3. MVP Lifecycle Statuses

MVP statuses:

```text
pending
accepted
edited_accepted
rejected
archived
needs_clarification
superseded
```

### Status meanings

#### `pending`

Created and awaiting review.

#### `accepted`

Accepted as-is. Canonical write completed.

#### `edited_accepted`

User edited payload or metadata before accepting. Canonical write completed using edited version.

#### `rejected`

Rejected as incorrect, unwanted, unsafe, or not useful.

Rejected candidates must not contribute to confirmed retrieval.

#### `archived`

Set aside without confirming or rejecting. Useful when the candidate may be relevant later but should not currently affect canonical context.

#### `needs_clarification`

Candidate appears plausible but requires a user answer before accept/reject.

#### `superseded`

Candidate was replaced by a newer, better, or merged candidate/canonical record.

---

## 4. Accept Behavior

MVP uses immediate canonical write.

Flow:

```text
candidate pending
→ user accepts
→ canonical row created/updated immediately
→ candidate.status = accepted or edited_accepted
→ candidate.canonical_record_ref = <table>:<id>
```

Batch review / changeset apply is not MVP.

---

## 5. Candidate Table Draft

Suggested table:

```text
candidates
- id
- candidate_type
- target_entity_id nullable
- payload jsonb
- confidence
- sensitivity
- suggested_action
- status
- created_by
- created_at
- resolved_at
- resolved_by
- resolution_note
- canonical_record_ref
- supersedes_candidate_id nullable
- supersedes_record_ref nullable
```

Candidate evidence is stored separately:

```text
candidate_evidence
- candidate_id
- episode_id
- excerpt
- confidence
- created_at
```

Candidate evidence responses may also include source metadata resolved from the linked episode:

```text
source_type
source_ref
source_description
body_hash
actor
```

Implementation note:

- DB stores `payload` as JSONB.
- API/Pydantic layer validates payload by `candidate_type`.
- This avoids both untyped chaos and over-normalized candidate tables.
- Use `candidate_evidence`, not `candidates.evidence_episode_ids`, as the canonical evidence model.
- Agent-submitted candidates require at least one evidence item. Manual user-created candidates may
  omit evidence when explicitly entered by the user.
- Agent evidence must reference an existing episode, include a non-empty user-authored excerpt,
  confidence in `[0, 1]`, and enough episode provenance to trace source type/ref. Agent runtimes
  should place stable `source_message_id` and `source_turn_id` values in `source_ref` or structured
  source metadata when available.

---

## 6. Common Candidate Envelope

All candidate submissions use a common envelope.

```json
{
  "candidate_type": "observation",
  "target_entity_id": "...",
  "payload": {},
  "evidence": [
    {
      "episode_id": "...",
      "excerpt": "...",
      "confidence": 0.8
    }
  ],
  "confidence": 0.72,
  "sensitivity": "medium",
  "suggested_action": "review",
  "created_by": "ai_agent"
}
```

Required common fields:

```text
candidate_type
payload
confidence
created_by
```

Strongly recommended fields:

```text
evidence[]
sensitivity
suggested_action
target_entity_id when candidate applies to existing entity
```

---

## 7. Typed Payload Schemas

### 7.1 `new_entity`

```json
{
  "entity_type": "person",
  "display_name": "Alex",
  "canonical_name": "alex",
  "properties": {},
  "ai_use_policy": "cautious_use",
  "sensitivity": "medium"
}
```

Accept result:

```text
entities row created
candidate.canonical_record_ref = entities:<id>
```

### 7.2 `alias`

```json
{
  "entity_id": "...",
  "alias": "former coworker",
  "confidence": 0.74
}
```

Accept result:

```text
entity_aliases row created
candidate.canonical_record_ref = entity_aliases:<id>
```

### 7.3 `profile_field`

```json
{
  "entity_id": "...",
  "field_path": "profile.email",
  "fact_type": "email",
  "content": "alex@example.com",
  "value": {
    "kind": "work",
    "email": "alex@example.com"
  },
  "claim_type": "fact",
  "sensitivity": "high",
  "ai_use_policy": "ask_before_use"
}
```

Accept result:

```text
entity_facts row created
candidate.canonical_record_ref = entity_facts:<id>
```

Structured person profile fields use `entity_facts` as canonical storage. Supported structured
fact types include `legal_name`, `birth_date`, `phone`, `email`, `address`, `organization`,
`role`, and `memo`. Profile candidates may still use `important_context` for general notes.

### 7.4 `relationship_edge`

```json
{
  "from_entity_id": "...",
  "to_entity_id": "...",
  "relation_type": "former_coworker",
  "directed": false,
  "claim_text": "Alex is the user's former coworker.",
  "claim_type": "fact",
  "properties": {}
}
```

Accept result:

```text
entity_edges row created
edge_evidence rows created
candidate.canonical_record_ref = entity_edges:<id>
```

Validation:

- `relation_type` must exist in `allowed_edge_types`.
- endpoint entity types must match registry.
- observation-like relation types should be rejected unless explicitly allowed by registry.

### 7.5 `observation`

```json
{
  "subject_entity_id": "...",
  "related_entity_ids": ["..."],
  "observation_type": "communication_preference",
  "content": "Alex tends to prefer concise follow-ups.",
  "claim_type": "pattern",
  "ai_use_policy": "cautious_use",
  "sensitivity": "medium",
  "occurred_at": null,
  "valid_from": null,
  "valid_to": null
}
```

Accept result:

```text
observations row created
observation_evidence rows created
candidate.canonical_record_ref = observations:<id>
```

Temporal behavior:

- `occurred_at` is the event date/time for point-in-time observations.
- `valid_from` and `valid_to` are the applicability range for period-bound context.
- Candidate submit, accept, and edit-accept preserve these temporal fields into canonical
  `observations`.

Quality behavior:

- Structurable facts and durable relationships should be submitted as typed records instead of long
  observation prose.
- Agent write validation may return warnings for overlong content, dangling references, missing
  temporal scope, or typed-record boundary review. These warnings are diagnostics; Kinlayer does not
  infer or construct a replacement fact/edge payload.

### 7.6 `merge`

```json
{
  "source_entity_id": "...",
  "target_entity_id": "...",
  "reason": "Alias and recent references suggest these may be the same person.",
  "fields_to_merge": ["aliases", "observations"],
  "merge_plan": {
    "aliases": "copy_non_conflicting",
    "profile_facts": "copy_non_conflicting",
    "edges": "repoint_without_self_or_duplicate_edges",
    "observations": "repoint_related_entities",
    "conflicts": "create_conflict_candidates"
  },
  "field_conflict_policy": {
    "display_name": "keep_target",
    "canonical_name": "keep_target",
    "sensitivity": "use_more_restrictive",
    "ai_use_policy": "use_more_restrictive"
  },
  "risk_notes": ["Both entities have similar names but different contexts."],
  "merged_entity_ref": "entities:<target_id>"
}
```

Review result:

```text
T041 defines the contract only.
T043 implements atomic accept/merge execution.
```

Merge rules:

- AI agents may propose merge candidates and may accept them only after explicit current-turn user
  confirmation for the exact source-target merge. The accept request should identify
  `resolved_by = ai_agent` and include a `resolution_note` summarizing the user confirmation.
- Pronoun-only or weak identity similarity may create a clarification/merge candidate, not an
  accepted merge.
- Protected self cannot be source or target for normal person merge unless both IDs refer to the same
  protected self row.
- Execution must preserve auditability and keep the source inspectable as merged/deprecated, not deleted.
- After execution, retrieval/context/graph should use the target entity and not rank the source as a
  separate active person.

### 7.7 `conflict`

```json
{
  "record_refs": ["observations:...", "observations:..."],
  "conflict_type": "contradiction",
  "description": "Two observations disagree about Alex's preferred communication style."
}
```

Accept result:

```text
records marked disputed or conflict record created, depending on final data model
```

### 7.8 `supersede`

```json
{
  "old_record_ref": "observations:...",
  "new_payload": {
    "content": "Alex now prefers direct scheduling instead of casual check-ins.",
    "claim_type": "pattern",
    "observation_type": "communication_preference"
  },
  "reason": "More recent interaction updated the prior pattern."
}
```

Accept result:

```text
old record deprecated/superseded
new canonical record created
candidate.canonical_record_ref = <new_record_ref>
```

---

## 8. API Actions

Minimum candidate API actions:

```http
POST /api/candidates
GET /api/candidates
GET /api/candidates/{id}
POST /api/candidates/{id}/accept
POST /api/candidates/{id}/edit-accept
POST /api/candidates/{id}/reject
POST /api/candidates/{id}/archive
POST /api/candidates/{id}/needs-clarification
POST /api/candidates/{id}/supersede
```

Action requirements:

- `accept` performs immediate canonical write.
- `edit-accept` validates edited payload before canonical write.
- `reject/archive/needs_clarification` do not create canonical records.
- All terminal or review actions should set `resolved_at` and `resolved_by` where applicable.

---

## 9. Retrieval Interaction

Confirmed canonical records participate in normal retrieval.

Pending candidates may participate only in policy-safe recent context when the retrieval endpoint explicitly allows it.

Rules:

```text
accepted / edited_accepted → canonical record participates normally
pending → conditional only, if policy-safe and recent-context eligible
rejected → excluded
archived → excluded by default
needs_clarification → conditional/debug only
superseded → excluded unless audit/debug mode
```

---

## 10. Open Questions

1. Should candidate evidence use `uuid[]` on candidates or a `candidate_evidence` join table?
2. Should merge execution be fully implemented in MVP or treated as review-only/manual?
3. Should profile fields be embedded in `entities.properties` or normalized as separate records?
4. Should `needs_clarification` generate suggested user-facing questions or just mark state?
5. Should candidates support bulk creation in one request for agent post-turn extraction?

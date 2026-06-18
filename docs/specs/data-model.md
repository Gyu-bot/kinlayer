# Kinlayer Data Model

- Status: Draft v0.1
- Parent PRD: `prd.md`
- Related docs: `ontology-design.md`, `candidate-lifecycle-and-payload.md`, `context-output-contract.md`

---

## 1. Purpose

This document defines the MVP canonical data model for Kinlayer.

Kinlayer is a single-user, local-first relationship context layer for AI agents. The data model must support:

- agent-conversation-first context accumulation;
- user-controlled correction and review;
- candidate-to-canonical workflows;
- provenance through episodes and bounded evidence excerpts;
- policy-aware retrieval;
- person-first relationship graph behavior;
- future ontology/graph expansion without overbuilding MVP.

---

## 2. Global MVP Decisions

### 2.1 Single-user local workspace

MVP assumes one local Kinlayer instance owns one relationship context workspace.

No built-in auth, user accounts, or workspace membership in MVP.

Do not add `workspace_id` to every table in MVP unless implementation later needs an internal constant.

Optional local bearer-token protection is runtime configuration, not a user/session table.

### 2.2 Protected self entity

Kinlayer initializes a protected `self` entity.

```text
entity_type = person
system_role = self
is_system = true
```

The self entity:

- cannot be deleted;
- should not be merged without explicit protected logic;
- appears as the owner/self node in relationship edges and graph view.

### 2.3 Entity-generic schema, person-first behavior

Schema supports generic entities, but MVP fully supports only `person` workflows.

Reserved/experimental entity types may exist in registry but should not become first-class MVP UX.

---

## 3. Enums / Controlled Values

These should be enforced through code and/or active ontology registry.

### Entity types

```text
person = supported
organization = reserved/experimental
place = reserved/experimental
event = reserved/experimental
topic = reserved/experimental
account = reserved/experimental
```

### Created by

```text
user
ai_agent
connector
import
system
```

### Confirmation/status values

Entity-level:

```text
confirmed
candidate
rejected
deprecated
merged
disputed
```

Canonical record status:

```text
active
deprecated
disputed
superseded
deleted
```

Candidate status:

```text
pending
accepted
edited_accepted
rejected
archived
needs_clarification
superseded
```

### Claim type

```text
fact
inference
preference
pattern
```

### Sensitivity

```text
low
medium
high
```

### AI use policy

```text
freely_use
cautious_use
ask_before_use
never_surface
```

### Retrieval-time surface buckets

```text
direct_surface
conditional_surface
internal_only
blocked
```

---

## 4. Core Tables

## 4.1 `entities`

Represents people/entities in the relationship graph. MVP behavior is person-first.

```text
entities
- id uuid primary key
- entity_type text not null
- display_name text not null
- canonical_name text
- properties jsonb not null default '{}'
- confirmation_status text not null default 'confirmed'
- status text not null default 'active'
- sensitivity text not null default 'medium'
- ai_use_policy text not null default 'cautious_use'
- created_by text not null
- system_role text nullable              # e.g. self
- is_system boolean not null default false
- first_seen_at timestamptz nullable
- last_referenced_at timestamptz nullable
- created_at timestamptz not null
- updated_at timestamptz not null
```

Notes:

- `properties` is for lightweight UI metadata only.
- Relationship-relevant stable facts belong in `entity_facts`.
- protected self entity uses `system_role = 'self'` or equivalent.

Indexes:

```text
(entity_type)
(canonical_name)
(confirmation_status)
(system_role) unique where system_role = 'self'
pg_trgm index on display_name/canonical_name as needed
```

---

## 4.2 `entity_aliases`

Stores alternate names, nicknames, handles, or reference phrases for an entity.

```text
entity_aliases
- id uuid primary key
- entity_id uuid references entities(id)
- alias text not null
- normalized_alias text
- status text not null default 'active'
- confidence numeric not null default 1.0
- source_candidate_id uuid nullable references candidates(id)
- created_by text not null
- created_at timestamptz not null
- updated_at timestamptz not null
```

Notes:

- AI-suggested aliases should normally enter candidates first.
- Alias fuzzy matching uses exact/normalized match plus pg_trgm.

Indexes:

```text
(entity_id)
(normalized_alias)
pg_trgm index on alias/normalized_alias
```

---

## 4.3 `entity_facts`

Stores stable relationship-relevant facts about an entity that need provenance, policy, and confidence.

```text
entity_facts
- id uuid primary key
- entity_id uuid references entities(id)
- fact_type text not null                 # e.g. job, organization, birthday, role_note
- content text not null
- value jsonb nullable                    # optional structured value
- claim_type text not null
- confidence numeric not null
- sensitivity text not null default 'medium'
- ai_use_policy text not null default 'cautious_use'
- status text not null default 'active'
- valid_from timestamptz nullable
- valid_to timestamptz nullable
- source_candidate_id uuid nullable references candidates(id)
- created_by text not null
- created_at timestamptz not null
- updated_at timestamptz not null
```

Notes:

- `profile_field` candidates usually canonicalize into `entity_facts`.
- Lightweight presentation-only fields stay in `entities.properties`.

---

## 4.4 `entity_edges`

Represents durable typed relationships between entities.

```text
entity_edges
- id uuid primary key
- from_entity_id uuid references entities(id)
- to_entity_id uuid references entities(id)
- relation_type text not null
- directed boolean not null
- claim_text text not null
- claim_type text not null
- properties jsonb not null default '{}'
- confidence numeric not null
- sensitivity text not null default 'medium'
- ai_use_policy text not null default 'cautious_use'
- status text not null default 'active'
- valid_from timestamptz nullable
- valid_to timestamptz nullable
- invalidated_by_edge_id uuid nullable references entity_edges(id)
- source_candidate_id uuid nullable references candidates(id)
- created_by text not null
- first_seen_at timestamptz nullable
- last_seen_at timestamptz nullable
- created_at timestamptz not null
- updated_at timestamptz not null
```

Notes:

- `relation_type` must exist in `allowed_edge_types`.
- Graph, context card, and retrieval read paths exclude active legacy edge rows whose
  `relation_type` is missing from active `allowed_edge_types` or whose endpoint entity types no
  longer match the active edge type; diagnostics report those rows for explicit repair decisions.
- Pending relationship proposals live in `candidates`, not active `entity_edges`.
- Edge types should remain structural. Advisory/contextual items belong in `observations`.

---

## 4.5 `observations`

Stores sentence-like context useful for agent reasoning, context cards, and context packs.

```text
observations
- id uuid primary key
- subject_entity_id uuid references entities(id)
- observation_type text not null
- content text not null
- claim_type text not null
- confidence numeric not null
- sensitivity text not null default 'medium'
- ai_use_policy text not null default 'cautious_use'
- status text not null default 'active'
- valid_from timestamptz nullable
- valid_to timestamptz nullable
- occurred_at timestamptz nullable         # especially for recent_interaction
- recency_weight numeric nullable
- embedding vector nullable                # pgvector semantic retrieval
- embedding_status text not null default 'pending'
- embedding_error text nullable
- embedding_model text nullable
- embedding_dim integer nullable
- embedding_created_at timestamptz nullable
- source_candidate_id uuid nullable references candidates(id)
- created_by text not null
- created_at timestamptz not null
- updated_at timestamptz not null
```

Related entities are represented through a join table:

```text
observation_entities
- id uuid primary key
- observation_id uuid references observations(id)
- entity_id uuid references entities(id)
- role text not null                       # subject, related, mentioned, speaker, target
- confidence numeric nullable
- created_at timestamptz not null
```

Observation type examples:

```text
stable_fact
communication_preference
relationship_pattern
care_point
caution
recent_interaction
user_feeling
follow_up_context
```

Notes:

- One table covers both stable and recent context.
- Retrieval buckets observations into `stable_context` vs `recent_context` at query time.
- Repeated recent interactions can produce pattern observations via candidate flow.

---

## 4.6 `episodes`

Stores source/provenance metadata and bounded excerpts. Kinlayer MVP is not a raw conversation archive.

```text
episodes
- id uuid primary key
- source_type text not null                # agent_conversation, manual_entry, connector, import, correction
- source_ref text nullable
- source_description text nullable
- body_excerpt text not null
- body_hash text not null
- actor text not null
- occurred_at timestamptz nullable
- ingested_at timestamptz not null
- sensitivity text not null default 'medium'
- retention_policy text not null default 'excerpt_only'
- created_at timestamptz not null
- updated_at timestamptz not null
```

Allowed MVP retention policies:

```text
metadata_only
excerpt_only
```

Out of MVP:

```text
full_body
```

Notes:

- Full raw body storage is not MVP.
- Reliability comes from correction/supersede/deprecate flows and bounded explainability.

---

## 4.7 `candidates`

Stores proposed change items awaiting review or resolution.

```text
candidates
- id uuid primary key
- candidate_type text not null
- target_entity_id uuid nullable references entities(id)
- payload jsonb not null
- confidence numeric not null
- sensitivity text not null default 'medium'
- suggested_action text nullable
- status text not null default 'pending'
- created_by text not null
- created_at timestamptz not null
- resolved_at timestamptz nullable
- resolved_by text nullable
- resolution_note text nullable
- canonical_record_ref text nullable
- supersedes_candidate_id uuid nullable references candidates(id)
- supersedes_record_ref text nullable
```

Notes:

- `payload` is JSONB in DB.
- API/Pydantic validates `payload` by `candidate_type`.
- Accepting a candidate immediately writes canonical records.
- `merge` candidates are review-only until the person merge execution API is implemented.
- Batch changesets are not MVP.

### Person merge contract

Person merge is a reviewed canonical maintenance operation. AI agents may propose
`merge` candidates, but they must not directly merge people.

Merge payload fields:

- `source_entity_id`: possible duplicate entity to retire from active person workflows.
- `target_entity_id`: canonical entity that should remain active.
- `merge_plan`: explicit plan for aliases, facts, edges, observations, evidence, and conflicts.
- `field_conflict_policy`: per-field decisions for display name, canonical name, sensitivity,
  AI use policy, profile facts, aliases, active edges, and observations.
- `merged_entity_ref`: durable reference from the source entity to the target after execution.

Protected self constraints:

- normal person merge rejects any source or target with `system_role = self`;
- the only allowed self/self case is the same physical protected self row;
- future protected-self repair flows need a separate contract.

After merge execution, source rows remain inspectable but are not active people. Retrieval,
context cards, and graph reads should resolve old source IDs to the target or hide the source
from active results while preserving aliases and provenance under the target.

---

## 5. Evidence Tables

Typed evidence tables preserve FK integrity and avoid polymorphic references.

## 5.1 `candidate_evidence`

```text
candidate_evidence
- id uuid primary key
- candidate_id uuid references candidates(id)
- episode_id uuid references episodes(id)
- excerpt text nullable
- confidence numeric nullable
- created_at timestamptz not null
```

## 5.2 `entity_fact_evidence`

```text
entity_fact_evidence
- id uuid primary key
- entity_fact_id uuid references entity_facts(id)
- episode_id uuid references episodes(id)
- excerpt text nullable
- confidence numeric nullable
- created_at timestamptz not null
```

## 5.3 `edge_evidence`

```text
edge_evidence
- id uuid primary key
- edge_id uuid references entity_edges(id)
- episode_id uuid references episodes(id)
- excerpt text nullable
- confidence numeric nullable
- created_at timestamptz not null
```

## 5.4 `observation_evidence`

```text
observation_evidence
- id uuid primary key
- observation_id uuid references observations(id)
- episode_id uuid references episodes(id)
- excerpt text nullable
- confidence numeric nullable
- created_at timestamptz not null
```

---

## 6. Ontology Registry Tables

See `ontology-design.md` for full semantics.

Implemented MVP registry tables:

```text
ontology_registry_values
allowed_edge_types
allowed_observation_types
```

`ontology_registry_values` stores controlled values by category, including `entity_type`, `fact_type`, `claim_type`, `sensitivity`, `ai_use_policy`, `retention_policy`, `evidence_source_type`, and `candidate_type`.

```text
ontology_registry_values
- id uuid primary key
- category text not null
- value text not null
- label text not null
- description text nullable
- support_level text not null
- is_active boolean not null default true
- sort_order integer not null default 0
- created_at timestamptz not null
- updated_at timestamptz not null
```

`allowed_edge_types` is especially important:

```text
allowed_edge_types
- id uuid primary key
- relation_type text not null
- from_entity_type text not null
- to_entity_type text not null
- directed_default boolean not null
- inverse_relation_type text nullable
- allowed_properties_schema jsonb nullable
- description text nullable
- examples jsonb nullable
- active boolean not null default true
- created_at timestamptz not null
- updated_at timestamptz not null
```

---

## 7. Correction Model

Explicit user corrections in agent conversation may apply directly.

Flow:

```text
user explicitly corrects agent
→ agent submits trusted correction apply
→ correction episode created with bounded excerpt/hash
→ old canonical record deprecated/superseded
→ new canonical record active
→ evidence linked to correction episode
```

Agent-inferred corrections/conflicts must enter candidate review instead.

---

## 8. Retrieval Implications

Normal retrieval should include:

- active confirmed entities/facts/edges/observations;
- policy-safe pending recent candidates only when explicitly allowed by retrieval request;
- no rejected candidates;
- no superseded/deprecated records unless debug/audit mode.

Retrieval response computes:

```text
score
confidence band
suggested_response_policy
surface bucket
```

Stored policy metadata:

```text
sensitivity
ai_use_policy
```

Computed retrieval-time buckets:

```text
direct_surface
conditional_surface
internal_only
blocked
```

---

## 9. Agent Write Operation Audits

`agent_write_operation_audits` is the persisted operational record for AI-agent write attempts.

It is not a raw log sink. It stores bounded, structured metadata that can be exported for later review with a coding agent:

```text
agent_write_operation_audits
- id uuid primary key
- operation_type text not null
- source_path text not null
- actor text not null
- result_status text not null
- api_error_code text nullable
- request_summary jsonb not null
- diagnostics jsonb not null
- related_refs jsonb not null
- candidate_id uuid nullable
- correction_id uuid nullable
- episode_id uuid nullable
- canonical_record_ref text nullable
- bounded_excerpt text nullable
- created_at timestamptz not null
- updated_at timestamptz not null
```

Rules:

- include agent candidate submit/accept/edit-accept and correction apply attempts;
- include direct edge create/update attempts when `created_by` or the existing edge actor can be traced;
- include rejected validation attempts when the route can safely identify `created_by = ai_agent`;
- relationship write audit rows include submitted `relation_type`, endpoint entity refs/types when
  available, and an `edge_type_match` diagnostic such as `active_allowed_edge_type`,
  `missing_allowed_edge_type`, or `endpoint_type_mismatch`;
- do not store full prompts, bearer tokens, API keys, raw conversation transcripts, or unbounded request bodies;
- retrieval/context-pack reads are not agent write operations.

---

## 10. Closed Implementation Decisions

1. Ontology seed values live in `kinlayer_backend.services.ontology.REGISTRY_SEEDS`.
2. `entity_facts.fact_type` is registry-backed.
3. `canonical_record_ref` remains string-based in the form `table:id`.
4. MVP indexes cover entity type, canonical name, confirmation/status, aliases, facts, edges, observations, episodes, and evidence lookup paths used by current retrieval and smoke checks.
5. Agent write operation export uses newline-delimited JSON with a manifest followed by bounded operation records.

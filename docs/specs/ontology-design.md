# Kinlayer Ontology Design

- Status: Draft v0.1
- Scope: Ontology registry and relationship-edge design for Kinlayer
- Parent PRD: `prd.md`
- Related docs: `../agents/agent-write-instruction-pack.md`

---

## 1. Purpose

Kinlayer needs ontology support, but MVP must not become a formal semantic-web project.

The ontology design exists to keep relationship context controlled, validated, explainable, and extensible while preserving a practical local-first implementation.

For agent write behavior, `../agents/agent-write-instruction-pack.md` is the operational instruction
pack. It treats UI relationship type, API `relation_type`, candidate `relationship_edge.relation_type`,
and graph edge labels as ontology edge types from `allowed_edge_types`.

Core principle:

> Kinlayer ontology is an active registry for validation, filtering, retrieval, and UI explanation — not an RDF/OWL knowledge graph in MVP.

---

## 2. Design Position

Kinlayer uses:

- Postgres as the canonical source of truth.
- Entity-generic schema with person-first MVP behavior.
- Registry-backed allowed types for entities, edges, claims, candidates, sensitivity, and AI-use policy.
- Relationship edges for durable relationship structure.
- Observations for situational, advisory, or behavior/context knowledge.

Kinlayer does not use in MVP:

- RDF/OWL as canonical model.
- Neo4j/Kuzu as canonical source.
- Automatic ontology inference.
- Open-ended relation strings without registry validation.

---

## 3. Entity Model and Ontology Boundary

Kinlayer uses a generic `entities` table for long-term graph/ontology compatibility, while MVP behavior is person-first.

### MVP support level

```text
person = fully supported
organization = reserved / experimental
place = reserved / experimental
event = reserved / experimental
topic = reserved / experimental
account = reserved / experimental
```

MVP UI, CLI, retrieval, and context-card assembly should treat `person` as the only first-class workflow unless explicitly marked experimental.

### Why not person-only tables?

Person-only tables make MVP simple but create later migration pressure for organization/place/topic/event relationships. A generic entity table keeps relationship edges and observations stable while limiting MVP product behavior to people.

---

## 4. Core Distinction: Edges vs Observations

This is the most important ontology boundary.

```text
entity_edges = durable relationship structure
observations = situational/advisory/contextual knowledge
```

### Use `entity_edges` for

- stable social/professional/family relationships;
- durable graph structure;
- relationship claims that can be represented as typed links between entities;
- relationship facts/inferences with evidence.

Examples:

```text
User --former_coworker--> Alex
Alex --introduced_by--> Jamie
User --client_contact--> Dana
```

### Use `observations` for

- communication preferences;
- emotional salience;
- reply strategy;
- cautions;
- recent interaction interpretation;
- advice-like or situation-specific context;
- anything better expressed as a sentence than a graph edge.

Examples:

```text
Alex tends to prefer concise follow-ups.
Dana is sensitive to last-minute schedule changes.
Avoid bringing up the previous conflict unless the user asks directly.
The last interaction felt ambiguous to the user.
```

### Anti-pattern

Do not turn every useful context item into an edge.

Bad edge types for MVP:

```text
avoid_topic
follow_up_needed
emotionally_salient
prefers_short_replies
reply_strategy
sensitive_subject
```

These belong in observations unless a later ontology pass proves they should become typed relationships.

---

## 5. `entity_edges` Specification

`entity_edges` represent actual relationship instances between two entities.

Suggested table:

```text
entity_edges
- id
- from_entity_id
- to_entity_id
- relation_type
- directed
- claim_text
- claim_type
- properties
- confidence
- status
- valid_from
- valid_to
- invalidated_by_edge_id
- created_by
- source_candidate_id
- created_at
- updated_at
```

### Field notes

#### `from_entity_id`, `to_entity_id`

The two endpoints of the relationship.

#### `relation_type`

Machine-readable relationship type. Must be defined in the ontology registry.

#### `directed`

Whether direction matters for this relationship instance.

Examples:

- `friend`: usually undirected.
- `reports_to`: directed.
- `introduced_by`: directed.

#### `claim_text`

Human-readable relationship claim.

Example:

```text
Alex is the user's former coworker.
```

The relation type is for machines; `claim_text` is for review, explanation, and provenance display.

#### `claim_type`

What kind of claim the edge represents.

```text
fact
inference
preference
pattern
```

For edges, `fact` and `inference` are expected to be common; `preference` and `pattern` should usually be observations unless there is a clear graph-relationship use.

#### `properties`

Relation-type-specific structured metadata. Should be validated against the relation type's `allowed_properties_schema` when possible.

#### `status`

Accepted edge lifecycle state.

Recommended MVP statuses:

```text
active
deprecated
disputed
superseded
deleted
```

Pending proposed relationships should normally live in `candidates`, not as `entity_edges.status = candidate`.

#### `source_candidate_id`

Candidate item that produced this edge, when applicable.

---

## 6. Edge Evidence

Relationship edges need provenance just like observations.

Suggested table:

```text
edge_evidence
- edge_id
- episode_id
- excerpt
- confidence
- created_at
```

A single edge can have multiple pieces of evidence across time.

Example:

```text
Edge: User --former_coworker--> Alex
Evidence A: user stated it in an agent conversation
Evidence B: imported relationship map also says former coworker
```

---

## 7. Allowed Edge Type Registry

`allowed_edge_types` defines which relationship types may be used and how they behave.

Suggested table:

```text
allowed_edge_types
- id
- relation_type
- from_entity_type
- to_entity_type
- directed_default
- inverse_relation_type
- allowed_properties_schema
- description
- examples
- active
- created_at
- updated_at
```

### Field notes

#### `relation_type`

Canonical string used in `entity_edges.relation_type`.

#### `from_entity_type`, `to_entity_type`

Allowed endpoint entity types.

MVP examples mostly use:

```text
person -> person
```

#### `directed_default`

Default directionality for this relationship type.

#### `inverse_relation_type`

Optional inverse type.

Examples:

```text
reports_to inverse manager_of
introduced_by inverse introduced
```

For symmetric relationships, inverse can be null or self.

#### `allowed_properties_schema`

JSON Schema-like object describing allowed `properties` for edges of this type.

MVP may start permissive but should define the field to avoid later migration.

---

## 8. Recommended MVP Edge Types

MVP should keep edge types narrow and structural.

### Social/professional structural edges

```text
knows
friend
family
acquaintance
coworker
former_coworker
client_contact
vendor_contact
```

### Directional work/social edges

Prefer direction-explicit names.

```text
reports_to
manager_of
introduced_by
referred_by
collaborated_with
```

### Dating/romantic structural edges

Keep these structural. Emotional/advisory dating context should remain observations.

```text
dating_interest
dating
former_dating
romantic_partner
former_partner
introduced_for_dating
matched_on_app
```

### Deferred / observation-preferred concepts

Do not add as MVP edge types unless a later review explicitly promotes them.

```text
avoid_topic
follow_up_needed
emotionally_salient
communication_preference
reply_strategy
sensitive_subject
has_crush_on
ambiguous_interest
avoid_pressure
high_expectation_risk
dating_anxiety
needs_expectation_setting
```

---

## 9. Other Ontology Registry Tables

MVP should also define registries for core controlled values.

### `allowed_entity_types`

```text
allowed_entity_types
- entity_type
- support_level: supported | reserved | experimental | disabled
- description
- allowed_properties_schema
- active
```

### `allowed_claim_types`

```text
allowed_claim_types
- claim_type
- description
- default_review_requirement
- active
```

Initial values:

```text
fact
inference
preference
pattern
```

### `allowed_observation_types`

Examples:

```text
communication_preference
relationship_context
recent_interaction
caution
care_point
user_preference_about_person
```

### `allowed_candidate_types`

Initial values:

```text
new_entity
alias
profile_field
relationship_edge
observation
merge
conflict
supersede
```

### `allowed_sensitivity_levels`

Initial values:

```text
low
medium
high
```

### `allowed_ai_use_policies`

Initial values:

```text
freely_use
cautious_use
ask_before_use
never_surface
```

---

## 10. Candidate-to-Edge Flow

Pending proposed relationships should be represented as candidate items first.

Flow:

```text
AI detects possible relationship
→ candidates row created with candidate_type = relationship_edge
→ user reviews candidate
→ accept or edit_accept
→ entity_edges row created
→ edge_evidence rows created
→ candidate status becomes accepted or edited_accepted
```

`entity_edges` should represent accepted/canonical relationship facts or inferences, not unresolved suggestions.

---

## 11. Validation Rules

MVP validation should enforce:

1. `entity_edges.relation_type` exists in `allowed_edge_types` and is active.
2. `from_entity.entity_type` and `to_entity.entity_type` match the allowed edge type.
3. If `directed` is omitted, use `allowed_edge_types.directed_default`.
4. `claim_type` exists in `allowed_claim_types`.
5. Pending AI-generated relationship suggestions enter `candidates`, not directly active `entity_edges`.
6. Accepted AI-generated edges must have at least one evidence episode or explicit user confirmation.
7. Observation-like concepts should not be accepted as edges unless the edge type registry allows them.
8. Edge create/update, relationship-edge candidate resolution, and correction apply paths should
   record bounded write diagnostics for accepted and rejected AI-agent relation types.
9. `/api/ontology/edge-type-diagnostics` and `kinlayer ontology edge-diagnostics` report existing
   invalid legacy edge rows without rewriting them.

---

## 12. Open Questions

1. Should `user_self` be represented as a special person entity?
2. Should `family` be a generic edge type or split into parent/sibling/spouse/etc. later?
3. Should relation type registry be editable in the Web UI during MVP, or seed-only through migrations/config?
4. Should `properties` validation be strict from day one or warning-only?
5. How should inverse edges be materialized: stored explicitly or computed through registry?
6. Should `topic` remain tags/properties only in MVP, or be allowed as experimental entity type?

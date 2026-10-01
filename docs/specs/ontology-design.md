# Kinlayer Ontology Design

> Current write contract: [Agent Write Contract](../agents/agent-write-instruction-pack.md).
> The 2026-10-01 revision separates claim basis from observation topic and removes candidate-first
> approval and AI-use-policy gating. Earlier physical-field examples are compatibility descriptions.
> Always fetch the running registry; illustrative value lists are not permission to invent values.
> The approved relationship-v1 revision is tracked in
> [relationship ontology plan](../plans/relationship-ontology.md). It broadens ordinary social,
> family, work, school and community relations without adding appointment tracking.


- Status: Relationship v1; older physical-field examples below remain compatibility descriptions
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
- Registry-backed types for entities, edges, facts, observation topics, claim basis and participants; legacy candidate/policy values remain marked as compatibility.
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
Alex --parent_of--> Jamie
User --client_of--> Dana
```

`introduced_by` in earlier versions described acquaintance background. New records put supported
background in `properties.origin` or an observation; it is no longer a new-write edge type.

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
- `parent_of`: directed, with parent as from and child as to.

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

Optional source-supported metadata, validated against the type's `allowed_properties_schema`.
Relationship v1 admits only `context` (company/school/group), `relationship_detail` (specific
kinship or relationship detail), and `origin` (acquaintance background). Each supplied value is a
nonempty string of at most 300 characters. Unknown keys and non-string values are rejected.
Do not invent exact kinship, an institution, an app, or a meeting from a vague source.

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

New memory claims save immediately with their basis and source; candidates remain a legacy
interface. Record lifecycle status is separate from whether a relationship exists now or existed
in the past.

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

`allowed_edge_types` and the server-owned relationship definitions determine readable types and
their write semantics. `GET /api/ontology` and `/api/ontology/edge-types` return
`version: relationship-v1`. Existing historical types remain readable with `active: true`,
`support_level: legacy`, and `write_supported: false`; active does not mean writable.

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

New writes either omit `directed` or supply this exact value. The server rejects an incompatible
explicit direction. Both endpoints are people; neither is required to be protected self.

#### Labels, descriptions, and write support

`label` names the source person's role relative to the target, and `inverse_label` names the
target's role for a directional relation. For `parent_of`, these are 부모 and 자녀; for `reports_to`,
부하 and 상사; for `client_of`, 고객 and 서비스 제공자. A person-centric UI must use the focal
person's endpoint to choose the label. `category`, `description`, and `examples` explain selection.
The symmetric case has one shared label. `support_level` and `write_supported` govern whether a
type can be selected for a new write. `replacement_type`, when present, suggests a source-based
migration target; it does not authorize a blind rename or endpoint swap.

#### `inverse_relation_type`

Compatibility metadata, not an instruction to create a second edge. Relationship v1 keeps one
canonical predicate for a directional pair and provides the inverse display label. Do not invent
`child_of`, `manager_of`, or another inverse as a new-write type because a UI needs reversed wording.

#### `allowed_properties_schema`

The schema declares the three optional string properties described above, their length limits,
and `additionalProperties: false`. Agent clients must preserve and read this schema rather than
copy a permissive local dictionary.

---

## 8. Relationship v1 meaning and compatibility

The following is the approved design map, not a substitute for the running registry. Clients
discover current values and metadata from the API; the server definitions remain authoritative.

| Domain | Supported relationship meanings |
| --- | --- |
| Social | `acquaintance`, `friend` |
| Family | `family`, `parent_of`, `sibling`, `spouse`, `relative`, `in_law`, `former_spouse` |
| Work | `coworker`, `former_coworker`, `reports_to`, `collaborated_with`, `business_partner`, `client_of` |
| School and learning | `classmate`, `schoolmate`, `cohort_peer`, `senior_of`, `teacher_of`, `mentor_of` |
| Community and living | `neighbor`, `housemate`, `community_peer` |
| Romantic | `situationship`, `romantic_partner`, `former_partner` |

Only `parent_of`, `reports_to`, `client_of`, `senior_of`, `teacher_of`, and `mentor_of` are directed.
Their from person is respectively the parent, subordinate, customer, senior, teacher, or mentor.
Other types are symmetric. Family detail can remain broad when the source says only “family”;
use the specific type and optional `relationship_detail` only when the source establishes it.
Several independently supported relationships can coexist, such as classmate and coworker.

`situationship` stores a relationship the source describes as “썸” symmetrically. It does not
establish independently verified mutual attraction, exclusivity, or a formal partnership. Keep
the source's wording and basis. A one-sided feeling is still an observation with its experiencer
and target, not a situationship inferred from interest.

`knows`, `dating`, `former_dating`, `dating_interest`, `manager_of`, `client_contact`,
`vendor_contact`, `introduced_by`, `referred_by`, `introduced_for_dating`, and `matched_on_app`
are legacy readable types. They cannot be selected for new edges. In particular:

- `dating_interest` is ambiguous across historical sources; neither a blanket `situationship`
  conversion nor a blanket feeling conversion is valid.
- App matching and introduction describe acquaintance background. They do not prove an actual
  meeting or a romantic relationship. Preserve supported origin information without creating a
  stronger structural claim.
- Legacy inverse/contact types require checking endpoint meaning before any canonical mapping.
- A correction may retain the exact legacy relationship structure while correcting text, source,
  or time. This does not authorize new legacy records or a legacy reattribution to different people.

Current/past types such as `former_coworker`, `former_partner`, and `former_spouse` are retained.
Do not collapse them into expired current edges: current context intentionally excludes elapsed
validity intervals, so that would hide useful past-relationship context. Generic timelines,
pair-scoped retrieval, event entities, and calendar/appointment tracking are outside this revision.

Preferences, feelings, reply strategy, cautions and inferred expectations remain observations.
No edge type should convert subjective interpretation into an established reciprocal relation.

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

### Claim basis and legacy claim types

New memory writes require `claim_basis` from `reported`, `inferred`, or `unknown`. This axis describes
how a claim was obtained. `observation_type` describes what it is about. The general `preference` type covers food, travel,
colors and interests; `communication_preference` remains specific to communication style. A preference or pattern can
be reported or inferred; do not encode both axes in one value.

Legacy `claim_type: fact|inference|preference|pattern` remains only for old APIs/records. In migration,
use source evidence/wording to establish basis; do not blindly map all historical preferences or
patterns to reported facts. `unknown` is preferable to invented certainty.

### `allowed_observation_types`

Fetch current values from `GET /api/ontology/observation-types`. Existing topics include
`communication_preference`, `recent_interaction`, `caution`, `care_point`, and `user_feeling`.
This relationship revision does not add a new event or appointment observation type.

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

### Retired AI-use policies

The former `freely_use`, `cautious_use`, `ask_before_use`, and `never_surface` values remain only
where an old-client response or historical record requires compatibility. They have no active
storage/retrieval gating semantics. Do not ask agents to choose them for new `/api/memories` writes.

## 10. Immediate Edge and Observation Flow

```text
agent interprets human source → resolves both people → selects an existing edge type
→ POST /api/memories with one entity_edges claim and basis
→ canonical edge, Episode/evidence and memory change commit together
```

A feeling, preference, caution, inferred reply strategy or recent event remains an observation.
Saving immediately does not broaden the edge ontology or imply verified truth.

## 11. Validation Rules

1. A new `relation_type` has `write_supported: true` in the running registry and valid endpoint types.
2. Omitted `directed` uses the registry direction; an explicit conflicting direction is invalid.
   Properties must follow the supplied schema; clients must not invent inverse types or keys.
3. New memories explicitly supply `claim_basis`, bounded confidence and an admitted human source.
4. Supported profile facts use the typed-value contract. Generic note fact types are legacy only.
5. Agents split semantic claims; Kinlayer deterministically validates shapes and references.
6. The write, source/evidence and common change history commit atomically; no human approval queue.
7. Existing candidate/correction interfaces retain their compatibility validation and diagnostics.
8. `/api/ontology/edge-type-diagnostics` identifies invalid legacy edges without silently rewriting
   them. Human-approved data conversion handles bounded known repairs with traceable lineage.
9. Agents fetch the ontology at session start and before an unknown type, invalidate cached
   definitions when the version changes, and refresh after ontology validation errors. A refresh
   does not authorize changing meaning merely to make a write pass. See the
   [agent cache contract](../agents/agent-write-instruction-pack.md#ontology-discovery-and-cache-rules).

---

## 12. Scope decisions and deferred work

The [approved plan](../plans/relationship-ontology.md) records the decision history. Family detail,
symmetric 썸, canonical directed predicates and strict optional properties are now decided.
The registry is server-owned; this revision does not add Web editing of ontology definitions.
Pair-level context, generic relationship timelines, dispute workflows, and observation regrouping
remain separate proposals, not implied deliverables of this relationship-type change.

## 13. Self-perspective relationship profile

`ontology.relationship_profile` has its own `version: relationship-profile-v1` and an `axes`
object. Each axis supplies `label`, `description`, and `values: [{value,label,description}]`.
The canonical runtime registry owns values; clients fetch it instead of cloning an enum.

Four independent axes describe the protected user's perspective toward another person:
`closeness`, `importance`, `interaction_frequency`, and `connection_state`. They are source-backed
`relationship_assessment` observations, not edges, global person facts, feelings attributed to the
other person, or properties repeated across family/friend/coworker edges. Every axis requires an
explicit user statement/selection (`reported`). No missing-log decay, frequency-based closeness,
family-based importance or inferred disconnection is allowed.

An unset axis has no current assertion and projects as null; it is distinct from all enum values.
Each stored axis is independently corrected/retracted with source/history through `/api/memories`.
The current profile has at most one active assertion per self/target/axis, rejects future claims
and any `valid_to`, and does not implement generic timelines or meetings. See the
[write contract](../agents/agent-write-instruction-pack.md#self-perspective-relationship-assessments)
and [approval delta](../plans/relationship-ontology.md#d09d10-승인-변경분--네-축과-프런트-수정).

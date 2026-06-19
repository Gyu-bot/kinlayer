# Kinlayer Agent Write Instruction Pack

- Status: Draft v0.1
- Scope: Instructions for AI agents, skills, plugins, MCP adapters, and runtime hooks that write or propose data into Kinlayer
- Parent docs: `../specs/api-spec.md`, `../specs/candidate-lifecycle-and-payload.md`, `../specs/ontology-design.md`

---

## 1. Purpose

This pack tells an agent how to write relationship knowledge into Kinlayer without corrupting the schema.

Agents may help discover possible people, aliases, profile facts, relationships, observations, merges, conflicts, and corrections. Agents must not invent Kinlayer ontology values or bypass review for inferred memory.

Default rule:

```text
Agent-inferred memory -> POST /api/candidates
Explicit user correction -> POST /api/corrections/apply, only when the old record is unambiguous
Ambiguous or unsupported memory -> no write, or ask for clarification
```

---

## 2. Non-Negotiable Rules

1. Fetch or use current ontology values before choosing controlled fields.
2. Never invent controlled values.
3. Use candidates for inferred agent writes.
4. Use direct correction apply only for explicit user corrections.
5. Use evidence only from user-authored source text.
6. Do not use assistant text, tool output, retrieved context, or your own inference as evidence.
7. Do not create relationship edges for advice, feelings, reply strategy, caution, communication preference, or recent interaction interpretation.
8. If the target person or old record is ambiguous, do not write a canonical correction.
9. If the correct ontology value is missing, stop instead of creating a new value.
10. Verify the API response and surface validation failures as diagnostics, not as rewritten facts.

Controlled fields include at least:

```text
candidate_type
relation_type
observation_type
fact_type
claim_type
sensitivity
ai_use_policy
entity_type
source_type
suggested_action
```

---

## 3. Required Pre-Write Flow

Before any write-like call, run this flow.

```text
1. Identify the user-authored statement that justifies the write.
2. Resolve the target entity or entities.
3. Fetch ontology and controlled values.
4. Classify the proposed memory into one Kinlayer write type.
5. Resolve temporal context when the usefulness of the record depends on time.
6. Create or identify an evidence episode.
7. Submit a candidate or explicit correction.
8. Verify the response.
```

Recommended ontology calls:

```text
GET /api/ontology
GET /api/ontology/edge-types
GET /api/ontology/observation-types
GET /api/ontology/entity-fact-types
GET /api/ontology/policies
```

Use the registry values returned by these endpoints. Mechanical normalization may exist in the service layer later, but agents should still send canonical registry values.

Kinlayer exposes `POST /api/agent-writes/validate` and CLI `kinlayer agent-write validate <payload.json>`
for dry-run checks. Use it when integrating a new adapter or debugging a rejected write. A successful
dry run does not persist a candidate or canonical record.

---

## 4. Relationship Type Is Edge Type

In Kinlayer, these are the same concept:

```text
Web UI relationship type
API entity_edges.relation_type
Candidate relationship_edge.relation_type
Graph edge label/value
```

All must come from `allowed_edge_types.relation_type`.

An agent must never send free-form values such as:

```text
"is close with"
"important person"
"avoid_topic"
"reply_strategy"
"likes short messages"
"probably dating-ish"
```

Unless an active ontology edge type with exactly that canonical `relation_type` exists, the value is invalid.

---

## 5. Edge vs Observation Decision Table

Use `relationship_edge` only for durable structural relationships between entities.

| User meaning | Kinlayer type | Reason |
| --- | --- | --- |
| "Minji is my former coworker." | `relationship_edge` | Stable structural relationship. |
| "Alex is a client contact." | `relationship_edge` | Stable professional relationship. |
| "Sam reports to Dana." | `relationship_edge` | Directed structural relationship. |
| "Dana introduced me to Minji." | `relationship_edge` | Structural introduction relationship when `introduced_by` or inverse exists. |
| "Minji prefers short replies." | `observation` | Communication preference, not graph structure. |
| "Be careful not to mention salary." | `observation` | Caution/advice, not a relationship edge. |
| "Minji needs a softer tone when I follow up." | `observation` | Care point and reply strategy. |
| "I felt awkward after the last message." | `observation` | Recent interaction or emotional context. |
| "Follow up tomorrow." | no relationship edge | Task/advice; use observation only if an allowed observation type and evidence justify it. |
| "She might like me." | `observation` or no write | Inference/emotional context, not structural edge unless explicitly supported by ontology and evidence. |
| "Alex and Alexander are probably the same person." | `merge` candidate | Identity resolution requires review. |
| "This contradicts the old note." | `conflict` candidate | Conflicting records require review. |

Observation-preferred concepts include:

```text
communication_preference
relationship_context
recent_interaction
caution
care_point
user_preference_about_person
reply strategy
emotional salience
sensitive subject
follow-up advice
```

Use only active `observation_type` values from the ontology.

---

## 6. Candidate Type Decision Table

| Situation | Candidate type |
| --- | --- |
| A new person, organization, or supported entity appears. | `new_entity` |
| A known entity has another name or nickname. | `alias` |
| A stable profile field such as email, role, organization, phone, birth date, or address appears. | `profile_field` |
| A stable structural relation appears and its type exists in `allowed_edge_types`. | `relationship_edge` |
| A contextual note, preference, caution, recent interaction, or care point appears. | `observation` |
| Two entities may be the same. | `merge` |
| Existing records contradict each other. | `conflict` |
| A candidate or canonical record should be replaced by a clearer proposed record. | `supersede` |
| The statement is ambiguous, unsupported, or uses missing ontology values. | no write or clarification |

`needs_clarification` is a review status/action, not a `candidate_type`.

---

## 7. Evidence Rules

Evidence must be small, attributable, and user-authored.

Allowed evidence:

```text
- current-turn user message text;
- a bounded excerpt from a user-authored source;
- an imported source excerpt with a stable source reference.
```

Disallowed evidence:

```text
- assistant-generated summaries;
- retrieved Kinlayer context;
- tool results;
- model guesses;
- paraphrases that remove important uncertainty;
- private full transcripts when a bounded excerpt is enough.
```

Use the minimum excerpt that supports the candidate. Preserve uncertainty when present.

Create an episode when the candidate needs provenance:

```json
{
  "source_type": "agent_conversation",
  "source_ref": "thread-or-turn-id",
  "source_description": "User-authored conversation excerpt",
  "body_excerpt": "Minji is my former coworker.",
  "body_hash": "sha256:...",
  "occurred_at": "2026-06-12T00:00:00Z",
  "created_by": "ai_agent"
}
```

This is a review workflow. Agents may submit this candidate with evidence and confidence, or use
`POST /api/entities/duplicate-candidates` to inspect duplicate signals and create a pending merge
candidate with traceable evidence. They may call candidate accept for person merge execution only
when the current turn contains explicit user confirmation for the exact source-target merge. In that
case, call accept with `resolved_by = ai_agent` and a `resolution_note` that captures the user
confirmation. Protected self must not be source or target for a normal person merge. Weak or
pronoun-only identity evidence should ask for clarification instead of proposing a merge.

When a reviewer accepts a merge candidate, Kinlayer marks the source person `merged`, stores
`properties.merged_entity_ref = entities:<target>`, and treats the target as canonical in retrieval,
context-card, and graph output. Agents should rely on those API outputs rather than keeping their own
source-to-target mapping.

If the runtime cannot create the hash itself, use the adapter-provided episode helper. Do not invent an unverifiable hash.

---

## 8. Recording Quality Rules

Schema validity is only the baseline. Agent-written records must also be useful when read later without
the original conversation.

### 8.1 Make `content` self-contained

Observation `content` should be understandable on its own.

Good observation content usually includes:

```text
- the named subject, not only a pronoun;
- the concrete event, preference, caution, or context;
- the relevant counterpart when useful;
- uncertainty from the source text;
- temporal context when time affects later usefulness.
```

Avoid content that depends on hidden chat context:

```text
Bad: "This week, suggested sending that person a short reply."
Good: "During the week of 2026-06-08 to 2026-06-14 (Asia/Seoul), the agent suggested that the user send Minji a concise reply."
```

Do not include internal UUIDs in human-facing `content` unless the UI/tool specifically asks for a
debug payload.

### 8.2 Prefer typed records over observation prose

Do not use observations as a dumping ground for facts that Kinlayer can store as typed records.

Use typed records for structurally queryable or correctable facts:

| Source wording | Better target |
| --- | --- |
| "혜영은 전 연인이다." | `relationship_edge` with `relation_type: "former_partner"` |
| "8년 만났다." | relationship edge `properties` or a relationship-scoped fact, if supported |
| "중학교 영어교사." | `profile_field` / `entity_facts` with an active `fact_type` |
| "다솜은 치아바타를 좋아함." | a typed preference/profile fact when the fact model supports it |

Observation should hold relationship judgment, coaching context, conversation strategy, and reusable
context notes that are not cleanly typed:

```text
"최근 대화에서 민규는 혜영의 정서적 의존 때문에 관계 단절을 어렵게 느낀다고 설명했다."
"혜영 관련 조언에서는 단순히 '연락 끊어'보다 안전한 경계 설정과 책임 분리를 다뤄야 한다."
"다솜과의 초반 대화에서는 미래지향적/관계 프레이밍 표현이 부담이 될 수 있어 낮은 압박이 좋다."
```

Agent-write validation may return a non-blocking warning when observation content looks like it may
belong in relationship edges, relationship properties, or entity facts. The API must not invent a
replacement typed record; the agent or reviewer should submit the better typed candidate explicitly.

### 8.3 Observation content contract

Observation `content` remains natural language, but it must be compact and reviewable:

```text
- one observation = one claim, pattern, caution, or reusable context point;
- usually 1-2 sentences;
- roughly 300 characters unless the context truly requires more;
- name the subject explicitly; avoid "그 사람", "저런 식", "that person", or other dangling references;
- include temporal scope in `occurred_at`, `valid_from`/`valid_to`, or readable content such as "As of 2026-06-18".
```

The deterministic agent-write filter can warn about blank content, overlong content, dangling
references, missing temporal scope, and typed-record boundary review. Warnings do not mean the API has
semantically rewritten the payload; they are review diagnostics.

### 8.4 Temporal recording rules

For agent-submitted observations, prefer explicit temporal fields when the source gives event or
applicability time. Do not stamp every observation with a date just because the record is being
created, but do not drop known time information.

Default granularity is date-level, not clock-time-level. Use exact times only when the source provides
them or the distinction matters. If the storage/API field is a timestamp, the adapter may encode a
date as a local-day boundary, but the agent-facing meaning should remain date-based.

Important distinction:

```text
created_at = when Kinlayer stored the record; not evidence of when the event happened
episode.occurred_at = when the user-authored source was recorded or spoken
observation.occurred_at = when the observed event actually happened
valid_from / valid_to = the date or date range when the observation is true or relevant
```

Never collapse `episode.occurred_at` and `observation.occurred_at` unless the source clearly says the
event happened at the same time as the user record.

When the user source contains relative time, resolve it against the source timestamp, not an unrelated
wall-clock time. If the source timestamp is unknown, do not pretend it is known.

Examples:

| Source wording | Better record |
| --- | --- |
| "이번주에 민지한테 짧게 답장하라고 제안했어." | Source-recorded date is 2026-06-12. Event/applicability range is 2026-06-08 to 2026-06-14 (Asia/Seoul). Use `valid_from`/`valid_to` for that date range. |
| "어제 Alex가 다시 연락했어." | If the source-recorded date is 2026-06-12, the event date is 2026-06-11. Use `observation.occurred_at` or equivalent event-date field for 2026-06-11 if supported; content should say the absolute date. |
| "요즘 Dana는 일정 변경에 예민해." | Use a readable anchor such as "as of 2026-06-12" in content; use `valid_from` only if the source implies a start date or current validity matters. The event date is not necessarily 2026-06-12. |
| "Minji prefers concise replies." | No temporal field is needed unless the source says this is temporary or recent. |
| "지난번엔 분위기가 어색했어." | If "지난번" cannot be resolved to an event/date from the current turn or context, preserve uncertainty or ask for clarification before writing a high-confidence recent-interaction observation. |

For date ranges stored in timestamp-shaped fields, prefer half-open local-day ranges:

```text
valid_from = 2026-06-08T00:00:00+09:00
valid_to   = 2026-06-15T00:00:00+09:00
```

The readable content may display the inclusive human range:

```text
2026-06-08 to 2026-06-14 (Asia/Seoul)
```

Candidate observation payloads support `occurred_at`, `valid_from`, and `valid_to`; adapters must
preserve those fields through submit, accept/edit-accept, and canonical observation creation. Also keep
a readable temporal anchor in `content` when it helps future reviewers understand the note.

### 8.5 Record suggestions and advice with enough context

When recording an observation that a suggestion or advice was given, include:

```text
- who or what the suggestion was about;
- what was suggested;
- when it was suggested or when it applied, if time matters;
- whether it was the agent's suggestion, the user's plan, or a third-party statement;
- the reason only if it was explicit in the source.
```

Bad:

```text
"This week, suggested a short reply."
```

Good:

```text
"During the week of 2026-06-08 to 2026-06-14 (Asia/Seoul), the agent suggested that the user send Minji a concise, low-pressure reply about the follow-up."
```

If storing the fact that the agent suggested something is not useful for future relationship context,
prefer no write. Kinlayer is not a transcript archive.

### 8.6 Preserve uncertainty and scope

Do not upgrade weak statements into strong facts.

```text
Source: "민지가 좀 부담스러워했을 수도 있어."
Bad: "Minji felt burdened."
Good: "The user thought Minji may have felt pressured; this is uncertain."
```

Do not make temporary observations timeless:

```text
Source: "요즘은 길게 설명하면 부담스러워하는 것 같아."
Bad: "Minji dislikes long explanations."
Good: "As of 2026-06-12, the user thinks Minji may currently find long explanations burdensome."
```

---

## 9. Common Candidate Envelope

All candidate submissions use this envelope shape:

```json
{
  "candidate_type": "observation",
  "target_entity_id": "uuid-or-null",
  "payload": {},
  "evidence": [
    {
      "episode_id": "uuid",
      "excerpt": "User-authored supporting excerpt.",
      "confidence": 0.9
    }
  ],
  "confidence": 0.72,
  "sensitivity": "medium",
  "suggested_action": "review",
  "created_by": "ai_agent"
}
```

Use `suggested_action: "accept"` only when the user statement is explicit, the target entity is unambiguous, and all controlled values are registry-backed. Otherwise use `review` or `clarify` when supported.

---

## 10. JSON Examples

### 10.1 `new_entity`

```json
{
  "candidate_type": "new_entity",
  "target_entity_id": null,
  "payload": {
    "entity_type": "person",
    "display_name": "Minji",
    "canonical_name": "minji",
    "properties": {},
    "ai_use_policy": "cautious_use",
    "sensitivity": "medium"
  },
  "evidence": [
    {
      "episode_id": "uuid",
      "excerpt": "Minji is my former coworker.",
      "confidence": 0.9
    }
  ],
  "confidence": 0.8,
  "sensitivity": "medium",
  "suggested_action": "review",
  "created_by": "ai_agent"
}
```

### 10.2 `alias`

```json
{
  "candidate_type": "alias",
  "target_entity_id": "entity-uuid",
  "payload": {
    "entity_id": "entity-uuid",
    "alias": "MJ",
    "confidence": 0.82
  },
  "evidence": [
    {
      "episode_id": "uuid",
      "excerpt": "MJ, I mean Minji, is my former coworker.",
      "confidence": 0.9
    }
  ],
  "confidence": 0.82,
  "sensitivity": "low",
  "suggested_action": "review",
  "created_by": "ai_agent"
}
```

### 10.3 `profile_field`

Use `profile_field` for stable profile facts. Structured person profile facts canonicalize into `entity_facts`. Supported structured fact types include values such as `legal_name`, `birth_date`, `phone`, `email`, `address`, `organization`, `role`, and `memo` when those values exist in the active registry.

```json
{
  "candidate_type": "profile_field",
  "target_entity_id": "entity-uuid",
  "payload": {
    "entity_id": "entity-uuid",
    "field_path": "profile.organization",
    "fact_type": "organization",
    "content": "Minji works at Example Corp.",
    "value": {
      "organization": "Example Corp"
    },
    "claim_type": "fact",
    "sensitivity": "medium",
    "ai_use_policy": "cautious_use"
  },
  "evidence": [
    {
      "episode_id": "uuid",
      "excerpt": "Minji works at Example Corp.",
      "confidence": 0.92
    }
  ],
  "confidence": 0.88,
  "sensitivity": "medium",
  "suggested_action": "review",
  "created_by": "ai_agent"
}
```

Do not promote a general note into a structured fact unless the active `fact_type` and `field_path` are clear.

### 10.4 `relationship_edge`

Only use this when `former_coworker` is an active `allowed_edge_types.relation_type` and the endpoint entity types match.

```json
{
  "candidate_type": "relationship_edge",
  "target_entity_id": "minji-entity-uuid",
  "payload": {
    "from_entity_id": "user-self-entity-uuid",
    "to_entity_id": "minji-entity-uuid",
    "relation_type": "former_coworker",
    "directed": false,
    "claim_text": "Minji is the user's former coworker.",
    "claim_type": "fact",
    "properties": {}
  },
  "evidence": [
    {
      "episode_id": "uuid",
      "excerpt": "Minji is my former coworker.",
      "confidence": 0.95
    }
  ],
  "confidence": 0.9,
  "sensitivity": "medium",
  "suggested_action": "accept",
  "created_by": "ai_agent"
}
```

If the user says "Minji is important to me" or "I should be careful with Minji", do not create a relationship edge.

### 10.5 `observation`

```json
{
  "candidate_type": "observation",
  "target_entity_id": "minji-entity-uuid",
  "payload": {
    "subject_entity_id": "minji-entity-uuid",
    "related_entity_ids": ["user-self-entity-uuid"],
    "observation_type": "communication_preference",
    "content": "Minji prefers concise replies.",
    "claim_type": "preference",
    "ai_use_policy": "cautious_use",
    "sensitivity": "medium",
    "occurred_at": null,
    "valid_from": null,
    "valid_to": null
  },
  "evidence": [
    {
      "episode_id": "uuid",
      "excerpt": "Minji prefers short replies.",
      "confidence": 0.9
    }
  ],
  "confidence": 0.84,
  "sensitivity": "medium",
  "suggested_action": "review",
  "created_by": "ai_agent"
}
```

### 10.6 `merge`

Preferred discovery flow:

1. Use entity resolution first for the current-turn person mention.
2. If two existing person records may be duplicates, call
   `POST /api/entities/duplicate-candidates` with `create_candidate = false`.
3. If the result recommends `create_merge_candidate`, call the same endpoint with
   `create_candidate = true` and evidence from a user-authored episode.
4. If the user confirms the exact source-target merge in the current turn, call
   `POST /api/candidates/{candidate_id}/accept` with `resolved_by = ai_agent` and a
   `resolution_note` recording that confirmation.
5. If the user has not confirmed the exact merge, leave accept/reject/archive/clarify to the
   reviewer workflow.

```json
{
  "candidate_type": "merge",
  "target_entity_id": "target-entity-uuid",
  "payload": {
    "source_entity_id": "possible-duplicate-entity-uuid",
    "target_entity_id": "target-entity-uuid",
    "reason": "User refers to MJ as Minji, and both records appear to describe the same person.",
    "fields_to_merge": ["aliases", "observations"],
    "risk_notes": ["The match is not certain without user review."]
  },
  "evidence": [
    {
      "episode_id": "uuid",
      "excerpt": "MJ, I mean Minji...",
      "confidence": 0.8
    }
  ],
  "confidence": 0.7,
  "sensitivity": "medium",
  "suggested_action": "review",
  "created_by": "ai_agent"
}
```

### 10.7 `conflict`

```json
{
  "candidate_type": "conflict",
  "target_entity_id": "entity-uuid",
  "payload": {
    "record_refs": ["entity_edges:old-edge-uuid", "observations:new-observation-uuid"],
    "conflict_type": "contradiction",
    "summary": "One record says Minji is a former coworker, while the new statement says Minji is a client contact.",
    "recommended_resolution": "Ask the user whether this is a correction or a different Minji."
  },
  "evidence": [
    {
      "episode_id": "uuid",
      "excerpt": "No, Minji is a client contact, not a former coworker.",
      "confidence": 0.95
    }
  ],
  "confidence": 0.8,
  "sensitivity": "medium",
  "suggested_action": "review",
  "created_by": "ai_agent"
}
```

Use `conflict` when the old record or intended replacement is not safe enough for direct correction apply.

### 10.8 `supersede`

```json
{
  "candidate_type": "supersede",
  "target_entity_id": "entity-uuid",
  "payload": {
    "old_record_ref": "observations:old-observation-uuid",
    "new_record": {
      "record_type": "observations",
      "payload": {
        "subject_entity_id": "entity-uuid",
        "related_entity_ids": ["user-self-entity-uuid"],
        "observation_type": "relationship_context",
        "content": "Minji is currently a client contact, not only a former coworker.",
        "claim_type": "fact",
        "ai_use_policy": "cautious_use",
        "sensitivity": "medium"
      }
    },
    "reason": "Newer user statement is more specific."
  },
  "evidence": [
    {
      "episode_id": "uuid",
      "excerpt": "Actually Minji is a client contact now.",
      "confidence": 0.9
    }
  ],
  "confidence": 0.78,
  "sensitivity": "medium",
  "suggested_action": "review",
  "created_by": "ai_agent"
}
```

### 10.9 Explicit Correction Apply

Use direct correction only when all are true:

```text
- the user explicitly corrects a previous record;
- the old record ref is known and unambiguous;
- the new record payload uses registry-backed controlled values;
- the correction source excerpt is user-authored;
- user_explicit is true.
```

```json
{
  "old_record_ref": "entity_edges:old-edge-uuid",
  "new_record": {
    "record_type": "entity_edges",
    "payload": {
      "from_entity_id": "user-self-entity-uuid",
      "to_entity_id": "minji-entity-uuid",
      "relation_type": "client_contact",
      "directed": true,
      "claim_text": "Minji is a client contact, not a former coworker.",
      "claim_type": "fact",
      "properties": {},
      "confidence": 0.95,
      "status": "active",
      "sensitivity": "medium",
      "ai_use_policy": "cautious_use",
      "created_by": "ai_agent"
    }
  },
  "correction_source": {
    "source_type": "agent_conversation",
    "user_explicit": true,
    "excerpt": "No, Minji is a client contact, not a former coworker.",
    "occurred_at": "2026-06-12T00:00:00Z"
  },
  "created_by": "ai_agent"
}
```

If `client_contact` is not an active edge type for the endpoint entity types, do not apply this correction.

### 10.10 Invalid Edge Payload and Safer Alternative

Invalid:

```json
{
  "candidate_type": "relationship_edge",
  "target_entity_id": "minji-entity-uuid",
  "payload": {
    "from_entity_id": "user-self-entity-uuid",
    "to_entity_id": "minji-entity-uuid",
    "relation_type": "prefers_short_replies",
    "directed": false,
    "claim_text": "Minji prefers short replies.",
    "claim_type": "preference",
    "properties": {}
  },
  "confidence": 0.84,
  "sensitivity": "medium",
  "suggested_action": "review",
  "created_by": "ai_agent"
}
```

Why invalid:

```text
`prefers_short_replies` is a communication preference, not a structural edge type.
It is invalid unless the active `allowed_edge_types` registry explicitly allows it.
```

Safer alternative when `communication_preference` is an active observation type:

```json
{
  "candidate_type": "observation",
  "target_entity_id": "minji-entity-uuid",
  "payload": {
    "subject_entity_id": "minji-entity-uuid",
    "related_entity_ids": ["user-self-entity-uuid"],
    "observation_type": "communication_preference",
    "content": "Minji prefers short replies.",
    "claim_type": "preference",
    "ai_use_policy": "cautious_use",
    "sensitivity": "medium",
    "occurred_at": null,
    "valid_from": null,
    "valid_to": null
  },
  "evidence": [
    {
      "episode_id": "uuid",
      "excerpt": "Minji prefers short replies.",
      "confidence": 0.9
    }
  ],
  "confidence": 0.84,
  "sensitivity": "medium",
  "suggested_action": "review",
  "created_by": "ai_agent"
}
```

If no active observation type fits, produce no write and surface a diagnostic.

---

## 11. Korean Examples

### Example A: Stable relationship

User:

```text
민지는 내 전 직장 동료야.
```

Agent action:

```text
1. Resolve or create Minji entity.
2. Fetch edge types.
3. If `former_coworker` is active and endpoint types match, submit `relationship_edge`.
4. Do not use a free-form relation type such as `전 직장 동료`.
```

### Example B: Communication preference

User:

```text
민지는 짧게 답장하는 걸 좋아해.
```

Agent action:

```text
Submit an `observation` candidate with an active observation type such as `communication_preference`.
Do not submit a `relationship_edge`.
```

### Example C: Ambiguous pronoun

User:

```text
그 사람이 또 연락했어.
```

Agent action:

```text
Retrieve context if useful, but do not write until the person is clear.
Ask a short clarification if needed.
```

### Example D: Explicit correction

User:

```text
아니, Alex는 전 직장 동료가 아니라 클라이언트 쪽 사람이야.
```

Agent action:

```text
If the old edge is unambiguous and `client_contact` is an active edge type, call `/api/corrections/apply`.
If the old edge is ambiguous, submit a `conflict` or `supersede` candidate instead.
```

### Example E: General profile fact promotion

User:

```text
민지 회사는 Example Corp야.
```

Agent action:

```text
If `organization` is an active fact type and Minji is unambiguous, submit a `profile_field` candidate.
If the statement is a broad note rather than a structured profile field, keep it as an `observation` candidate.
```

### Example F: Relative time in recent observations

User source date:

```text
2026-06-12 Asia/Seoul
```

User:

```text
이번주에 민지한테 너무 길게 보내지 말고 짧게 답장하라고 제안했어.
```

Agent action:

```text
Do not write "이번주" by itself.
Treat 2026-06-12 as the source-recorded date, not necessarily the event date.
Resolve "이번주" to the event/applicability range: 2026-06-08 through 2026-06-14 in Asia/Seoul.
If storing this is useful, submit an `observation` candidate with self-contained content:
"During the week of 2026-06-08 to 2026-06-14 (Asia/Seoul), the agent suggested that the user send Minji a concise reply rather than a long one."
Use `valid_from`/`valid_to` for the week range.
```

---

## 12. Failure Behavior

When the agent cannot safely write, it should return a no-write diagnostic.

| Problem | Safe behavior |
| --- | --- |
| Entity target ambiguous | Ask clarification or do no write. |
| Old record ambiguous | Do not call `/api/corrections/apply`; use `conflict` candidate or ask. |
| Missing `relation_type` | Do not create edge or invent type. |
| Missing `observation_type` | Do not create observation or invent type. |
| Multiple ontology values could match | Ask or stop; do not guess. |
| Evidence is assistant-generated | Do not write. |
| User statement is hypothetical | Usually no write; use candidate only if user clearly wants it stored. |
| Sensitive data has unclear policy | Prefer `ask_before_use` or stop if policy values are unavailable. |
| Relative time cannot be anchored and time is important | Ask for clarification or write content that explicitly says the date is unknown. |
| API validation fails | Surface the validation error and do not retry with guessed schema. |

Example diagnostic:

```json
{
  "write_status": "no_write",
  "reason": "relation_type_not_allowed",
  "details": "The requested relationship type was not present in active allowed_edge_types."
}
```

---

## 13. Agent Prompt Snippet

Use this compact snippet in agent/system prompts:

```text
Before writing to Kinlayer, fetch ontology values and use only registry-backed controlled values.
Treat UI relationship type, API relation_type, relationship_edge.relation_type, and graph edge labels as ontology edge types from allowed_edge_types.
Use candidates for inferred memory. Use /api/corrections/apply only for explicit user corrections with an unambiguous old record.
Edges are durable structural relationships. Preferences, cautions, feelings, reply strategy, recent interactions, and advice are observations, not edges.
Observation content must be self-contained. If a useful observation depends on relative time such as "this week", "yesterday", "recently", or "지난번", resolve it against the source timestamp and record an absolute date/range when possible.
Evidence must be a bounded user-authored excerpt. Never use assistant text, tool output, retrieved context, or guesses as evidence.
If the entity, record, or ontology value is ambiguous or missing, do not write; ask for clarification or return a no-write diagnostic.
```

---

## 14. Adapter Implementation Notes

Tool adapters should expose narrow helpers rather than asking agents to handcraft every HTTP call.
For local read/debug access, prefer the repo-owned helper before ad-hoc shell snippets:

```bash
python3 scripts/kinlayer_client.py health
python3 scripts/kinlayer_client.py entities --query "Jordan" --entity-type person
python3 scripts/kinlayer_client.py context-card --entity-id person_jordan
python3 scripts/kinlayer_client.py observations --subject-entity-id person_jordan --status active
python3 scripts/kinlayer_client.py candidates --status pending
python3 scripts/kinlayer_client.py retrieve --query "relationship context for Jordan" --hint Jordan
python3 scripts/kinlayer_client.py pack --query "briefing before drafting a reply" --hint Jordan
```

The helper resolves the base URL from config/env, emits compact JSON by default, and requires
`--raw` for full payload dumps. It is read/debug only. Do not use it as a substitute for candidate
review, candidate acceptance, correction apply, or any canonical write path.

Recommended helper sequence:

```text
kinlayer_get_ontology()
kinlayer_resolve_entity()
kinlayer_create_episode()
kinlayer_submit_candidate()
kinlayer_apply_correction()
kinlayer_validate_write()       # future deterministic guard
kinlayer_list_recent_write_audit() # future diagnostics
```

The deterministic service guard should validate schema, registry membership, endpoint entity-type compatibility, evidence presence, and low-risk exact normalization. It should not use an LLM, fuzzy semantic matching, synonym lists, or keyword-based intent rewriting.

LLM-assisted background curation may exist later as an optional review-only workflow. It must never directly write canonical records and must still pass deterministic validation before creating candidates.

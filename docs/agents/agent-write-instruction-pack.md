# Kinlayer Agent Write Contract

- Contract: save-first memory and relationship ontology v1, 2026-10-01
- Wire truth: `backend/src/kinlayer_backend/schemas/memories.py` and `/openapi.json`
- Implementation plan: [save-first memory schema](../plans/save-first-memory-schema.md)
- Relationship revision: [approved scope and acceptance](../plans/relationship-ontology.md)
- Source imports: [authorized material imports](../specs/authorized-material-imports.md)

## 1. Operating rule

Read relevant context, interpret the current human source, and save each useful claim immediately.
Do not submit ordinary new memories to a candidate queue or wait for user approval. When the user
points out an error in conversation, correct, retract, or reattribute the exact stored record.
Saving a statement does not establish that it is true: always preserve its basis and uncertainty.

```text
human conversation → resolve person → one claim per request → POST /api/memories
→ canonical record + bounded source + change history commit together → readback
later correction → POST /api/memories with the old record ref → immediate corrected retrieval
```

Kinlayer runs deterministic validation and storage. The agent performs extraction, interpretation,
claim splitting, and source selection. No LLM runs inside the core write transaction.

## 2. Before writing

1. Identify a bounded excerpt from the current human-authored turn. Imported human material uses
   the separate authorized import workflow; it cannot be laundered through ordinary source fields.
2. Resolve people with `POST /api/entities/resolve`. Use exact returned IDs. If a clearly named new
   person has no match, create it with `POST /api/entities`; no approval queue is necessary.
   A minimal person body is `{"entity_type":"person","display_name":"민지","created_by":"ai_agent"}`.
   Do not send approval/AI-use-policy fields. Then use the returned ID in the memory request.
3. At session start, fetch `GET /api/ontology` (or `python3 scripts/kinlayer_client.py ontology`).
   Read the definitions as well as the values. Refresh before an unknown type, after a deployment
   notice, and after a type/direction/property validation failure. See the cache rules below.
4. Split independently correctable claims. A profession, work schedule, appointment, and inference
   are separate records even if they came from one sentence and share one source excerpt.
5. Choose the record type and explicit `claim_basis`, confidence, participants, and known times.
6. Assign a stable `request_id` for this one logical operation and send the request.
7. Check the response and read the exact resulting record and affected person's context card.

Do not create people from pronouns alone or silently merge people with similar names. Resolve an
ambiguous target from conversation or ask the smallest necessary identity question. This is an
identity requirement, not a memory approval stage. Do not record public figures, fictional examples,
generic groups, models, or bots as the user's relationships without relevant human source context.

### Ontology discovery and cache rules

`GET /api/ontology` and `/api/ontology/edge-types` include an ontology `version`; relationship v1
is `relationship-v1`. Each edge definition supplies labels, direction, descriptions, examples,
property schema, `support_level`, `write_supported`, and any `replacement_type` hint. Registry
presence or `active: true` alone does not permit a new write: historical types remain readable.
Select a new relationship only when the current server definition has `write_supported: true`.

Keep any adapter cache scoped to the API instance and returned version. On a version change,
discard cached relationship definitions, direction assumptions, and property allowlists. Fetch
at every session start even if the previous version is cached. The repository helper itself
does not cache; its `definitions.edge_types` retains the complete server metadata. Its `values`
field is an index, not a write allowlist. Missing version/write metadata from an older server
must not be replaced with locally guessed defaults; inspect that server's raw contract.

After an ontology-related HTTP 422, refresh the registry and read the specific reason. Do not
loop retries, invent a relation name, swap people to fit validation, or weaken the claim into
another type. `replacement_type` is a migration hint requiring the original source and endpoint
meaning; it is never permission for automatic semantic conversion. Once a rejected request has
been corrected, use a new request ID for its changed body. Transport retries retain the exact
original body and request ID. These checks do not introduce a pre-save approval queue.

## 3. Request envelope

`POST /api/memories` accepts one atomic record operation:

| Field | Contract |
| --- | --- |
| `request_id` | Required stable idempotency key, 1–160 characters; reuse the exact request on transport retry. |
| `action` | `create`, `correct`, `retract`, or `reattribute`. |
| `old_record_ref` | `entity_facts:<id>`, `entity_edges:<id>`, or `observations:<id>`; required except for `create`. |
| `record` | `{record_type, payload}`; required except for `retract`. |
| `source` | Required bounded human source, defined below. |
| `reason` | Optional explanation of the change, at most 1,000 characters; not evidence. |
| `created_by` | Writer identity; normally `ai_agent`. It does not replace source authorship. |
| `expected_updated_at` | Optional old-record timestamp for optimistic concurrency. |

`source` contains:

| Field | Contract |
| --- | --- |
| `source_type` | Ordinary writes: `agent_conversation` or `manual_entry`. |
| `source_ref` | Optional stable conversation/turn or manual-entry locator, at most 500 characters. |
| `actor` | Actual human author, 1–80 characters; never `assistant`, `ai_agent`, `system`, `tool`, or `unknown`. |
| `excerpt` | Required supporting human text, 1–4,000 characters. |
| `occurred_at` | Optional time the source statement was made; not the described event's time. |

The service creates and hashes the source Episode and connects its evidence in the same transaction.
Do not pre-create an Episode or invent a hash for this endpoint. `source.actor = user` identifies
current-user authorship only; never relabel another person's imported material as the user.

A different body with an already used `request_id` is a conflict. A timeout is not proof of failure:
retry the same request rather than generating a new key. The endpoint returns HTTP 200 on success and replay. A successful replay returns the original
record/change references. HTTP 422 indicates validation failure, HTTP 404 a missing target, and
HTTP 409 an idempotency conflict or stale old record (a status other than active/disputed). Do not retry a semantic validation error by changing facts to fit it.

### Create an observation

Replace example IDs with resolved real IDs; the names and statements here are fictional.

```json
{
  "request_id": "conversation-42:turn-8:claim-1",
  "action": "create",
  "record": {
    "record_type": "observations",
    "payload": {
      "subject_entity_id": "person-minji-id",
      "observation_type": "communication_preference",
      "content": "민지는 일정 확인 메시지를 짧게 받는 것을 선호한다고 말했다.",
      "claim_basis": "reported",
      "confidence": 0.9,
      "related_entities": [{"entity_id": "person-minji-id", "role": "speaker"}]
    }
  },
  "source": {
    "source_type": "agent_conversation",
    "source_ref": "conversation-42/turn-8",
    "actor": "user",
    "excerpt": "민지가 일정 확인 메시지는 짧게 보내주는 게 좋대."
  }
}
```

### Create a typed profile fact with an incomplete date

```json
{
  "request_id": "conversation-42:turn-9:claim-1",
  "action": "create",
  "record": {
    "record_type": "entity_facts",
    "payload": {
      "entity_id": "person-minji-id",
      "fact_type": "birth_date",
      "content": "1990-03",
      "value": {"year": 1990, "month": 3, "precision": "month"},
      "claim_basis": "reported",
      "confidence": 0.9
    }
  },
  "source": {
    "source_type": "agent_conversation",
    "source_ref": "conversation-42/turn-9",
    "actor": "user",
    "excerpt": "민지는 1990년 3월생이야. 날짜는 몰라."
  }
}
```

### Create a relationship

```json
{
  "request_id": "conversation-42:turn-10:claim-1",
  "action": "create",
  "record": {
    "record_type": "entity_edges",
    "payload": {
      "from_entity_id": "self-id",
      "to_entity_id": "person-minji-id",
      "relation_type": "former_coworker",
      "claim_text": "사용자와 민지는 이전 직장 동료다.",
      "claim_basis": "reported",
      "confidence": 0.95
    }
  },
  "source": {
    "source_type": "agent_conversation",
    "source_ref": "conversation-42/turn-10",
    "actor": "user",
    "excerpt": "민지는 예전 직장 동료야."
  }
}
```

Omit `directed` to use the ontology's direction. An explicit value must agree with that definition.
Use the description to place the people: for `parent_of`, from is the parent and to is the child;
for `reports_to`, from reports to to; for `client_of`, from is the customer of to. Do not create
an extra inverse edge or invent an inverse type just to display the other person's perspective.

Relationship v1 covers social, family, work, school, learning, community, and romantic relations.
Use the fetched registry rather than a copied enum list. Optional `properties` are `context`
(company/school/group), `relationship_detail` (specific family or relationship detail), and
`origin` (how the people became acquainted). Each supplied value must be a nonempty string of at
most 300 characters; unknown keys are invalid. Omit unknown details rather than guessing them.

`situationship` represents a source-described “썸” symmetrically. That representation does not
verify reciprocal attraction, exclusivity, or formal partnership. Preserve who described it and
the source's uncertainty in `claim_text` and basis. A unilateral feeling remains an attributed
observation. In particular, historical `dating_interest` may mean either feeling or an early
relationship: do not automatically convert it to `situationship` or to `user_feeling`.

`matched_on_app` and introduction types are historical relationship types, not new-write choices.
An app match or introduction can supply `origin` only when there is a separately supported
relationship claim. It does not establish an in-person meeting, friendship, 썸, or partnership.
Do not manufacture a relationship merely to attach origin metadata. Preserve a contextual claim
as an appropriate observation when no structural relationship is established. This revision
does not add meeting, appointment, calendar, or reminder tracking.

Existing legacy relationship records remain readable. An exact correction can retain their
structural fields while changing prose, source, or time; this exception does not permit new
legacy edges or changing their endpoints through reattribution. A representation change needs
source-based mapping and preserved record/evidence lineage; see the approved migration plan.

## 4. Record semantics

### One claim and a typed value

| Record | Use for | Required semantic fields |
| --- | --- | --- |
| `entity_facts` | Stable, queryable profile attributes | `entity_id`, supported `fact_type`, `content`, typed `value`, `claim_basis`, `confidence` |
| `entity_edges` | Structural relation between two known entities | `from_entity_id`, `to_entity_id`, `relation_type`, `claim_text`, `claim_basis`, `confidence` |
| `observations` | Preferences, feelings, interactions, schedules, cautions, patterns, contextual facts | `subject_entity_id`, `observation_type`, `content`, `claim_basis`, `confidence` |

Profile text values use `{"text":"..."}` and a matching `content`. For example, `job` describes a
profession; `role` describes a position/title. Do not put both profession and shift schedule in `job`.
`birth_date` and `birthday` use partial dates with `year`, `month`, `day` only when known, plus
`precision: year|month|day`. Matching `content` is `YYYY`, `YYYY-MM`, or `YYYY-MM-DD`.
Only annual `birthday` permits unknown year, rendered as `--MM` or `--MM-DD`. Never supply a
made-up first day or year to satisfy a date field.

New memory facts reject `memo`, `important_context`, `relationship_note`, and `contact_note`.
Use an appropriately typed observation instead. Existing legacy facts remain traceable during
migration; their existence is not permission to submit new generic facts.

### Basis is separate from topic

- `reported`: a human source states the claim. This means “the source reported it”, not external
  verification. Preserve “said”, “apparently”, and other uncertainty in content when relevant.
- `inferred`: the agent inferred the claim from the admitted human source. Include the actual
  source excerpt and qualified content; the inference itself is never evidence.
- `unknown`: the available historical basis cannot be determined. Do not upgrade it automatically.

`observation_type` is the topic: `preference` covers general food, travel, color and other interests;
`communication_preference` covers message/conversation style. Other examples are
`relationship_pattern` and `user_feeling`. `claim_basis` is the origin of the assertion. `confidence` is bounded 0–1 and does
not convert an inference or report into a verified fact. Do not send legacy `claim_type`,
`ai_use_policy`, or `confirmation_status` through the new memory payload.

### People and time

`subject_entity_id` selects whose context contains the observation. `related_entities` identifies
participants with roles. For a user's feeling about Minji, the subject may be Minji while
`{"entity_id":"self-id","role":"experiencer"}` identifies who felt it. Use `speaker` for the
person making a reported statement, `target` for its target, and `related` for other relevant people.
Allowed role values are `subject`, `related`, `mentioned`, `speaker`, `target`, `about`, and
`experiencer`; a request may contain at most 20 links and no duplicate entity/role pair. Do not infer
that the context owner is always the speaker or experiencer.

- `source.occurred_at`: when the source statement was made.
- Observation `occurred_at`: when the described event happened.
- `valid_from` / `valid_to`: when a claim applies; not a substitute for storage time.
- `created_at`: server storage time; never backfill it as an invented event date.

All submitted timestamps (`source.occurred_at`, record `occurred_at`, `valid_from`, `valid_to`,
`expected_updated_at`) require an explicit timezone offset; a naive timestamp is HTTP 422. Send
known times as ISO 8601 with `Z` or an offset; the service stores the same instant in UTC. Unknown
timestamps are omitted or null. Resolve relative dates only with a known source date and timezone. If precision is unknown, preserve
that uncertainty in content and leave exact timestamps empty. A date-sensitive plan is an
observation with the known time bounds, not a permanent profile fact.

## 5. Corrections without an approval stage

Read the exact old record before changing it. Active or disputed records can be changed; superseded/deleted records are stale targets. Use `correct` for a replacement claim, `retract` to
withdraw a claim without replacement, and `reattribute` when the claim belongs to another person.
All use a bounded human correction as source. Retraction changes old status to `deleted`; a
replacement changes it to `superseded`. Neither is a physical deletion. The service preserves the
old record and writes
change lineage; consumers use only current applicable records for ordinary context.

### Correct a profile claim

```json
{
  "request_id": "conversation-42:turn-11:correct-1",
  "action": "correct",
  "old_record_ref": "entity_facts:old-job-id",
  "record": {
    "record_type": "entity_facts",
    "payload": {
      "entity_id": "person-minji-id",
      "fact_type": "job",
      "content": "교사",
      "value": {"text": "교사"},
      "claim_basis": "reported",
      "confidence": 0.95
    }
  },
  "source": {
    "source_type": "agent_conversation",
    "actor": "user",
    "excerpt": "민지 직업을 내가 잘못 말했어. 교사야."
  }
}
```

### Reattribute to the intended person

```json
{
  "request_id": "conversation-42:turn-12:reattribute-1",
  "action": "reattribute",
  "old_record_ref": "observations:old-observation-id",
  "record": {
    "record_type": "observations",
    "payload": {
      "subject_entity_id": "person-jisu-id",
      "observation_type": "communication_preference",
      "content": "지수는 일정 확인 메시지를 짧게 받는 것을 선호한다고 말했다.",
      "claim_basis": "reported",
      "confidence": 0.9,
      "related_entities": [{"entity_id": "person-jisu-id", "role": "speaker"}]
    }
  },
  "source": {
    "source_type": "agent_conversation",
    "actor": "user",
    "excerpt": "짧은 일정 확인 메시지를 좋아한다는 건 민지가 아니라 지수 이야기야."
  }
}
```

Reattribution retains the record kind and changes its target person (or edge endpoint). `correct`
keeps the target people; use it to change the content or, where supported, record kind.

### Retraction

```json
{
  "request_id": "conversation-42:turn-13:retract-1",
  "action": "retract",
  "old_record_ref": "observations:old-observation-id",
  "source": {
    "source_type": "agent_conversation",
    "source_ref": "conversation-42/turn-13",
    "actor": "user",
    "excerpt": "민지가 짧은 메시지를 좋아한다는 건 내가 잘못 기억했어. 그 기록은 빼줘."
  },
  "reason": "사용자가 이전 진술을 철회함"
}
```

For `correct`, provide a replacement `record` using the same payload structure as create. For
`reattribute`, provide the corrected entity IDs and a self-contained replacement claim. Do not
silently rewrite an old record through PATCH or create an unrelated second record: both lose the
explicit old-to-new relationship. Fact/edge/observation records referenced by `memory_changes`
(including converted records) reject legacy PATCH/DELETE with HTTP 409 `memory_change_required`.
Use `/api/memories` with `correct`, `retract`, or `reattribute`; do not retry through another CRUD
endpoint or create an unlinked replacement. Legacy CRUD reads remain available, and old untracked
records retain their compatibility behavior. A cross-kind correction may move a broad legacy fact into a
proper observation for the same person when the source supports it. Changing a record does not
set `valid_to` to the correction time: a correction time is not proof of when the old claim stopped
being true.

If multiple records could be the user's target, retrieve their exact contents and resolve the
intended target. Do not retract all records matching a broad word. No candidate approval UI is
required for a clear correction.

## 6. Evidence and trust boundaries

Ordinary evidence is current-turn human text, bounded and attributable. These are not evidence:
assistant replies, generated summaries, tool output, retrieved Kinlayer context, prompts, logs,
compacted conversation summaries, or previous memory output. Source locators and author metadata
belong in `source`/Episode evidence, not pasted as a repeated prefix into every claim.

Explicitly authorized source material remains a separate operation:
`POST /api/material-imports/validate`, then `/submit`, with the bounded manifest, actual author,
source locator, and required authorization. A new authorized import immediately saves its
observations and returns `canonical_record_refs`; accepted candidate IDs are an internal provenance
ledger, not an approval queue. Source dates stay in Episodes rather than becoming event dates.
Save-first does not remove source authorization or
allow arbitrary tool output to become human evidence. Follow that endpoint's dedicated contract.

Do not fabricate provenance for historical rows missing an original Episode. Migrations may record
that the old database row was transformed, which is different from inventing a human source.

## 7. Readback and adapter requirements

After success, record returned `change_id`, `old_record_ref`, `new_record_ref`, and
`source_episode_id` in bounded adapter diagnostics. Read the exact record and affected context card.
Verify basis, subject/roles, type, source links, and that the old record no longer appears as current
following correction or retraction. `GET /api/memory-changes/{change_id}` returns the change record;
`GET /api/memory-changes?record_ref=<type:id>&limit=50&offset=0` lists matching old or new refs.
History exposes writer `actor`, action, old/new refs, source Episode ID, reason and creation time;
source author/excerpt are obtained through the linked Episode, not confused with writer identity. Embeddings remain supported: changed observation content needs
its own pending/rebuilt embedding; a missing provider must not block canonical storage.

Adapter tools should expose one `kinlayer_write_memory(request)` operation and ordinary read tools.
Adapters must persist stable request IDs across transport retries and report validation or conflict
errors. They must not translate successful writes into “waiting for review”, auto-accept hidden
candidates, or start a periodic approval loop. Existing candidate/curation/reconciliation endpoints
are compatibility/history interfaces, not a prerequisite for new memory.

The CLI accepts the same JSON envelope without translating it:

```bash
uv run kinlayer memory apply /path/to/memory-request.json --json
```

The effective config advertises the active write contract at `GET /api/system/config`:
`memory_write = {"endpoint":"/api/memories","review_required":false,"contract_version":"2"}`.
Adapters should discover this capability instead of inferring it from a legacy candidate endpoint.

## 8. Verify the wire contract

The running deployment's `/openapi.json` is the machine-readable input structure. For a local API:

```bash
curl --fail --silent http://127.0.0.1:8765/openapi.json > /tmp/kinlayer-openapi.json
python3 - <<'PY'
import json
from pathlib import Path
schema = json.loads(Path('/tmp/kinlayer-openapi.json').read_text())
print(json.dumps(schema['paths']['/api/memories'], ensure_ascii=False, indent=2))
PY
```

If bearer-token protection is enabled, use the adapter's existing secure authentication mechanism;
do not paste credentials into documentation or logs. Resolve referenced component schemas from
`components.schemas`. Examples here illustrate semantics; deployment validation and generated
OpenAPI own exact accepted types and optional fields.

## Self-perspective relationship assessments

Fetch `ontology.relationship_profile` and its independent `version` (`relationship-profile-v1`)
at session start and before unfamiliar axes/values; invalidate cached axis meanings when that
version changes. The structured type is `observations` / `relationship_assessment`, with target
person `subject_entity_id`, protected self `perspective_entity_id`, and registry-owned
`relationship_axis` / `relationship_value`. All four axes require `claim_basis: reported`: use
only the user's explicit assessment or UI selection, never an inference from interaction frequency,
missing logs, family, a relationship type, or another person's feelings. Importance and disconnection
must be explicitly stated. Unknown/unset means no active assertion, not a stored lowest enum value.

Use one independently correctable memory per axis and the normal genuine human source. Do not
supply additional observation participants. This is a current profile: do not write future
`valid_from` / `occurred_at`, any `valid_to`, calendar entries, or inferred decay. The current
projection is read through `GET /api/entities/{id}/relationship-profile`; each axis includes its
full source-backed record or null. Self itself has no self→self assessment, and no configured self
means writes are unavailable.

Before a new current-axis statement, resolve the target and protected self, read the profile, and
validate its entity, perspective, version and axis. A successful null row permits `create`. An
existing row requires its exact record, then `correct` with `old_record_ref` and
`expected_updated_at`; preserve the axis and perspective. An explicit unset request retracts the
exact axis record; an already-unset axis is a no-op. When the value changes, do not inherit the old
value's `valid_from` or `occurred_at`: send explicit null unless the new source supplies that time.
Same-value wording corrections may preserve known times. Source statement time stays independent.
Do not interpret a timeout, HTTP error, malformed row or stale record as empty.
A duplicate axis returns HTTP 409 `relationship_axis_conflict` with `details.current_record_ref`;
this is not permission to silently change targets and retry. Immutable prepared requests and
receipts retain their original request IDs and bodies on transport replay. Correcting source or
wording is still a source-backed operation, not a user approval queue.

Read back the exact record and the corresponding axis on the person's profile/context card.
Context packs keep the perspective, value, source and time. Importance can only break ties among
already relevant people; it must not create relevance, increase factual confidence or hide people.

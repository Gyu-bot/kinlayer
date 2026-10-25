# Kinlayer save-first memory writes (contract v2)

Canonical source: the deployed repo's `docs/agents/agent-write-instruction-pack.md`, `backend/src/kinlayer_backend/schemas/memories.py`, and the running `/openapi.json`. If those disagree with this note, the live deployment wins; check `/api/system/config.memory_write` first. `contract_version: "2"` is the write-contract version, not an `/api/v2` path.

## When the agent writes

- Automatic post-turn extraction is owned by `personal-context-router` and uses the current human turn only.
- Ordinary conversational facts and corrections are submitted once by PCR, not independently by the main agent as well. A separately authorized agent-operated repair outside the automatic route must choose one execution owner before writing. Reading context for an answer is not a write trigger.
- Explicitly authorized external material uses the separate material-import route, never this endpoint.

## Procedure

1. Apply the main skill's identity gate to every subject, related person, edge endpoint, profile target and correction target before preparing a write. Use existing name/alias resolution plus bounded relationship/trait context; check protected self when an owner-name duplicate is possible. Neither name-only `single_strong_match` nor `no_match` settles conflicting or unfamiliar identity. If uncertain, stop the person-dependent write and ask gyurin one grounded relationship/trait clarification, then resume without replaying past facts as current evidence. Create via the documented entity endpoint only when existing-person checks are complete and current human evidence establishes a distinct new real person. Re-resolve before any retry; an unknown commit or partial lookup never authorizes another create. Pronoun-only, fictional, public-figure, group, bot, or ambiguous references are never created or merged. Preserve existing exact-body journal replay; an identity clarification must not retarget an already submitted operation.
2. Fetch `/api/ontology` at session start and before an unknown type. Read version and complete relationship definitions (the repository helper returns `version` and `definitions.edge_types`). Cache by API instance and version; invalidate when the version changes and refresh after a type/direction/property rejection. `/api/ontology/edge-types` also returns the relationship version. New edges require `write_supported: true` and `support_level: supported`; active historical types are not new-write choices. Never guess or synonym-map a controlled value, including when the registry is missing or unavailable.
3. Split independently correctable claims: a profession, a work schedule, an appointment, a feeling, and an inference are separate requests even when they share one source sentence.
4. Send one `POST /api/memories` per claim and read the receipt.
5. Read back the exact record, the affected person's context card, and `/api/memory-changes?record_ref=<type:id>`.

## Envelope

`{request_id, action, old_record_ref?, record?: {record_type, payload}, source, created_by: "ai_agent", reason?, expected_updated_at?}`

- `request_id`: stable per logical operation, at most 160 characters. Transport retries reuse the same ID **and identical body**. A changed operation needs a new ID. The same ID with a different body is HTTP 409. For automatic hooks, persist the accepted ordered extraction before any write and recover it before reclassification on restart; hashing a newly generated model output alone cannot prevent replay duplicates. Preserve the private request journal through backups/restarts.
- `source`: `{source_type: agent_conversation|manual_entry, source_ref?, actor, excerpt, occurred_at?}`. `actor` is the real human author (`user` for gyurin's current message); never assistant/ai_agent/system/tool/unknown. `excerpt` is 1–4,000 characters of the supporting human text; never the full transcript. Do not pre-create Episodes or compute hashes. `source.occurred_at` is when the statement was made, with a timezone.
- New payloads never include `claim_type`, `ai_use_policy`, `confirmation_status`, `sensitivity`, or candidate fields.

## Record payloads

- `observations`: `subject_entity_id`, registry `observation_type`, `content`, `claim_basis`, `confidence`; optional `related_entities[{entity_id, role}]`, event `occurred_at`, `valid_from`/`valid_to`. Roles: `subject`, `related`, `mentioned`, `speaker`, `target`, `about`, `experiencer`; at most 20 and no duplicate entity/role pair. For gyurin's feeling about a person, the subject is that person and gyurin's self entity is the `experiencer`.
- `entity_facts`: `entity_id`, `fact_type`, `content`, typed `value`, `claim_basis`, `confidence`. Text facts use `value: {"text": ...}` with identical `content`. `birth_date`/`birthday` use only known `year`/`month`/`day` plus `precision: year|month|day` (content `YYYY`, `YYYY-MM`, `YYYY-MM-DD`; annual `birthday` may omit the year as `--MM` or `--MM-DD`). Never invent a missing date part. New `memo`, `important_context`, `relationship_note`, and `contact_note` facts are rejected; use an observation.
- `entity_edges`: `from_entity_id`, `to_entity_id`, `relation_type`, `claim_text`, `claim_basis`, `confidence`; omit `directed` to use the ontology default. Feelings, preferences, cautions, reply strategy, or a single meeting are observations, not edges.
- `claim_basis`: `reported` (a human source said it, not verified truth), `inferred` (agent inference from human evidence; the inference is never itself evidence), or `unknown` (never auto-upgraded). `confidence` (0–1) does not convert a report or inference into fact.
- Time: `source.occurred_at` is the statement time, observation `occurred_at` is the event time, and `valid_from`/`valid_to` is the applicability range. Never copy one into another. Every timestamp needs `Z` or an offset; unknown values are omitted. Resolve relative dates only from a known source date and timezone.

## Relationship definition revision

`relationship-v1` supplies source-role `label`, target-role `inverse_label`, category, description, examples, direction, allowed property schema, support/write status, and source-dependent replacement hints. Use the returned from/to meaning; do not create inverse edges merely for display. Optional properties are `context`, `relationship_detail`, and `origin`, each a nonempty string no longer than 300 characters. Omit unknown details; do not invent extra keys.

Source-described `situationship` (썸) is symmetric, without independently verifying reciprocal attraction, exclusivity, or formal partnership. A one-sided feeling remains an attributed observation. Historical `dating_interest` must not be blindly changed into 썸 or a feeling. An app match or introduction describes acquaintance background, not proof of a meeting or partnership; do not create a stronger relationship just to attach origin metadata. This revision adds no appointment, meeting, calendar, or reminder tracking.

Historical types remain readable. `correct` may preserve an exact existing legacy type, endpoints, direction and properties while changing text/source/time; `retract` may withdraw that exact record. New legacy edges, changed legacy structures, and legacy reattributions are not permitted. A `replacement_type` hint requires checking the source and endpoint roles, never an automatic rewrite. After an ontology-related 422, refresh before reasoning about a new operation; do not automatically mutate or replay a semantically rejected body.

## Corrections

- `correct`: exact old ref plus a complete replacement record for the same target (not a PATCH fragment).
- `retract`: exact old ref and a human retraction source; no record.
- `reattribute`: exact old ref plus the same `record_type` with the corrected person/edge endpoint and a complete replacement.
- Read the exact old record first (`/api/entity-facts/{id}`, `/api/edges/{id}` for `entity_edges:` refs, `/api/observations/{id}`) and pass its `updated_at` as `expected_updated_at`. Only active/disputed records can change.
- If several records could be the target, inspect their content and choose exactly one, or ask. Never retract/correct every keyword match.
- Old records become `superseded` or `deleted`, never physically removed. Do not fill `valid_to` with the correction time. Preserve existing dates, participant roles/confidence and edge properties when the correction leaves them unchanged; omission is distinct from an explicit supported clear.

## Responses and failure handling

- HTTP 200 on first success and replay: `{change_id, action, old_record_ref, new_record_ref, source_episode_id}`. A retraction has no new ref.
- Timeout or connection error: retry the same ID/body. A timeout alone is not proof of failure.
- 409: idempotency conflict, stale/non-current old record, or `memory_change_required`. Re-read current records and history before deciding anything new.
- 404 missing target; 422 validation. Never alter facts, sources, or dates to get past validation.
- Report the reached state exactly: saved, corrected, failed, conflict, or ambiguous. If the API acknowledged a commit but readback fails, keep its receipt as committed-but-unverified; a transport timeout can mean unknown commit state. Neither means definitely failed or pending review.
- Embeddings are derived indexes. `pending` or missing embeddings do not block or condition a save, and a write must not trigger backfill.

## Read and history paths

`GET /api/observations/{id}`, `/api/entity-facts/{id}`, `/api/edges/{id}`, `/api/episodes/{id}`, `/api/entities/{id}/context-card`, `POST /api/context/retrieve`, `POST /api/context/pack`, `GET /api/memory-changes/{change_id}`, and `GET /api/memory-changes?record_ref=<type:id>&limit=50&offset=0`. The change-history `actor` is the writer; the human author and excerpt come from the linked Episode/provenance.

The maintained CLI accepts the same envelope unchanged: `KINLAYER_API_URL=<configured base> uv run kinlayer memory apply /path/to/request.json --json` from the deployment repo. Keep any API token in the existing secure environment, never in files, logs, or chat.

## Current relationship assessments (`relationship-profile-v1`)

Registry `relationship_profile` has its own version and `axes` metadata with label, description and
values. Use `record_type: observations`, `observation_type: relationship_assessment`, the other
person as `subject_entity_id`, protected self as `perspective_entity_id`, and one supplied
`relationship_axis` / `relationship_value`. Every axis must be explicitly reported by the user.
Do not infer these values, use third-party feelings as self perspective, or add related participants.
Current-only values reject future applicable/evaluation times and any valid_to. No appointment log.

Read `GET /api/entities/{id}/relationship-profile` before choosing create/correct. Each axis has
value/label/full MemoryRead record, or explicit nulls. Resolve a present axis to its exact MemoryRead
and updated_at, then correct using that old_record_ref and expected_updated_at. Axis and perspective
cannot be changed by correction. When a VALUE changes, old valid_from/occurred_at are not the new
value's times: clear them to null unless the new source supplies a real time. Same-value wording
corrections may preserve times. Source statement time is separate.

An explicit reset retracts the exact axis; already unset is no-op, never a new unknown value. Never
treat timeout, malformed profile, missing self or an absent API capability as an empty axis. A 409
relationship_axis_conflict (current_record_ref in details) or stale precondition needs a newly
reasoned operation, not silent target reselection. Frozen body/ID replay happens before any current
profile lookup. Read back the record and current axis/source afterward. Importance only affects
soft ordering among already relevant people, not truth confidence or who may be retrieved.

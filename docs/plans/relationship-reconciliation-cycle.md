# Relationship Reconciliation & Clarification Cycle

**Status:** Approved for implementation
**Approved by user:** 2026-08-25
**Kinlayer branch:** `codex/kinlayer-reconciliation-cycle`
**Hermes plugin branch:** `feature/kinlayer-reconciliation-cycle`
**Discord review target:** `1541811228530315365` (`kinlayer`, text channel)

## 1. User outcome

Extend the deployed periodic curation system with a separate reconciliation cycle:

```text
pending candidates + recent canonical changes
→ deterministic anomaly collection
→ bounded source-session review by Hermes
→ self-resolve only deterministic no-question cases
→ group genuinely unresolved questions by person/identity issue
→ deliver each question through Hermes' native Discord send engine and persist its message ID
→ user replies to that exact Discord message
→ Hermes interprets the reply into an allowlisted answer plan
→ Kinlayer applies user-confirmed candidate/entity corrections
→ candidate, canonical record, evidence, and context readback
```

The user must not review candidates one by one. Questions are exceptions after evidence review, not the normal curation path.

Named-person creation is intentionally permissive: a pending `new_entity` backed by user-authored evidence may be promoted automatically when it contains a specific proper name and deterministic guards find no self, role-title, pronoun, or exact-existing-identity conflict. The review cycle repairs later duplicates through verified merge/mapping actions instead of requiring approval before every person exists.

## 2. Boundaries

### Must ship

- Review blocked/pending candidates and newly created canonical records incrementally.
- Detect self-as-person mistakes, exact duplicate candidates, likely spelling/name variants, duplicate unresolved people, role-title identities, and suspicious new canonical records.
- Start from candidate evidence `source_ref`; inspect exact source sessions and only then a bounded same-name lookup when needed.
- Ask only what remains ambiguous after that review.
- Deliver questions only to Discord channel `1541811228530315365`.
- Support natural-language replies sent as Discord replies to a review batch message.
- Apply only allowlisted actions tied to a still-open staged review item.
- Verify every mutation by reading back candidates, canonical records, evidence links when applicable, and context cards/projections.
- Stay silent when there is nothing new to ask.

### Minimum safeguards

- No Hermes core changes, new model-facing tool, new turn hook, daemon, or full-session sweep.
- Keep the existing `post_llm_call` hook and plugin CLI; extend CLI commands and skip normal post-turn extraction for reconciliation reply markers.
- Use current session environment (`HERMES_SESSION_PLATFORM`, chat/thread ID, user ID, message ID) to authorize answer application.
- Closed JSON schemas, bounded strings/counts, no raw provider payloads or full transcripts in durable state.
- Idempotent retry after partial network/readback failure.
- Delivery handshake using the cron job’s prior `last_status` and `last_delivery_error`; do not permanently suppress an undelivered batch.
- One active delivery set at a time, one stable Discord receipt per question, cooldown/dedupe by review fingerprint.
- No product-level three-question cap. Group related candidates into one person-level question, rank by risk/age, and use configurable operational ceilings plus Discord rate/message-size limits only to prevent floods.

### Deferred

- General-purpose human review UI.
- Full semantic person deduplication across every session.
- Automatic canonical entity merge based on model similarity.
- Contact/address/profile-field review outside the current relationship identity/candidate scope.
- A second Hermes bot/profile.

## 3. Ownership

### Kinlayer

- Candidate and canonical source of truth.
- Deterministic user-confirmed grouped resolution.
- Row locking, transaction, lifecycle transition, idempotency, and exact readback.
- No Discord/session_search/model client.

### Hermes personal-context-router

- Read-only anomaly collection and compact review snapshots.
- Local notification/reply state needed only for dedupe and delivery handshake.
- CLI commands used by cron and the dedicated Discord channel session.
- Validation of batch/item IDs, target channel, authorized user, allowed answer options, and bounded source metadata.

### Scheduled Hermes agent

- Calls reconciliation prepare.
- Reads exact source sessions via `session_search` and performs at most one bounded name query per review item.
- Produces a closed review plan.
- Calls reconciliation stage and delivery.
- Delivery uses Hermes' existing send engine (`hermes send`/`send_message_tool`) and stores the returned Discord `message_id`; it does not rely on cron final-response delivery for correlation.
- The cron delivery target is local/silent so the scheduled agent cannot duplicate the plugin-owned question sends.

### Dedicated Discord channel session

- A `pre_gateway_dispatch` plugin hook authenticates the native Discord reply reference against the persisted outbound `message_id`, exact channel ID, guild/user allowlist, and question nonce before the main turn.
- The hook claims the inbound reply message once and rewrites the turn with bounded verified review metadata; copied text or a bare marker is never sufficient authority.
- The main turn reads the staged item through plugin CLI.
- Converts the user’s answer into an allowlisted answer plan.
- Calls plugin CLI apply.
- Reports verified result or asks a narrower follow-up without mutation.

## 4. Review-item classes

1. `self_entity_false_positive`
   - Deterministic when a pending `new_entity` exactly identifies Kinlayer protected self.
   - May be rejected without asking after exact protected-self readback.

2. `exact_pending_duplicate`
   - Exact normalized candidate type + payload duplicate.
   - May supersede/archive duplicates while retaining one pending candidate; never auto-create an entity.

3. `auto_promotable_named_entity`
   - User-authored pending `new_entity` with a specific proper name and no deterministic conflict.
   - Promote automatically on the normal curation path; reconciliation audits the resulting entity and later asks only when another entity/candidate appears to overlap.
   - Never applies to protected self names/aliases, pronouns, honorific-only or role-only labels, blank/one-character names, or exact active entity/alias matches.

4. `existing_entity_name_variant`
   - Candidate may refer to an existing entity/alias.
   - Ask unless exact deterministic alias/evidence rules already prove the mapping.
   - User choices: map to existing entity, different person with corrected name, do not store, unsure.

5. `duplicate_new_entity_group`
   - Multiple pending `new_entity` candidates likely refer to one person.
   - The entities may already exist because named-person creation is permissive.
   - User choices: same person/merge or map, different people, do not store, unsure.

6. `role_title_identity`
   - Honorific/job role without stable identity.
   - User choices: provide name/stable alias, do not store, unsure.

7. `recent_canonical_anomaly`
   - Newly created canonical record conflicts with, duplicates, or targets the wrong entity.
   - User choices are record-specific: keep, correct through explicit correction, supersede/archive where supported, unsure.

## 5. Kinlayer contract

Add one small durable reconciliation action ledger. Existing single-candidate endpoints do not provide reply-level idempotency, grouped atomicity, stale-version fencing, or fresh-session readback after a user-confirmed action.

Routes:

```text
POST /api/reconciliation/actions
GET  /api/reconciliation/actions/{action_id}
```

The POST route is fail-closed unless a dedicated `KINLAYER_RECONCILIATION_TOKEN` is configured and supplied as a bearer credential. Do not require the broad `KINLAYER_API_TOKEN` solely for this feature because that would also gate existing browser/read surfaces. GET action readback follows the same dedicated credential boundary. Secret creation and live injection are a separate deployment approval; source/tests ship disabled by default.

`reconciliation_actions` stores only bounded control/audit data: action ID/type/status, unique idempotency key, normalized request fingerprint, candidate IDs and expected status/`updated_at`/payload-evidence digests, target/primary entity IDs, derived candidate IDs, confirmation episode ID, outcome canonical refs, compact readback summary, error code, and timestamps. It never stores Discord payloads, full question/reply text, sessions, prompts, or model output.

The same uncommitted ledger also supports canonical-person cleanup. `merge_existing_entities` uses
empty candidate inputs, exact bounded snapshots for distinct active non-self person source/target
rows, and one internally created user-explicit merge candidate accepted in the ledger transaction.
`archive_existing_entity` uses one exact source snapshot and is limited to an empty active non-self
person produced by the reviewed `new_entity` path; owned canonical context or merge dependencies
fail closed and require merge or correction.

Closed request fields:

```json
{
  "resolution_id": "stable idempotency key",
  "action": "reject_candidates | map_to_existing_entity | confirm_new_entity_group | rename_and_accept_new_entity | merge_existing_entities | archive_existing_entity",
  "candidate_ids": ["..."],
  "expected_candidates": [
    {
      "id": "...",
      "status": "pending",
      "updated_at": "...",
      "payload_digest": "sha256:...",
      "evidence_digest": "sha256:..."
    }
  ],
  "expected_entities": [
    {
      "id": "...",
      "status": "active",
      "updated_at": "...",
      "entity_digest": "sha256:..."
    }
  ],
  "source_entity_id": null,
  "target_entity_id": null,
  "canonical_name": null,
  "display_name": null,
  "resolution_note": "bounded machine-readable summary",
  "source": {
    "user_explicit": true,
    "source_type": "agent_conversation",
    "source_ref": "bounded Discord message ref",
    "source_actor": "user",
    "body_hash": "sha256:..."
  }
}
```

Requirements:

- Lock all referenced candidates in deterministic order.
- Every candidate must still match the exact reviewed status/version/payload/evidence snapshot or already match the exact requested terminal state from an earlier retry.
- `map_to_existing_entity` requires one exact reviewed active target entity snapshot, locks that target with the candidates, and records a record reference on all resolved candidates.
- `confirm_new_entity_group` accepts one deterministic retained candidate, creates exactly one canonical entity, and supersedes the other group members in one transaction.
- `rename_and_accept_new_entity` edits one retained payload with user-provided bounded name, accepts it, and supersedes duplicates in one transaction.
- `reject_candidates` rejects all specified candidates atomically.
- Protected self can never be newly created, renamed, or merged.
- Repeated `resolution_id` returns the same verified result and never creates another canonical record.
- Response includes all candidate statuses, canonical refs, entity readback, and verification state.
- Persist no raw Discord question, raw reply, full session text, or model output.

Execution persists the action intent first, performs the candidate/entity changes and action outcome refs in one transaction, commits as `committed_unverified`, then opens a fresh DB session for exact candidate/canonical/evidence/context readback. A retry after commit performs readback only. A reused idempotency key with another request fingerprint returns `409`.

The existing curation executor must also re-check decision/candidate/run state after acquiring its locks. If another executor already committed the decision, reconcile/read back it instead of re-evaluating or overwriting its status. This is required before named `new_entity` promotion can be safely enabled.

### Named-person automatic promotion gate

Keep `new_entity` promotion inside the normal Kinlayer curation transaction, not the post-turn hook. Permit it only when deterministic policy verifies all of the following:

- entity type is `person`;
- at least one linked evidence episode is user-authored and the bounded excerpt supports the name;
- display/canonical name passes the specific-person name validator;
- name is not protected self or a protected-self alias;
- name is not a pronoun, generic relationship noun, honorific-only label, or role/title-only label;
- no exact normalized active entity name or alias already exists;
- candidate has no unresolved identity/conflict/schema/evidence reason;
- the plan action is a single-candidate accept with no merge/alias inference.

Fuzzy similarity never blocks creation by itself; it schedules later reconciliation. Exact collisions block creation and become a mapping review item.

## 6. Plugin state

Prefer plugin `ctx.state` under the profile-scoped plugin-data directory. If the installed plugin API cannot expose `ctx.state` to CLI handlers, use this compatibility path with identical atomic/mode guarantees:

```text
$HERMES_HOME/state/personal-context-router/kinlayer-reconciliation.json
```

State contains only:

- schema version;
- last scanned candidate/canonical cursor;
- review fingerprints and bounded item metadata;
- active staged delivery set with question IDs, item IDs, allowed options, target guild/channel/user, question nonce/version, and staged time;
- delivery state (`planned`, `sending`, `delivered`, `awaiting_reply`, `claimed`, `applying`, `committed_unverified`, `verified_applied`, `delivery_failed`, `stale`, `expired`);
- mandatory Discord question message ID, reply message IDs, Kinlayer `resolution_id`s, and compact verified outcomes;
- cooldown/suppression timestamps.

Never store full sessions, full provider outputs, chain of thought, secrets, or unbounded user replies.

Writes are atomic with mode `0600`. Re-read state inside the final write lock before transitions.

## 7. Plugin CLI

Extend `hermes context-router`:

```text
reconciliation-prepare [--quiet-no-change]
reconciliation-stage --plan-file <json>
reconciliation-deliver --delivery-set-id <id>
reconciliation-question --question-id <id>
reconciliation-apply --question-id <id> --claim-token <token> --answers-file <json>
reconciliation-status
```

### Prepare

- Reconcile the prior pending delivery against the configured cron job’s current ledger entry.
- Collect bounded pending/canonical anomalies.
- Apply only deterministic no-question cleanup through Kinlayer and verify it.
- Output no more than a bounded set of review candidates for the scheduled agent.
- Include source session IDs/search terms but no raw full-session bodies.

### Stage

- Accept a closed plan that references only current prepared item fingerprints.
- Require the scheduled agent to state which exact source sessions and name query were checked.
- Reject questions answerable from the inspected evidence.
- Group candidates that concern the same person/identity issue into one question.
- No fixed three-question limit. Respect a configurable per-run operational ceiling, a hard safety ceiling, Discord rate limits, and the single-message size limit; carry the rest to the next run without losing priority.
- Persist `planned` questions and unique opaque nonces before delivery.

Marker example:

```text
[KINLAYER-REVIEW batch=<batch-id>]
```

Each question carries a stable `item=<item-id>` marker and explicit answer options. The marker aids usability and recovery but is not authorization.

### Deliver

- Transition one question at a time from `planned` to `sending` before the external call.
- Send through Hermes' native send engine to `discord:1541811228530315365` and require a successful JSON result containing the exact `chat_id` and `message_id`.
- Persist the returned `message_id`, then mark `delivered/awaiting_reply`.
- On send-ack loss, use the opaque nonce to find the bot's already-created recent channel message before retrying; never blindly duplicate a question.
- Keep each person-level question in one Discord message. If it would exceed the platform limit, shorten the evidence summary rather than splitting one question across unrelated message IDs.

### Apply

- Require a claim created by `pre_gateway_dispatch` from an authenticated Discord event whose native `reply_to_message_id` equals the persisted outbound question `message_id`.
- Require exact configured guild/channel/authorized-user IDs, current inbound Discord message ID, opaque question nonce/version, and one-time claim token.
- Require a delivered, open question and allow only its item options.
- Permit partial answers; ambiguous items remain open and no mutation occurs for them.
- Send user-confirmed actions to Kinlayer with stable `resolution_id`s.
- Read back and persist compact results before reporting success.

## 8. Discord configuration

Add channel skill binding for `1541811228530315365`:

```text
gyurin-personal-context
kinlayer-local
```

Add a channel prompt that:

- recognizes the plugin-rewritten verified reconciliation reply context, not copied marker text;
- fetches the claimed question before interpreting the answer;
- writes an answers JSON file under `$HERMES_HOME/tmp/personal-context-router/<run>/`;
- runs `hermes context-router reconciliation-apply` with the one-time claim token;
- reports only verified actions and any unanswered ambiguity;
- otherwise treats the channel as normal Kinlayer/personal-context discussion;
- never accepts a bare marker typed by another user or from another channel.

Do not make the channel globally free-response unless reply behavior proves a mention is required; Discord replies to the bot normally carry the native reply reference and the bot has participated.

## 9. Scheduler

Create a separate agent-driven cron after deployment.

- Cadence: every 6 hours, offset from canonical curation so the latter finishes first.
- Cron delivery: `local`; question delivery is performed explicitly by `reconciliation-deliver` so outbound Discord message IDs are captured.
- Script: thin wrapper under `$HERMES_HOME/scripts/` calling reconciliation prepare.
- Skills: `gyurin-personal-context`, `kinlayer-local`.
- Toolsets: session search, terminal/file/skills as required.
- Silent/local final response when `wakeAgent=false` or after explicit question delivery.
- The cron prompt never reads bot tokens or calls raw Discord REST; the plugin invokes Hermes' native send engine and validates the structured receipt.

## 10. Current dogfood expectations

The first real review should classify:

- `민규` pending `new_entity` as protected-self false positive and reject it without asking.
- `해영` as a likely typo/name variant of existing `혜영`, requiring one confirmation.
- duplicate `황윤영` candidates/entities as one likely person; named-person creation may already have produced one or more entities, so ask whether they should be merged rather than requiring pre-creation approval.
- duplicate role-title `전무님` candidates as one unresolved role identity, requiring a name/stable alias or a do-not-store answer.
- the recently consolidated canonical observation as verified and non-questionable unless a fresh audit finds an actual conflict.

## 11. Verification

### Unit/focused

- anomaly grouping and fingerprints;
- bounded source-session references;
- closed plan/answer schemas;
- target channel/user enforcement;
- marker spoof rejection;
- person-level grouping, dynamic batching, operational safety ceiling, and cooldown;
- named `new_entity` automatic promotion and role/self/pronoun exclusion;
- outbound Discord receipt persistence and native reply-reference enforcement;
- copied-marker, wrong-author, wrong-channel, stale-reply, and duplicate-inbound rejection;
- delivery success/failure handshake;
- partial answers;
- state lock/concurrent update protection;
- deterministic self rejection;
- grouped candidate transaction rollback and retry idempotency;
- exact canonical/entity/evidence/context readback;
- reconciliation replies skipped by ordinary post-turn candidate extraction.

### Integration

1. Disposable PostgreSQL migrated from prior head to new head.
2. Synthetic candidates reproduce self, typo variant, duplicate new person, role title, and safe canonical cases.
3. Scheduled-agent dry run uses a disposable Hermes home and mocked session-search results.
4. Stage a question batch and verify message under 2000 chars.
5. Apply a synthetic reply from correct and incorrect thread/user environments.
6. Verify wrong target/spoof/stale/concurrent replies fail closed.
7. Verify one entity only, candidate states exact, correction/audit source bounded, and repeat apply is idempotent.
8. Run affected backend suite, Ruff, plugin smoke, Python compile, shell syntax, and installed-layout fresh-process CLI.

### Live rollout

1. Backup live DB/Compose/plugin/state.
2. Push Kinlayer branch and read back exact SHA.
3. Deploy migration/API in existing apply mode; verify health and old curation behavior.
4. With separate approval, create/inject the dedicated reconciliation bearer secret into casa and Hermes without printing or persisting it in config; verify unauthenticated requests fail and plugin-authenticated readback succeeds.
5. Install plugin update disabled for reconciliation; verify installed-layout CLI.
6. Configure target channel/user and channel prompt/bindings.
7. Run reconciliation prepare/stage in dry-run/local mode; inspect the first batch.
8. Obtain Gateway restart confirmation at the actual activation boundary.
9. Send one real batch to `1541811228530315365`.
10. User replies to that message; verify exact Kinlayer resolution and context readback.
11. Enable recurring review cron only after the reply E2E passes.

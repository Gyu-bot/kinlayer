# Relationship Reconciliation & Clarification Cycle

One authenticated reply resolves identity and every clear bounded same-person context claim together. Prior
promotion accepts only original user-authored evidence locked to the reviewed candidate snapshot, never an
assistant summary. Do not ask the user to repeat authenticated text; report only freshly verified categories.

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
→ user replies naturally to that exact Discord message
→ Hermes interprets the whole reply as an ordinary conversational turn, separating reconciliation intent, new information, follow-up needs, and any other requested action
→ Kinlayer applies user-confirmed candidate/entity corrections
→ candidate, canonical record, evidence, and context readback
```

The user must not review candidates one by one. Questions are exceptions after evidence review, not the normal curation path.

### Conversational user experience

Reconciliation is a generative dialogue, not a form, decision tree, or scripted chatbot.

- Hermes reviews the current anomaly, exact source sessions, bounded same-name history, and existing Kinlayer context, then writes a fresh natural-language Korean question suited to that specific situation.
- The user-visible Discord message contains only that natural question. Batch IDs, item IDs, message IDs, nonces, fingerprints, internal option names, action names, receipts, and validation instructions remain private implementation state.
- The user answers in unrestricted natural language. A reply may resolve the original ambiguity, add new person/relationship information, correct the premise, request a different action, ask a question back, or combine several of these.
- Hermes handles the reply as a real conversation. It may ask a natural follow-up when needed, perform ordinary authorized Hermes actions, route new durable person information through the normal Kinlayer candidate/correction path, and submit only the reconciliation mutations that the backend can verify safely.
- A natural follow-up sent by Hermes becomes the next private reply anchor for the same open review. The plugin carries the binding forward using authoritative own-message reply metadata plus a private content digest; the user must never be told to reply again to an older technical anchor.
- All unresolved items for one person/identity issue are combined into one context-specific generated question. Different internal items must not leak as multiple form-like prompts merely because they have different action options.
- Closed option/action schemas remain an internal execution boundary for canonical mutations; they are never the user's input format and must not reduce the conversation to selecting a code.
- Native Discord reply metadata authenticates who answered which question. Authentication metadata must not shape or leak into the visible wording.
- A verified reconciliation reply is not globally excluded from post-turn extraction. Internal metadata is stripped, while the user's clean natural-language content remains eligible for ordinary evidence routing so additional information is not lost.

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
- Domain question state, closed answer compilation, Kinlayer apply/readback, and bridge-spec handoff.
- CLI commands used by cron and the dedicated Discord channel session.
- Validation of item snapshots, attached bridge conversation ID, allowed answer options, and bounded source metadata.
- No Discord send, message-ID receipt, native-reply authentication, bot token, or session switching.

### Standalone proactive-conversation bridge

- Owns Discord delivery/ACK recovery, message IDs, exact route/owner validation, native-reply
  authentication, and the current Hermes session lease.
- Supplies private adapter context with the attached bridge conversation ID and PCR question reference.
- Stores no Kinlayer candidate/entity/domain payload.

### Scheduled Hermes agent

- Calls reconciliation prepare.
- Reads exact source sessions via `session_search` and performs at most one bounded name query per review item.
- Produces a closed review plan.
- Calls PCR stage, standalone bridge stage, PCR attach, then standalone bridge deliver.
- Uses the exact silence contract after bridge delivery so cron final-response delivery cannot duplicate
  the question.

### Dedicated Discord channel session

- The standalone bridge authenticates the native reply against its exact outbound message, route,
  owner, and one-time claim before the main turn, then attaches the current session lease.
- The main turn requires private bridge adapter context and reads the staged PCR item through plugin CLI;
  copied text or a bare marker is never sufficient authority.
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
  "action": "reject_candidates | map_to_existing_entity | confirm_new_entity_group | accept_existing_entity_observation_group | rename_and_accept_new_entity | merge_existing_entities | archive_existing_entity",
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
- `accept_existing_entity_observation_group` requires one or more exact pending observation candidates plus the exact snapshot of their common active non-system person target. After candidate locks, it derives the union of that target, every observation subject, and every related entity and locks the full union once in globally sorted ID order before accepting every candidate through the canonical observation writer in one transaction. It creates or supersedes no entity.
- `rename_and_accept_new_entity` edits one retained payload with user-provided bounded name, accepts it, and supersedes duplicates in one transaction.
- `reject_candidates` rejects all specified candidates atomically.
- Protected self can never be newly created, renamed, or merged.
- Repeated `resolution_id` returns the same verified result and never creates another canonical record.
- Response includes all candidate statuses, canonical refs, entity readback, and verification state.
- Persist no raw Discord question, raw reply, full session text, or model output.

Execution persists the action intent first, performs the candidate/entity changes and action outcome refs in one transaction, commits as `committed_unverified`, then opens a fresh DB session for exact candidate/canonical/evidence/context readback. A retry after commit performs readback only. A reused idempotency key with another request fingerprint returns `409`.

Before that intent lookup, Kinlayer requires exactly one PCR answer binding signed with a separate
deployment secret, not the reconciliation bearer. The binding covers the actual question/item,
full agenda, resolution/action body, and exact context claims. It is stored with the same ledger row,
revalidated and returned by fresh readback, and cannot be substituted by a bearer-only caller.

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
- active staged delivery set with question IDs, item IDs, allowed options, exact route/owner,
  standalone bridge conversation ID/key, and staged time;
- domain state (`staged`, `awaiting_reply`, `applying`, `committed_unverified`,
  `verified_applied`, `stale`, `expired`, `cancelled`);
- Kinlayer `resolution_id`s and compact verified outcomes. Discord message IDs, reply IDs,
  claim tokens, nonces, and delivery receipts belong only to the standalone bridge state;
- cooldown/suppression timestamps.

Never store full sessions, full provider outputs, chain of thought, secrets, or unbounded user replies.

Writes are atomic with mode `0600`. Re-read state inside the final write lock before transitions.

## 7. Plugin CLI

Extend `hermes context-router`:

```text
reconciliation-prepare [--quiet-no-change]
reconciliation-stage --plan-file <json> --bridge-spec-file <json>
reconciliation-attach-bridge --question-id <id> --conversation-id <id>
reconciliation-question --question-id <id>
reconciliation-apply --question-id <id> --bridge-conversation-id <id> --answers-file <json>
reconciliation-cancel --question-id <id>
reconciliation-status
```

`reconciliation-deliver` is deprecated and fail-closed; it returns `bridge_required` without
sending. Delivery is owned by the standalone proactive-conversation bridge.

### Prepare

- Reconcile the prior pending delivery against the configured cron job’s current ledger entry.
- Collect bounded pending/canonical anomalies.
- Apply only deterministic no-question cleanup through Kinlayer and verify it.
- Output no more than a bounded set of review candidates for the scheduled agent.
- Include source session IDs/search terms but no raw full-session bodies.
- Expose only raw-free candidate evidence commitments and opaque handles; exact excerpts are not
  generic prepare output.

### Stage

- Accept a closed plan that references only current prepared item fingerprints.
- Require the scheduled agent to state which exact source sessions and name query were checked.
- Reject questions answerable from the inspected evidence.
- Group candidates that concern the same person/identity issue into one question.
- For every multi-record identity item, require one closed `record_summaries` object per prepared
  record in canonical order: exact internal `record_id`, exact snapshot `record_digest`, and one
  bounded natural `summary`. Validate the bindings against the prepared candidate/entity snapshots;
  keep summaries as private visible grounding only and never treat them as evidence. Never expose
  the IDs or digests.
- Optionally accept at most six closed `prepared_context_claims` per question item. Stage privately
  revalidates the exact candidate snapshot and user-authored evidence through the token-gated
  candidate-evidence endpoint, requires one unique exact excerpt substring, derives offsets and
  effective policy, discards the excerpt, and persists only typed commitments bound to the item.
- Consume every source-bearing plan once from a bounded mode-0700 directory/mode-0600 regular file,
  unlinking it after both successful and failed stage consumption.
- No fixed three-question limit. Respect a configurable per-run operational ceiling, a hard safety ceiling, Discord rate limits, and the single-message size limit; carry the rest to the next run without losing priority.
- Persist staged domain questions before bridge handoff.

### Bridge handoff and delivery

- PCR writes one bounded bridge spec only to an explicitly requested validated private mode-0600
  file. Stage/resume/reissue/status never return it inline.
- Attach the returned bridge conversation ID to the exact PCR question before delivery.
- The standalone bridge owns Discord send/ACK recovery, exact native-reply authentication,
  route/owner matching, message IDs, and session lease. PCR stores no Discord delivery receipt.
- On unknown delivery, use bridge status/deliver only; never blindly send a second question.
- Keep each person-level question in one Discord message. If it would exceed the platform limit,
  shorten the bounded summaries rather than splitting the question.

### Apply

- Require private bridge context containing adapter key/version plus the exact bridge conversation ID
  and PCR question reference. Never infer authority from visible text or a copied marker.
- Require the supplied `--bridge-conversation-id` to equal the ID attached to the open PCR question.
- Require the same exact ID on the private question-read command and return no agenda for missing,
  wrong, staged-unattached, terminal, or attention-receipt-mismatched questions.
- Allow only the question's current item options and fresh candidate/entity snapshots.
- Permit partial answers; ambiguous items remain open and no mutation occurs for them.
- Send user-confirmed actions to Kinlayer with stable `resolution_id`s.
- Merge stage-bound prepared claims automatically with exact current-reply claims, fix current
  context at medium/cautious, preserve stricter prepared policy, and bind all claims into the one
  submission/action digest before one PCB proof consume and one backend POST.
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
- runs `hermes context-router reconciliation-apply` with the private bridge conversation ID;
- reports only verified actions and any unanswered ambiguity;
- otherwise treats the channel as normal Kinlayer/personal-context discussion;
- never accepts a bare marker typed by another user or from another channel.

Do not make the channel globally free-response unless reply behavior proves a mention is required; Discord replies to the bot normally carry the native reply reference and the bot has participated.

## 9. Scheduler

Use the existing separate agent-driven cron after deployment.

- Cadence: every 6 hours, offset from canonical curation so the latter finishes first.
- Cron delivery: `local`; the cron stages and delivers through the standalone bridge, then returns
  the exact silence contract so scheduler delivery cannot duplicate the question.
- Run reconciliation status first and resume any active PCR/bridge conversation before preparing
  another review item.
- Skills: `gyurin-personal-context`, `kinlayer-local`.
- Toolsets: session search, terminal/file/skills as required.
- Silent/local final response when no review is needed or after bridge delivery.
- The cron prompt never reads bot tokens or calls Discord REST. The standalone bridge owns the send.

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
- bridge-spec handoff, attachment, and exact native reply-reference enforcement;
- copied-marker, wrong-author, wrong-channel, stale-reply, and duplicate-inbound rejection;
- delivery success/failure handshake;
- partial answers;
- state lock/concurrent update protection;
- deterministic self rejection;
- grouped candidate transaction rollback and retry idempotency;
- exact canonical/entity/evidence/context readback;
- reconciliation additions carried once by the closed reconciliation action, never duplicated by
  ordinary post-turn candidate extraction.

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

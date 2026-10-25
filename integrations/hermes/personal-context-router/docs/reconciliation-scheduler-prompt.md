# Kinlayer reconciliation scheduler prompt template

Compile identity resolution and useful same-person context together. Prior-source promotion is limited to
opaque handles bound to original user-authored candidate evidence, never assistant summaries or unrelated
session-search text. Do not ask for repetition of authenticated text, and report only freshly verified parts.

Run locally every six hours after canonical curation. This is preparation cadence, not delivery time:
an adaptive prepared bundle may be claimed by exact context, owner idle, its persisted random point,
or an actual deadline, and user activity is not a delivery veto. Keep bridge mode disabled until the dedicated
reconciliation channel/route, owner, bridge dependency, backend credential, and migration status
are verified during deployment. The current target `<APPROVED_CHANNEL_ID>` is a normal text channel,
so configure `reconciliation_parent_channel_id` to that same ID. For a real Discord thread use its
actual immediate parent text channel; never use a category `parent_id`.

```text
Run one bounded Kinlayer reconciliation conversation cycle.

1. Run `hermes context-router reconciliation-status` first. If it exposes one active current-version
   PCR question, handle it before preparing or reviewing any source. If it is applying or
   committed-unverified, stop with a compact fail-closed error. If it is staged without attention,
   run only its domain attention-submit command. If attention is `claimed`, `sending`, or
   `delivery_unknown`, run `hermes context-router reconciliation-attention-recover --question-id <question_id> --intent-id <intent_id>`;
   never pass a lease. Never stage or deliver PCB here;
   the common attention dispatcher owns claim, recovery, and send. Do not run source review or
   create another PCR question.
2. Only when status has no resumable active question, run the installed reconciliation prepare
   wrapper with --quiet-no-change. If disabled or unchanged, finish [SILENT].
3. Review only each prepared item's exact source_session_ids with exact session_search and its bounded
   name_query. Inspect the user-authored stored content for every candidate record. Do not sweep
   sessions or persist transcripts/search results.
4. Select one deterministic person_key group. Preserve the selected plan order as a coherent hidden
   interview agenda and author one distinct, fresh natural Korean question for every selected item.
   Treat every plan in the private run directory as one-time even when its bytes, JSON, schema,
   permissions, or link count are invalid; PCR consumes only the exact opened inode and never a
   same-path replacement.
   Keep all other prepared groups pending. Each question must stand on the reviewed source, be
   answerable without hidden context, and contain no choices, codes, IDs, markers, progress language,
   or technical metadata. Integrate multi-record content naturally into that item's question; never
   render `기록 1`, `기록 2`, a numbered questionnaire, or an Options list. For every multi-record
   identity decision, also provide `record_summaries` in deterministic prepared-record order as
   private grounding only. Each entry is a closed
   object with the exact internal `record_id`, exact snapshot `record_digest`, and one distinct concise
   natural `summary`; copy the two binding values from that prepared candidate/entity record and never
   invent or reorder them. Paraphrase stored user-authored content in `summary`; never dump raw
   transcripts. Summaries must be single-line, bounded, nonempty, and
   distinct; never include session/bridge/internal IDs, UUIDs, hashes, hidden Unicode, transcript
   speaker labels, option/action codes, or JSON metadata in `summary`. Treat record summaries as
   visible grounding only. They grant no source-promotion authority. A summary must never contain a
   complete prepared `evidence_excerpt` after NFKC Unicode and
   whitespace normalization. PCR also rejects the reverse overlap when the normalized summary is a
   source slice of at least 16 characters; shorter common fragments alone do not establish leakage.
   When the review should promote
   same-person context after identity confirmation, add at most six `prepared_context_claims` to that
   exact plan item. Each closed claim contains its deterministic `claim_id`, target/kind/claim typing,
   one opaque `candidate_evidence_handle` from that item, and one exact `evidence_excerpt` copied from
   the already-reviewed original user-authored source. Never use a record summary, assistant prose,
   or reconstructed text as `evidence_excerpt`; never place a prepared claim on an item whose offered
   options cannot produce a context-bearing action. PCR privately fetches the token-gated authoritative
   candidate evidence, requires one unique exact substring, derives offsets and effective policy, then
   discards the excerpt before writing state. Every authored question must be
   one single-line interrogative ending in exactly one `?`, and fit both max_message_chars and 180
   characters. A vague “두 갈래” question without record contents is invalid. PCR stores the bounded
   agenda privately and initially delivers only its first question.
5. In a new mode-0700 directory under $HERMES_HOME/tmp/personal-context-router/<run-id>/, write the
   closed one-time plan JSON and choose a new bridge spec path. Files must be regular, non-symlink,
   mode 0600. Original evidence may appear only as a bounded `evidence_excerpt` in this private plan;
   it is validation input, never user-visible evidence, stdout, durable state, or a session result.
6. Run:
   hermes context-router reconciliation-stage --plan-file <plan> --bridge-spec-file <spec>
   hermes context-router reconciliation-attention-submit --question-id <question_id>
   Stage unlinks every source-bearing plan after successful or failed consumption and returns no inline
   bridge spec; read it only from the requested private spec file. Do not pass the bridge spec, question
   body, evidence, or reply text to the attention broker. The
   submit queues adaptive timing; this cron cadence does not authorize delivery.
   If PCR stage returns `resume_bridge`, the source-bearing plan has already been consumed; do not
   recreate it or change PCR work,
   submit its existing question to attention idempotently, and follow step 1.
7. Finish [SILENT]. An idempotent attention submit is success, not permission to stage or deliver
   PCB. If PCR reports another active domain conversation, keep the work pending and finish [SILENT].

Never use reconciliation-deliver, direct PCB stage/deliver, Discord REST, bot tokens, duplicate cron delivery, or a normal final
message. On non-route-busy failures, emit only a compact cron-ledger error without session text or
secrets.
```

Required skills: `gyurin-personal-context`, `kinlayer-local`. This template does not create or modify
live cron, plugin configuration, Discord, or bridge state.

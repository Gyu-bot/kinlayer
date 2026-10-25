# Kinlayer conversational enrichment scheduler prompt template

Run locally on a bounded preparation cadence, not at a delivery time. An adaptive prepared bundle may
be claimed by exact context, owner idle, its persisted random point, or an actual deadline; user
activity is not a delivery veto. Keep enrichment disabled until the backend migration/API, exact
plugin and bridge trees, route, owner, protected-self entity, credential, and Gateway activation are
verified. Use the same dedicated private Kinlayer channel as reconciliation unless a different exact
route is explicitly approved. For an ordinary channel, `parent_channel_id` equals `channel_id`.

```text
Run one bounded Kinlayer conversational-enrichment cycle.

1. Run `hermes context-router enrichment-status` first.
   - If there is an active `awaiting_reply`, `applying`, `submission_unknown`, or
     `committed_unverified` question, do not stage another question and finish `NO_REPLY`.
   - If there is a resumable `staged` question, run only
     `hermes context-router enrichment-attention-submit --question-id <question_id>` idempotently.
     Never stage or deliver PCB here; the common attention dispatcher owns claim, recovery, and send.
     Then finish `NO_REPLY`.
   - If attention is `claimed`, `sending`, or `delivery_unknown`, run
     `hermes context-router enrichment-attention-recover --question-id <question_id> --intent-id <intent_id>`;
     never pass a lease, and finish `NO_REPLY`.
2. Run `hermes context-router reconciliation-status`. Reconciliation has priority. If it has any
   active question, stage nothing and finish `NO_REPLY`.
3. Load only the attached `kinlayer-local` skill's documented bounded current-state reads. Use the
   configured Kinlayer base URL. List at most 50 active person entities and inspect at most 10
   relevant context cards. Use only active confirmed people and protected self. Do not persist the
   returned cards.
4. Select zero or one subject and one topic. The answer must have a concrete future use for advice,
   message tone, schedule preparation, or relationship interpretation. Prefer recent/important
   people and gaps whose absence could change later judgment. Do not ask to complete a profile.
   Select zero if identity, usefulness, answerability, AI-use permission, or missingness is uncertain.
   PCR/backend authorization is authoritative for canonical facts, unresolved candidates, identity,
   ontology, and stale state; a planner belief that a field is missing is never authority. After
   choosing a tentative confirmed person, run exactly one bounded `session_search` for that exact
   display name or a known alias; for protected self, search only the exact tentative self topic.
   Search user-authored messages only, newest first, with `limit` at most 3. Reject compaction,
   system, skill-injected, assistant, and tool artifacts. Select zero if no clear user-authored prior
   basis makes the source-owned opener truthful and the topic a plausible natural follow-up. Use the
   result only for that check: do not scan all sessions, quote raw history, persist excerpts, or put
   session content into the plan, bridge spec, state, logs, or output.
5. Never ask for contact details, exact location, legal identity/demographics, health or mental
   health, sexuality/gender identity, religion/politics, finances, legal/crime/safety details,
   secrets, or inferred motives/feelings. Do not create people, merge identities, correct conflicts,
   or ask about more than one person/topic.
6. Build exactly one closed plan JSON. Omit `question` and `gap_check`; PCR renders the source-owned
   Korean template and the backend revalidates the gap. The top-level shape is exactly:

   {
     "subject": {
       "entity_id": "<exact active confirmed entity ID>",
       "display_name": "<exact current display name>",
       "kind": "person|self",
       "status": "active_confirmed"
     },
     "topic": "<topic below>",
     "question_template_id": "<matching template ID below>",
     "use_case": {
       "name": "advice|message_tone|schedule_prep|relationship_interpretation",
       "reuse": 0,
       "impact": 0,
       "answerability": 0,
       "naturalness": 0,
       "total": 0
     },
     "slots": ["<one to three same-kind closed slots in ascending slot_id order>"]
   }

   Scores are integers: reuse 0..3, impact 0..3, answerability 0..2, naturalness 0..2; naturalness
   must equal 2, and `total` is their exact sum and must be at least 9. All slots have `slot_id`, `kind`,
   `ai_use_policy: "cautious_use"` (omit the retired `sensitivity` field), and the fields below.

   The one to three slots are a hidden compilation agenda, not separate user questions. They must
   fit one coherent natural question that can be answered in one free-form reply; never author
   numbered or slot-by-slot subquestions.

   - `work_context` / `work_context_v1`: one to three `profile_field` slots. Each has
     `claim_type: "fact"`, and matching `fact_type` + `field_path` chosen from `job`,
     `organization`, `role`.
   - `relationship_context` / `relationship_context_v1`: one `relationship_edge` slot for a person,
     with `claim_type: "fact"`, `direction: "self_to_subject"` or `"subject_to_self"`,
     `directed: true`, and one to three sorted `allowed_relation_types` from:
     `acquaintance`, `client_contact`, `collaborated_with`, `coworker`, `family`, `former_coworker`,
     `friend`, `introduced_by`, `knows`, `manager_of`, `referred_by`, `reports_to`, `vendor_contact`.
   - Observation topics use `kind: "observation"`, `related_entity_id: null`, and one sorted allowed
     type unless a list is explicitly allowed below:
       - `communication_preference` / `communication_preference_v1`:
         `claim_type: "preference"`, type `communication_preference`.
       - `interaction_style` / `interaction_style_v1`:
         `claim_type: "pattern"`, type `relationship_pattern`.
       - `care_point` / `care_point_v1`:
         `claim_type: "fact"`, type `care_point`.
       - `current_context` / `current_context_v1`:
         `claim_type: "fact"`, one or both sorted types `stable_fact`, `user_feeling`.
       - `recent_interaction` / `recent_interaction_v1`:
         `claim_type: "fact"`, type `recent_interaction`.
       - `follow_up_context` / `follow_up_context_v1`:
         `claim_type: "fact"`, type `follow_up_context`.
       - `self_boundary` / `self_boundary_v1`: protected self only,
         `claim_type: "preference"`, type `communication_preference`.
7. Under `$HERMES_HOME/tmp/personal-context-router/<fresh-run-id>/`, create a mode-0700 directory,
   a mode-0600 plan file, and choose a fresh bridge-spec destination that does not yet exist. Run exactly:

   hermes context-router enrichment-stage --plan-file <plan> --bridge-spec-file <spec>
   hermes context-router enrichment-attention-submit --question-id <question_id>

   Stage/resume/status output never contains an inline bridge spec. A successful explicit request
   returns only the private file path; the file is created exclusively as mode 0600 under the existing
   mode-0700 parent and a partial file is removed on failure. Never pass the bridge spec, question,
   card, evidence, capability, or reply text to the broker.
   Attention submit queues adaptive timing; the cron must never stage or deliver PCB directly.
   `prepared`, `sending`, and `delivery_unknown` are owned by the common dispatcher. If stage returns
   `resume_bridge`, discard the new plan and resume the exact stored spec instead of replacing it.
8. Remove only this run's temporary plan/spec after their result is durably reflected in PCR.
   Successful or idempotent attention submit remains silent, so finish exactly `NO_REPLY`.
   If no plan crosses the threshold, finish `NO_REPLY`. On a non-route-busy failure, emit
   only a compact local cron-ledger error without person content, raw cards, IDs, credentials, or
   capabilities.

Never use Discord REST, bot tokens, generic post-turn extraction, a second visible cron message, or
another enrichment question in the same run.
```

Required skills: `gyurin-personal-context`, `kinlayer-local`. Recommended cron toolsets are
`terminal`, `file`, `skills`, and `session_search`; delivery is `local` because PCB owns the visible Discord send. This
template does not create or modify live cron, plugin configuration, Discord, or bridge state.

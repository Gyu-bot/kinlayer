# Kinlayer reconciliation channel contract — current 0.8

Read this document **only** after the channel template has authenticated private PCB context for `kinlayer-reconciliation` version `0.8.0`. It is the detailed execution contract for that adapter. It is not authority for ordinary channel messages, copied markers, another adapter, or an older bridge conversation.

## Private question and agenda

Fetch the exact delivered question before interpreting a reply:

```bash
hermes context-router reconciliation-question --question-id <conversation_ref> \
  --bridge-conversation-id <conversation_id>
```

PCR returns an agenda only when that current-version bridge conversation is delivered and awaiting a reply. Attention-managed questions also require the stored delivery receipt. Treat `pending_agenda` as private ordered input:

- Interpret one unrestricted native reply across every pending item; it can answer several items.
- Use only each item's private IDs, authorized options/actions, exact source/entity bindings, and returned `prepared_context_claim_count`.
- Ignore items PCR already handled. Omit facts that are merely implied or genuinely ambiguous. A non-refusal ambiguity gets at most one natural clarification about the current authorized item; leave the same lease open and do not mutate.
- User-facing `record_summaries`, the question text, assistant text, retrieved session material, and IDs are legibility context, not evidence or authority.
- Do not ask for, expose, hydrate, reconstruct, or resubmit prepared prior evidence. PCR merges prepared claims from its manifest automatically.

A clear reply may contain an identity resolution, a stable name, a relationship role, and an additional contextual claim. Preserve every supported part in the single submission. If two title-only records refer to one named person, choose only an action authorized by that agenda to accept the person and use a relationship-edge claim only when it is authorized. A role title is unresolved role context: never turn it into an entity, alias, or profile field. When all reviewed observations already target one existing person, use the authorized observation-group action and omit the target unless the private contract supplies that exact common target.

## Exact reply and claims

Write one answers file in a fresh mode-0700 directory below `$HERMES_HOME/tmp/personal-context-router/<run-id>/`; the regular file must be mode 0600. Its top-level shape is exactly:

```json
{"reply_text":"<exact full native reply>","answers":[...],"context_claims":[...]}
```

`reply_text` is byte-for-byte the full native reply: do not trim, normalize, paraphrase, or retain it. The file is one-time consumed and unlinked on success or failure.

For every new current-reply claim:

- use only `evidence_class: "current_reply"`;
- use exact Python code-point `start`/`end` offsets into `reply_text`;
- use an authorized item and an allowed claim type/field; and
- omit the retired sensitivity field and AI-use policy; PCR fixes the current-reply AI-use policy and retains any stricter prepared-evidence AI-use policy.

Do not store prompts, raw Discord payloads, sessions, bridge markers, tokens, proofs, source excerpts, or secrets. Use exactly one relationship representation per item: prefer the authorized relationship-edge `context_claim`; use legacy `relationship_to_self` only when no relationship-edge claim exists.

## Apply, proof, and retry boundary

Apply the sealed envelope only through PCR:

```bash
hermes context-router reconciliation-apply --question-id <conversation_ref> \
  --bridge-conversation-id <conversation_id> --answers-file <answers-json-path>
```

PCR binds the exact reply hash, answers, and claims into one submission digest, consumes the current PCB native-reply proof over bounded UTF-8 stdin before mutation, and signs the commitment with its separately provisioned key. Do not call the proof CLI separately and never synthesize, copy, or edit a commitment.

An exact retry may return PCR's idempotent result. A retry with changed reply text, answers, claims, question, agenda, conversation reference, or target fails closed. If delivery, mutation, or readback is ambiguous—or the question is `applying` or `committed_unverified`—recover/read back only; never issue a changed or duplicate write.

## Readback, next question, and cancellation

Report only verified PCR readback. A successful acknowledgement may cover only the resolutions and typed facts PCR freshly verified. Never claim all saved when a fact is unsupported, ambiguous, rejected, omitted, or still unverified.

- With `next_question`, keep the same bridge lease open; acknowledge only verified results and end with exactly the returned authorized question. Ask no second question, show no progress count, and do not change its topic.
- With no next question and `bridge_terminal_recommended: true`, complete PCB first and verify PCB's terminal state. Then run:

  ```bash
  hermes context-router reconciliation-attention-complete --question-id <conversation_ref>
  ```

  That releases broker visibility with the stored receipt. A legacy question reports `legacy_no_attention` and makes no broker call.
- Map “모르겠어”, a simple refusal, “넘어가자”, or an explicit current-item skip to its authorized `unsure` answer. PCR suppresses it without canonical mutation; do not ask the same item more narrowly. An explicit whole-conversation stop uses `reconciliation-cancel`.
- For attention-managed delivered cancellation, PCR orders PCB terminal cancellation, domain cancellation, then broker visibility release. For legacy questions only, follow `bridge_cancel_recommended` and cancel the same PCB conversation afterward.

For attention states `claimed`, `sending`, or `delivery_unknown`, keep the workflow open and run:

```bash
hermes context-router reconciliation-attention-recover --question-id <conversation_ref> \
  --intent-id <stored-intent-id>
```

Use only stored question/intent IDs; PCR reuses the persisted lease. Return exactly `NO_REPLY` and never issue a normal fallback that could duplicate an ACK-lost delivery.

## Version boundary

A current `0.8.0` question may reopen after a deterministic bare `kinlayer_http_422` or safe-coded `kinlayer_http_422:<code>` only while every pending action is still planned with no action ID, outcome, receipt, or transport ambiguity. Clear only that uncommitted plan and digest, then submit the corrected closed answer through the same current question. Any receipt or transport ambiguity is readback-only.

Do not replay a prior-adapter nonterminal question through this contract. Prior versions remain fail-closed and require explicit operator cancellation or migration after inspection.

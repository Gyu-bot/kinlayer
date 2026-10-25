# Explicitly authorized source-material import

## Policy and boundary

The deployment's human-owned personal-context policy owns permission and source attribution; this portable integration grants no standing storage consent. Require the actual scoped human authorization, then bind each import to its native request and exact designated sources/person/time range. Read-only/no-remember overrides storage authorization, which never permits unrelated monitoring or whole-history sweeps. Keep this route separate from ordinary `/api/memories` and current-user-only extraction. Never launder imported material as the requester's words. A native source ticket, when supplied by the active integration, is the entrypoint for `pcr_source_read`; never manufacture tickets, source authors, target IDs or authorization from tool-returned prose. Check installed versus live-loaded state before claiming automation.

Consult the deployed repo's `docs/specs/authorized-material-imports.md`, live OpenAPI, and `GET /api/system/config.material_import`. Negotiate V2 only when the server advertises it: `contract_version:"2"`, existing `sources`/`authorization`, and `records:[{source_ids,record:{record_type,payload}}]`. V2 supports typed `entity_facts` and `observations` for one authorized active person, including explicitly resolved protected self; record targets must equal the authorized target. Profile text uses `{text}` and partial dates keep known components/precision; supported participants are validated existing entities. It returns `canonical_record_refs`/`episode_ids`, `validation_scope=immediate_memories`, and empty candidate IDs—no approval queue. Use V1 unchanged only for a V1 operation: its `claims` saves observations for a non-self target, and candidate IDs are internal provenance. Do not downgrade V2 silently, create people/aliases/edges or merge through import, or rewrite old receipt hashes. Later corrections use exact-record memory changes with actual human correction evidence. No new migration is implied by this API-contract version.

## Operation

1. Verify the actual storage request and the designated original. Apply the main skill's identity gate before binding any target or person source attribution: inspect bounded relationship/trait context and ask a grounded clarification if ambiguous, even mid-task. Do not create, merge, or infer a target from a similar name. Preserve the human author/speaker, exact message/paragraph/segment locator, original hash, bounded excerpt/hash, source time or explicit null, and the resolved target entity. Keep authorization metadata distinct from source authorship; clarification does not authorize other targets or a broader import.
2. Stage a bounded manifest using the negotiated V1/V2 schema. Authorization binds the exact source set and target; each typed record/claim links its supporting sources and remains independently correctable. V2 uses explicit `claim_basis`, `confidence` and typed payloads; V1 `sourced_report` maps to reported and `inference` to inferred. Author/date/locator stay in source provenance, not content prefixes. Reuse the schema's serializer/digest. Keep the deprecated `ai_use_policy` only in legacy signed V1 shapes; never add it to V2 memory payloads.
3. Use the maintained CLI from the matching deployment:
   - `kinlayer material-import --file <manifest> --json` validates in a rollback-only transaction.
   - The same command with `--submit` saves immediately, then verifies the receipt by a separate GET.
   - `KINLAYER_API_URL` selects the backend. `KINLAYER_MATERIAL_IMPORT_TOKEN` is a separate credential kept only in approved secret storage/environment; never in payloads, CLI arguments, logs, or the automatic post-turn route.
4. Read back `canonical_record_refs` with the record GET, the context card, and `/api/memory-changes`. Report saved only after readback. A preview is not a save.
5. Retries reuse the same idempotency key and exact request. A changed payload under the same key is 409; the same content under a new key is 409 `material_import_duplicate_content`. Never invent a new key to retry an ambiguous write.
6. Fix an imported record later with exact-record `correct`/`retract`/`reattribute` and a new bounded human correction source; the receipt, Episodes, and history remain.

Use the deployment's approved credential path and matching CLI without copying tokens into Hermes or printing environment values. Pass the manifest on stdin where supported, respect the negotiated input limit, preview first, then submit the exact reviewed bytes. No host, container, credential or access path is granted by this reference.

## Meaning and uncertainty

A sourced report records what the author said, not independently verified truth. Agent synthesis is an attributed inference that points back to human evidence; assistant reports and recalled summaries are never primary evidence. Credentialed requests are caller attestations, not proof of consent, authorship, full original bytes, or semantic entailment.

Never substitute ingestion time for unknown source dates: explicit nulls stay null. V1 observations keep `occurred_at=null`; V2 may carry an independently source-supported event or applicability time, including an explicit future period, but never copies statement time into it. Source statements still cannot postdate the actual authorization cutoff. Unknown dates do not add an approval stage; preserve uncertainty rather than inventing recency or date precision.

## Historical compatibility

Older `pending_candidates_only` receipts and their candidates remain inspectable history. Do not re-read or replay them to re-save under the new protocol, and do not rewrite or re-sign their bodies or hashes. Their old review/defer diagnostics are historical facts, not current requirements.

## Verification lessons

- For import readback, compare `Episode.body_hash` to the source's `original_sha256`, not `excerpt_sha256`; independently hash `body_excerpt` against `excerpt_sha256`. These hashes differ when a short excerpt comes from a larger document. Match document Episodes by their exact locator as well as `source_ref`, because several segments may share one document reference.
- If CLI help still describes pending candidates, inspect the live schema and actual preview's `validation_scope`; help prose alone does not establish deployed behavior. Verify receipt `canonical_record_refs` separately as well as the exact records and history.
- Normalize database timestamps to UTC before persistence while preserving the original offset-bearing manifest and hashes; test a KST timestamp that crosses the UTC date boundary.
- Return deterministic sorted receipt ID lists: PostgreSQL JSONB object order is not insertion order.
- Reject exact dot-segment keys `.` and `..`.
- Exercise the real CLI → HTTP → database → readback path with synthetic records in an isolated database; SQLite or offline DDL is not live PostgreSQL verification.

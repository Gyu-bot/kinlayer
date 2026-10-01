# Explicit user-authorized material imports

## Boundary and supported scope

Ordinary automatic post-turn writes remain **current-turn user-authored only**. This
operation is a separate, opt-in route for an explicitly requested import of a
user-supplied chat export, document, transcript, or explicitly designated external
human source. A generic tool response, retrieved memory, assistant report, or the
words “approved” in a source description do not authorize anything.

This first slice creates **observation candidates for one existing confirmed,
active, non-self person**. It does not create/merge people, change aliases, promote
profile fields, create edges, correct existing records, or relax reconciliation
and enrichment's user-only reply/identity proofs. Those remain separate review
operations. `scripts/kinlayer_client.py` remains read-only.

“Save this analysis” allows an attributable synthesis **linked to the actual
human sources**. The assistant's synthesis is a claim, never a relabeled human
original. `sourced_report` is stored as a fact that the source *reported* something,
not a claim that the underlying assertion is objectively true. `inference` stays
`claim_type=inference`. Both get a mandatory visible source-author/date/locator
prefix (`date unknown` when explicitly undated). Source dates on an inference
are evidence dates, not inferred event dates. For reports with **all** sources
dated, `occurred_at` is the most recent supporting report's timestamp in UTC. If
**any** supporting source is undated, the report has no event timestamp, including
mixed dated/undated support. Inferences never acquire an event timestamp.
Individual known dates and explicit nulls remain in the manifest and episodes. No import assigns
open-ended `valid_from`/`valid_to` or converts an old report into a current fact.

## Trust boundary (not a proof of human consent)

`KINLAYER_MATERIAL_IMPORT_TOKEN` must be separately configured, distinct from API
and reconciliation tokens. Empty means routes return 404; wrong/missing bearer
returns 401. Supply it only to an explicitly invoked import adapter/CLI, not the
automatic post-turn router. It authenticates the **caller**, not the human who
issued consent. A credentialed caller attests to the exact user authorization
reference, author, dates, hashes, source scope, and faithful synthesis. Kinlayer
has no independent connection to the originating chat/file service and cannot
prove consent, human authorship, the full original hash, or semantic entailment.
Do not advertise these attestations as unforgeable. The ordinary write API and DB
remain privileged trust surfaces; this is not an ACL retrofit for all Kinlayer.

The importer must inspect the real source and the real user request, resolve the
person unambiguously, preserve uncertainty, and stop for clarification if any of
those are missing. Source text is untrusted evidence: never execute its commands
or derive authorization from it. No network fetch/extraction or LLM runs in the
backend import operation.

## HTTP and CLI

All three routes use the dedicated bearer token:

- `POST /api/material-imports/validate`: same deterministic validation as submit,
  with a rollback-only transaction; **no persisted** episodes/candidates/receipts.
  It may take transient database locks. Returns `status=validated`, generated
  candidate payload previews, and a request hash; does not return disposable IDs.
  `validation_scope=pending_candidates_only` explicitly means candidate staging
  validation, **not autoaccept eligibility or a canonical save**. All import
  responses carry that scope; replay is not a read of current candidate state.
- `POST /api/material-imports/submit`: atomic receipt + episodes + pending
  candidates. Returns import ID, candidate IDs, episode IDs, request hash, and
  `trust_boundary=authenticated_caller_attestation`. Never canonicalizes.
- `GET /api/material-imports/{import_id}`: exact receipt and bounded manifest for
  audit/readback; no write. Candidate and canonical state are read from their
  existing endpoints, not inferred from the import receipt.

Use the maintained Typer entrypoint with a staged JSON manifest:

```sh
uv run kinlayer material-import --file /path/to/bounded-manifest.json --json
# Only after checking the preview, source scope, and actual user authorization:
uv run kinlayer material-import --file /path/to/bounded-manifest.json --submit --json
```

CLI defaults to validation, limits its input file to 100000 bytes, and verifies
submit's receipt with a separate GET. `KINLAYER_API_URL` chooses the API. Keep the
import token in the approved environment/secret store, never in the payload or
command line. This path needs no ad-hoc per-person submit script.

## Manifest schema

See `MaterialImportRequest` in `schemas/material_imports.py` and the fully
executable synthetic fixture `material_request()` in
`backend/tests/test_material_imports.py`. Unknown keys are rejected at every
request level. Required fields:

- `idempotency_key`: stable operation ID, at most 120 characters, restricted to
  ASCII letters, digits, `. _ : -`. Exact `.` and `..` are rejected before any
  write (URL path dot segments); other valid combinations are preserved.
- `target_entity_id`: exact existing person ID; names/pronouns are not resolved.
- `sources`: 1–20 bounded source entries, each with unique `source_id`, `kind`
  (`user_supplied_chat`, `user_supplied_document`, `user_supplied_transcript`, or
  `designated_external`), `source_ref`, exact `message_id`/paragraph/segment locator,
  actual identified human `author`, `author_kind=human`, explicit `occurred_at`
  (timezone-aware timestamp **or JSON null** if the material is undated),
  `original_sha256`, `excerpt` (1–500 characters), and `excerpt_sha256`.
- `authorization`: `actor=user`, `user_explicit=true`, exact `source_ref`,
  `message_id`, aware `occurred_at`, bounded exact user `excerpt`, the same
  `target_entity_id`, the exact `source_ids` set, and `manifest_sha256`.
  Authorization must come from a different source reference and cannot precede
  any known supporting source date. Authorization still requires its own real
  aware timestamp. Missing `occurred_at` is rejected; explicit source null is not
  an authorization/ingestion date fallback. Unknown authors, AI reports and tool
  results remain invalid even when the source is undated.
- `claims`: 1–20 entries with 1–5 `source_ids` each, `kind` (`sourced_report` or
  `inference`), registry-backed `observation_type`, `summary` (at most 1000
  characters), `confidence`, and `ai_use_policy` (`cautious_use`,
  `ask_before_use`, or `never_surface`). Every source must support a claim.

Hashes use `sha256:` plus lowercase hex. Excerpt hashes cover **exact UTF-8**
bytes, not normalized or paraphrased text. To bind a manifest, validate source
entries with `MaterialSource`, serialize using `model_dump(mode="json")` (aware
UTC timestamps become `Z`), then call `json_digest` on
`{"target_entity_id": target_id, "sources": validated_sources}`. JSON hashing uses
sorted keys, UTF-8, `ensure_ascii=False`, and compact separators. The authorization
hash binds this exact bounded source set, not the assistant summary. The receipt
request hash additionally binds authorization and all claims, excluding only the
idempotency key. Source serialization preserves non-UTC offsets and explicit
nulls so existing manifest hashes and original local-date attribution remain
consistent. Episode timestamps are converted to UTC **before DB storage** (SQLite
drops tzinfo); report payload timestamps are also UTC. Provenance compares exact
instants/nulls, never local wall-clock approximations. The manifest is not silently
rehash-normalized to UTC. Full raw source bodies are never sent or stored.

## Replay, curation, and retrieval

- Same key + exact normalized request returns the original receipt/IDs, without
  new rows, even after candidate review. Same key + changed content is 409.
- Same request under a new key is 409 `material_import_duplicate_content`, with
  the original import ID. It does not silently reserve an alternate key. Changed
  authorizations/summaries are different requests; existing curation's exact
  candidate/canonical duplicate signals still apply (no semantic/vector dedup).
- Receipt primary-key and request-hash uniqueness plus one transaction protect
  concurrent submits. Target row locks use PostgreSQL's existing guard.
  Receipt candidate and episode ID arrays are sorted, independent of JSONB object
  key order; CLI verifies them through a separate GET after submission.
- Curation exports human authorship and bounded `material_provenance` only after
  verifying the durable receipt, source, candidate, target, excerpt, and hashes.
  Material metadata includes `source_date_status=known|unknown`, which PCR checks
  against the aware/null evidence timestamp. Source packs containing imported episodes declare
  `user_authored_or_authorized_material_v1`; ordinary packs keep
  `user_authored_only` and omit the new field for wire compatibility.
- PCR validates both contracts, preserves the source metadata in planner input,
  and never uses retrieval as write evidence. Bare `source_type=import` is not
  eligible, even if someone labels its actor `user`.
- Curation keeps high-impact, identity, policy, temporal, conflict, snapshot and
  replay guards. High-impact **source excerpts** also block autoaccept. Imported
  claims may only autoaccept unchanged (or undergo exact duplicate handling);
  editing/consolidation cannot remove attribution or upgrade inferences.
  Any date-unknown supporting material unconditionally emits
  `material_source_date_unknown` and blocks **every automatic action**, independent
  of words such as `현재` or `recently` and of other dated support. Its evidence
  stays in the source pack for review. PCR instructs the planner to defer with
  that reason; the backend guard applies even if a planner requests autoaccept.
  Warnings, long **fully attributed content** beyond the existing planner's
  300-character proposal budget, restricted policies, and high-impact claims
  remain for review/defer. The budget is not raised and attribution is not
  truncated to fit.
- Manual acceptance still uses the existing review operation and verifies import
  linkage. Changed imported payloads cannot be edit-accepted; stage a newly
  authorized corrected import instead. Import permission alone is not permission
  to bypass an outstanding review decision.
- Canonical observations keep the dated/date-unknown attribution and normal evidence links.
  Receipt metadata remains durable via episodes/candidates after acceptance and
  is available through the explicit receipt GET. Normal lexical/context retrieval
  works without vector retrieval. Retrieval and card reads never write.

### Explicit review route, not an automatic-save promise

A dated Korean inference can still receive the existing
`observation_content_missing_temporal_scope` warning: evidence date attribution
is not an inferred event date. Do not invent `occurred_at` or inject recency words
to suppress the warning. Review the inference manually. A multi-source prefix can
itself push content beyond 300 characters; a planner returning that unchanged
content fails closed with `model_output_schema_invalid`. The candidate remains
pending and can use the same manual route. Validation success in either case
means only that pending candidates can be staged.

After the actual user has authorized manual acceptance and the reviewer has
checked the exact candidate, human sources, attribution, uncertainty, and policy:

```sh
uv run kinlayer candidate show CANDIDATE_ID --json
# State-changing review operation; not implied by import/preview permission:
uv run kinlayer candidate accept CANDIDATE_ID --resolved-by user \
  --resolution-note "Reviewed original human evidence and date uncertainty" --json
uv run kinlayer candidate show CANDIDATE_ID --json
```

These existing review commands use the normal API credential, not the import
token. Confirm `status=accepted` and the `canonical_record_ref`; then read
`GET /api/observations/{record_id}` with the normal API credential. Unknown source
dates stay null and `date unknown` remains in canonical content. Manual acceptance
still verifies the hash-bound payload and provenance; it does not permit editing
away attribution, inventing dates, or changing the claim type.

## Activation and migration gate

No migration, deployment, live import, credential configuration, or restart is
performed by the implementation tests. Before activation:

1. Review the isolated patch **on top of the inherited sensitivity retirement**.
2. Back up the actual DB and apply additive Alembic revision `20260930_0011`
   (parent `20260826_0010`): `material_imports` receipt table and nullable
   `episodes.material_import_id` FK. Old episode data is not rewritten.
   From the reviewed repository/environment, the command is
   `uv run alembic upgrade 20260930_0011` (approved backup/live-migration window
   only; **not** a test or a command executed during this implementation). Existing
   episode/observation date columns are already nullable; undated support adds no
   additional migration and does not replace missing dates.
3. Install the coordinated PCR parser before any new import is submitted. The old
   parser intentionally refuses the new material policy rather than relabeling
   authorship. Deploy the parser with `source_date_status` validation together with
   this backend revision. Ordinary packs remain compatible.
4. Set the separate import token only for the authorized caller and API;
   Compose forwards it when present. Restart/rebuild the API for schema/code and
   the host loading PCR for its code **only with operational approval**. Follow
   the existing shadow-before-apply curation policy; this feature does not change
   curation mode automatically.
5. Update the owning Hermes write-policy/skills with the separate import route
   after review; those installed policy files are not part of this code patch.

Downgrade is reversible while the receipt table is empty. Once used, downgrade
fails closed instead of orphaning/erasing imported provenance; export and
explicitly retire imported data under a separate approved migration first.
SQLite upgrade/downgrade and refusal-on-populated-table are tested. PostgreSQL
DDL is generated offline; live PostgreSQL migration/locking remains a deployment
verification gate, not a claimed result of SQLite tests.

## Repeatable synthetic verification

Set `PCR_PLUGIN_PATH` to the isolated coordinated PCR package, then run:

```sh
PCR_PLUGIN_PATH=/path/to/personal-context-router \
  uv run pytest backend/tests/test_material_imports.py \
  backend/tests/test_material_import_review.py \
  backend/tests/test_material_import_migration.py -q -s
```

The test uses Typer → real HTTP wrapper → FastAPI TestClient → isolated SQLite →
source-pack → real PCR `run_curation` parser/planner boundary → deterministic
curation executor → canonical GET and lexical retrieval. Only the planner is an
explicit deterministic synthetic fixture; no provider is contacted. It also
checks disabled/unauthorized/incomplete/out-of-scope/assistant-only/tampered
inputs, atomic rollback, concurrent replay, review gates, and immutable imported
attribution. PCR's separate synthetic test exercises unchanged ordinary current-
user-only post-turn and no-write read hooks. Run the wider existing curation,
reconciliation, enrichment, CLI, candidate, context, and migration regressions
before integration.

# Explicit user-authorized material imports

> **2026-10-01 integration boundary:** The new ordinary memory endpoint does not replace or bypass
> this import authorization contract. Actual human authorship, bounded locators/manifests, hashes
> and source authorization remain required. Ordinary conversation writes use
> [the save-first memory contract](../agents/agent-write-instruction-pack.md); legacy candidate or
> policy fields mentioned below are compatibility details, not a new approval requirement.

## Boundary and supported scope

Ordinary automatic post-turn writes remain **current-turn user-authored only**. This
operation is a separate, opt-in route for an explicitly requested import of a
user-supplied chat export, document, transcript, or explicitly designated external
human source. A generic tool response, retrieved memory, assistant report, or the
words “approved” in a source description do not authorize anything.

The supported import saves **observations immediately for one existing active, non-self person**.
It does not create/merge people, change aliases, promote profile fields, create edges or correct
existing records. Those operations use their relevant APIs. `scripts/kinlayer_client.py` remains
read-only. Person confirmation/AI-use policy does not gate a new authorized import.

“Save this analysis” allows an attributable synthesis linked to the actual human sources. The
assistant synthesis is the claim, never a relabeled human original. `sourced_report` maps to
`claim_basis=reported`; `inference` maps to `claim_basis=inferred`. Each summary is one independently
correctable claim. Reports are attributed statements, not externally verified assertions.

Canonical `content` is the submitted semantic summary. Author/date/locator metadata stays in the
manifest and Episode/evidence and is exposed in provenance; it is not prepended to every claim.
The manifest carries source statement dates, not event dates. This input has no separate event-date
field, so new imported observations have `occurred_at=null`, even if every source is dated. Known
source dates and explicit nulls remain in Episodes. No import invents validity bounds or changes an
old source report into a current fact.

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

- `POST /api/material-imports/validate`: run the same deterministic canonical-write validation as
  submit in a rollback-only transaction. No receipts, Episodes, candidates, observations, evidence
  or changes remain. It may take transient database locks. Returns `status=validated`, payload
  previews and the request hash, with empty persisted-ID/reference arrays.
- `POST /api/material-imports/submit`: atomically save the receipt, source Episodes, immediately
  active observations/evidence and MemoryChange rows. Accepted candidate rows are retained as
  internal provenance/compatibility ledger entries, never as pending approval tasks. The response
  includes `canonical_record_refs`, existing `candidate_ids`/`episode_ids`, request hash and
  `trust_boundary=authenticated_caller_attestation`.
- `GET /api/material-imports/{import_id}`: exact durable receipt and bounded manifest for readback;
  no write. Read current canonical status at its record endpoint.

New validation/submit receipts use `validation_scope=immediate_memories`. Historical staging
receipts retain `pending_candidates_only`; reading or replaying an old receipt does not auto-upgrade
or repeat its old operation. Existing pending imports are handled by the separately verified data
conversion, not a side effect of receipt lookup.

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
  characters), `confidence`, and legacy `ai_use_policy` (`cautious_use`,
  `ask_before_use`, or `never_surface`). The policy field is deprecated/inert but remains in the
  compatible signed input shape; it never prevents immediate saving or use. Every source must
  support a claim.

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
drops tzinfo); claim event timestamps are not inferred from them. Provenance compares exact
instants/nulls, never local wall-clock approximations. The manifest is not silently
rehash-normalized to UTC. Full raw source bodies are never sent or stored.

## Replay, provenance, and retrieval

- Same key and normalized request return original IDs/references without new rows. Different
  content for the same key is 409. A historical staging receipt replays historically; it does not
  resubmit or promote its candidates.
- Same request under a new key is 409 `material_import_duplicate_content`, with the original import
  ID. Changed source/authorization/summary is a different request; no semantic deduplication is
  claimed.
- Receipt uniqueness, request-hash uniqueness and one transaction protect concurrent submits.
  Failure in canonical validation rolls back the entire batch, including Episodes and the receipt.
- `candidate_ids`, `episode_ids` and `canonical_record_refs` support exact readback. Accepted
  candidates are internal lineage and preserve source-import compatibility validation.
- The actual human source actor, locator and source timestamp/null are preserved in the manifest
  and Episode. They appear in structured context provenance. A source author's statement and the
  agent's inference remain distinct.
- Unknown source dates remain null and do not require an approval step. Do not invent an event date
  or inject recency wording to make a summary appear current.
- Saved observations are available to lexical/context retrieval immediately. Embedding generation
  remains an independent derived-index operation. Retrieval never writes or supplies fresh evidence.
- Corrections after import use exact-record memory correction with a new bounded human correction
  source; they preserve the old imported record, Episode/evidence, receipt and history.

### Historical staging and curation compatibility

Older `pending_candidates_only` receipts and accepted/pending candidate records remain inspectable.
Their existing source-pack verification continues to check receipt, target, author, locator,
excerpt and hashes; bare `source_type=import` never establishes authorization. Legacy curation and
manual-accept interfaces may still recognize those old records, but are not steps in new import
submission. Any original `material_source_date_unknown`, review/defer or planner-budget diagnostics
remain historical facts, not current approval requirements. Do not rewrite old signed request
bodies or hashes to pretend they used the new protocol.

## Deployment and previous migration history

The current schema adds `20261001_0012` on top of the original import migration. Apply it with the
[save-first conversion procedure](../plans/save-first-memory-schema.md), a verified backup/restore
and bounded conversion manifest. Replaying legacy receipts does not itself convert pending rows.

The original import migration and deployment constraints below are retained as history for existing
installations. They do not impose another approval stage on new authorized import saves.

### Original `0011` activation record

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
inputs, atomic rollback, concurrent replay, immediate canonical saves and preserved source attribution. PCR's separate synthetic test exercises unchanged ordinary current-
user-only post-turn and no-write read hooks. Run the wider existing curation,
reconciliation, enrichment, CLI, candidate, context, and migration regressions
before integration.

# Automatic Observation Embedding

**Status:** planned, not implemented. Selected as next on 2026-10-19; the 2026-10-22 review
places RC-A and the common writer foundation first. See the [current roadmap](../kinlayer-roadmap.md).
**Depends on:** [save-first memory schema](save-first-memory-schema.md) (SF09: an embedding
failure must never lose a canonical write) and the applicable identity, revision and timestamp
rules in the [shared record lifecycle contract](record-lifecycle-contract.md).

**2026-10-22 review delta:** this document now specifies indexing concurrency and retry ownership.
EA01–EA08 and the historical evidence below are retained. These are planning changes, not evidence
of implementation or authorization to deploy or transform live data.

## Problem

`POST /api/memories` and material imports store new observations with
`embedding_status=pending` and never call the embedding provider. Only the legacy
`POST /api/observations` path (`services/relationships.py`) embeds synchronously. Indexing new
memories therefore depends on someone running `POST /api/embeddings/backfill` or
`kinlayer embedding backfill`.

Live evidence (2026-10-19, read-only DB queries before the manual run):

- 197 of 240 active observations (82%) were `pending`, although the provider status was `ready`.
  Every observation created through `/api/memories` since 2026-10-02 was unindexed except one
  manually backfilled batch.
- Retrieval (`services/retrieval.py`) takes `max(semantic, lexical)`. A pending row has no vector,
  so it can match only by token overlap.

The user then authorized one manual backfill. It processed all 197 rows in about 47 seconds with
no failures, so all 267 observations (240 active, 27 superseded) are `ready` with 1536-dimension
`text-embedding-3-small` vectors. The backup taken beforehand is
`~/backups/kinlayer/main-sync-20261019T060913Z/` on the live host. This was a one-time fix: new
writes will be pending again until this plan is implemented.

## Goal

Every eligible ordinary observation stored through any current write path becomes `ready`, or
`failed` with an error, without a manual step. Write latency, transactions, and receipts stay
unchanged. A `ready` row proves that its content has an indexed vector; it does not prove that a
text-only query uses semantic retrieval. Query embedding ownership, vector compatibility and
truthful match reasons belong to [runtime correctness](runtime-correctness.md), which must supply
separate end-to-end search evidence.

## Design

1. **After commit, never inside it.** Once the memory/import transaction commits, schedule
   indexing for the new observation IDs, for example with FastAPI `BackgroundTasks` from the route.
   The canonical write and its receipt do not wait for the provider. Provider errors leave the row
   `pending` or `failed` and never roll back or fail the request.
2. **A periodic sweep catches anything the post-commit hook missed.** Examples: a process restart
   before the background task ran, a temporary provider outage, or rows written by legacy paths.
   An in-process loop runs on a configurable interval and calls the existing backfill on
   `pending`/`failed`/`stale` rows. It has a batch limit and a retry ceiling (for example, skip rows
   with `failed` more than N times until a manual backfill). The hook, sweep and manual backfill
   use the same database-backed claim operation; an in-process loop lock alone is insufficient
   when API workers overlap. The shared operation is specified below.
3. **Do not change the concurrency token.** `embed_observation` currently commits through the ORM,
   which bumps `updated_at` through `TimestampMixin.onupdate`. `updated_at` is the
   `expected_updated_at` token for corrections, so a background index can make a client's pending
   correction fail with a stale-write 409. SQLAlchemy Core `UPDATE` also applies column `onupdate`;
   using Core does not by itself preserve the token. Every indexing-state mutation, including
   claim, retry, completion and failure, must explicitly preserve the database's current
   `updated_at` value (for example, `updated_at = observations.updated_at`) or use a statement
   that bypasses that default. Do not restore an earlier client-read timestamp over a newer
   canonical change. Tests must prove token stability with the real model and SQL statements.
4. **Index only eligible revisions.** Index ordinary observations with an active/disputed revision
   status; exclude superseded/deleted revisions and relationship assessments, including their
   legacy observation representation before M8 moves them. A corrected observation is a new row,
   so its old vector is never copied. Revision eligibility and temporal relevance are separate,
   as defined by the shared lifecycle contract: passage of a validity boundary alone does not
   rewrite the revision or discard its vector. Search applies the common temporal read rules.
5. **Configuration.** Add `KINLAYER_EMBEDDING_AUTO_INDEX` (default on when a provider is configured)
   and a sweep interval/batch size. Pass them through `docker-compose.yml` and `.env.example`, and
   expose the effective non-secret values under `/api/system/config.embedding`. With
   `provider=disabled`, nothing runs and rows stay `pending`.
6. **Observability.** `/api/embeddings/status` and the Settings screen already show
   pending/ready/failed counts. Add the last sweep time and last error summary, without secrets.

### Shared claim and retry protocol (2026-10-22)

- Persist an owner token, lease expiry, attempt count, next retry time and last sanitized failure
  for each indexing work item in the existing database. The work identity includes observation
  revision ID, content fingerprint and provider/model/dimension configuration. Queue services
  outside the API process remain excluded.
- Hook, sweep and manual backfill atomically claim eligible work before calling the provider.
  Only the current lease owner may publish a result. Two API processes must not acquire the same
  live lease. Keep database transactions short; do not hold a row lock through network I/O.
- Bound the provider timeout and make the lease cover that timeout plus a completion margin;
  renew a lease when needed. Reclaim expired leases after worker loss. A process crash can cause
  a later repeated provider request, so this is not an exactly-once external-call guarantee.
  A former owner's late result must fail the owner/generation comparison and be discarded.
- Before publishing, compare revision identity, content fingerprint, model configuration and
  current eligibility again. A result for an edited, superseded or otherwise changed revision
  cannot overwrite the newer state. Record model and actual dimension together with the vector;
  reject empty, non-finite or configuration-incompatible results before marking it `ready`.
- Count and persist attempts before the provider call, schedule bounded retry backoff, and retain
  exhaustion across restarts. Manual backfill uses the same claim and may explicitly reset an
  exhausted retry budget; ordinary sweeps may not silently reset it. Automatic indexing off
  disables hooks and sweeps; an explicitly requested manual backfill remains available when a
  provider is configured. A disabled provider makes no provider calls in any path.
- Provider errors must not expose request credentials or raw sensitive input in status responses.
  A failed indexing attempt cannot alter a canonical receipt, memory history or correction token.

## Out of scope

- Embedding facts, edges, or relationship assessments. Semantic retrieval covers observations only.
- Changing retrieval scoring, thresholds, or models.
- A queue service outside the API process (Redis, Celery). Reconsider only if the in-process approach
  proves insufficient.

## Acceptance criteria

EA01–EA08 retain their IDs and original purpose. Observation indexing below means eligible
ordinary revisions; EA05's auto-index-off case governs automatic work, while explicitly requested
manual backfill follows the shared protocol above.

| ID | Required evidence |
| --- | --- |
| EA01 | After a `/api/memories` create or correct with a working provider, the new observation becomes `ready` with no manual call; the receipt and latency do not depend on the provider. |
| EA02 | A provider failure or timeout still returns the normal receipt; the row ends `failed` with an error and is retried by the sweep. |
| EA03 | Authorized material imports (V1/V2) are indexed the same way. |
| EA04 | Indexing does not change `updated_at`; a correction prepared before indexing still succeeds. |
| EA05 | `provider=disabled` or auto-index off leaves rows `pending` and makes no provider call. |
| EA06 | The sweep does not process the same row twice in parallel and respects its batch limit and retry ceiling. |
| EA07 | Targeted tests, `uv run pytest`, and `uv run ruff check .` pass, and tests make no external provider call. |
| EA08 | Live readback after a deployment the user authorizes separately: new agent writes reach `ready` without a backfill. |
| EA09 | Hook, sweep and manual backfill race across two API processes; only one acquires each live lease, and an expired owner's late result cannot publish. Recovery after worker loss makes progress without claiming exactly-once provider execution. |
| EA10 | Attempts, backoff, next retry and exhaustion survive process restart; manual retry reset is explicit. Off/disabled configurations obey the automatic/manual distinction above. |
| EA11 | Claim, retry, success, failure and recovery updates preserve `updated_at` with the actual SQLAlchemy model; a concurrent canonical correction is never overwritten by restoring an older timestamp. |
| EA12 | Superseded/deleted revisions and assessments are excluded; edited content or changed model configuration rejects an obsolete completion. A ready vector has a finite, nonempty value and compatible model/dimension metadata. |
| EA13 | Indexing verification is reported separately from runtime semantic-search verification; `ready` counts alone do not satisfy the search acceptance criteria in runtime-correctness.md. |

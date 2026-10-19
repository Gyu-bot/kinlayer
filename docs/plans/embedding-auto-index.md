# Automatic Observation Embedding

**Status:** next implementation plan, set by the user on 2026-10-19. Not implemented yet.
**Depends on:** [save-first memory schema](save-first-memory-schema.md) (SF09: an embedding
failure must never lose a canonical write).

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

Every observation stored through any current write path becomes `ready`, or `failed` with an
error, without a manual step. Write latency, transactions, and receipts stay unchanged.

## Design

1. **After commit, never inside it.** Once the memory/import transaction commits, schedule
   indexing for the new observation IDs, for example with FastAPI `BackgroundTasks` from the route.
   The canonical write and its receipt do not wait for the provider. Provider errors leave the row
   `pending` or `failed` and never roll back or fail the request.
2. **A periodic sweep catches anything the post-commit hook missed.** Examples: a process restart
   before the background task ran, a temporary provider outage, or rows written by legacy paths.
   An in-process loop runs on a configurable interval and calls the existing backfill on
   `pending`/`failed`/`stale` rows. It has a batch limit and a retry ceiling (for example, skip rows
   with `failed` more than N times until a manual backfill). The sweep must not run the batch
   concurrently with itself (use a lock or a single worker).
3. **Do not change the concurrency token.** `embed_observation` currently commits through the ORM,
   which bumps `updated_at` through `TimestampMixin.onupdate`. `updated_at` is the
   `expected_updated_at` token for corrections, so a background index can make a client's pending
   correction fail with a stale-write 409. Embedding updates should write only embedding columns,
   for example with a core `UPDATE` that leaves `updated_at` unchanged, and tests should prove the
   token is stable.
4. **Index only rows worth searching.** Prefer active/disputed rows. Superseded or retracted rows do
   not need new vectors. A corrected observation is a new row, so its old vector is never copied.
5. **Configuration.** Add `KINLAYER_EMBEDDING_AUTO_INDEX` (default on when a provider is configured)
   and a sweep interval/batch size. Pass them through `docker-compose.yml` and `.env.example`, and
   expose the effective non-secret values under `/api/system/config.embedding`. With
   `provider=disabled`, nothing runs and rows stay `pending`.
6. **Observability.** `/api/embeddings/status` and the Settings screen already show
   pending/ready/failed counts. Add the last sweep time and last error summary, without secrets.

## Out of scope

- Embedding facts, edges, or relationship assessments. Semantic retrieval covers observations only.
- Changing retrieval scoring, thresholds, or models.
- A queue service outside the API process (Redis, Celery). Reconsider only if the in-process approach
  proves insufficient.

## Acceptance criteria

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

# Sensitivity retirement

This contract supersedes older sensitivity examples and planning requirements.
Kinlayer no longer classifies information as `low`, `medium`, or `high` sensitivity.
`ai_use_policy` remains a separate, active control.

## Runtime and public contract

- Entity, fact, edge, observation, Episode, candidate, context, graph, ontology,
  curation source-pack, reconciliation evidence, enrichment, and agent-operation
  responses do not expose sensitivity fields. Nested historical candidate payloads,
  manifests, and audit summaries are projected without the retired metadata;
  persisted records are not rewritten. JSONL audit exports use the same projection.
- Retrieval has no sensitivity penalty or sensitivity-dependent surface bucket.
  Cautions and surface restrictions still honor `ai_use_policy`, observation type,
  status, ambiguity, and the existing evidence/identity rules.
- Curation auto-action and provisional-context eligibility no longer inspect
  sensitivity. AI-use policy, high-impact/contact-content safeguards, source evidence,
  temporal scope, identity resolution, approval, and exact source-window coverage
  remain enforced. A historical `high` label alone no longer blocks an otherwise
  eligible record; this is an intentional behavior change, not a data migration.
- Sensitivity filters are removed from API documentation, CLI commands, the
  read-only helper, and Web controls. Old HTTP query parameters are ignored rather
  than filtering out records. Old ordinary JSON request fields are tolerated and
  ignored; new canonical writes do not copy historical sensitivity labels.
- The Web no longer shows sensitivity columns, selectors, badges, graph details,
  merge policy entries, or ontology settings. It still shows AI-use policies.

## Historical storage and replay

No Alembic migration, table/column drop, record deletion, backfill, or relabeling is
required. Existing `sensitivity` columns and historical registry rows remain inert.
The old non-null column default (`medium`) still fills new rows for storage-schema
compatibility; it has no behavioral meaning and is not returned to clients.

Stored candidate payloads, audit records, curation plans, manifests, and authorization
snapshots remain intact. Candidate payload/evidence digests and entity snapshot digests
retain their exact historical algorithms, including the legacy stored values. Digests
are opaque server commitments, **not hashes of the public projected response**. Clients
must copy returned digests into expected snapshots rather than recomputing them from
sanitized payloads. Status, timestamps, provenance, hashes, idempotency checks, and
HMAC validation remain in force.

Two request-only compatibility fields remain deprecated:

- Reconciliation context-claim `sensitivity`, when supplied, remains in the exact
  signed request representation. It is not used for policy or canonical writes.
  New callers may omit it; absent values are excluded from the claim digest.
- Enrichment slot `sensitivity` remains request fingerprint metadata with its
  historical default `low`. It is not an ontology requirement or write/readback gate.

These exceptions preserve authenticated historical retries, not a usable feature.
Do not strip fields from already signed requests or rewrite persisted fingerprints.
For newly signed requests, signer and server must use the same canonical request
representation. Existing policy, capability, and HMAC checks must not be bypassed.

## Activation and rollback

The patch is based on deployed code commit `ac091ec`, which already contains curation,
reconciliation, and enrichment. Do not replace that deployment with an older
`origin/main` checkout lacking these features.

Activation requires rebuilding/replacing **both** API and Web images and coordinating
external Hermes/client validators to accept the field-free response contract. Existing
container images do not change when source files change. No deployment or restart is
performed by this patch; configuration, exposure, credentials, cost, and curation mode
are unchanged. Validate a read-only source pack before resuming periodic processing.

Historical storage remains available for rollback to prior code. New records created
after activation have inert defaults, not newly classified labels. No attempt is made
to retroactively classify them during rollback. Preserve the database and current
image references through the normal approved deployment procedure.

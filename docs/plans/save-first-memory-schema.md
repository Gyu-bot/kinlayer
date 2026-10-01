# Save-first Memory Schema

**Decision:** 2026-10-01, user authorized implementation and conversion of existing live records.
**Scope:** backend, agent input contract, existing data conversion, live verification. Frontend is
planning only in [frontend-rebuild.md](frontend-rebuild.md).

## Decision and prior-plan boundary

The ordinary loop is immediate canonical storage followed by correction during conversation.
Memory registration already means the agent may use it. AI-use policy and pre-save approval are
retired as product decisions. Embeddings remain a supported derived index and must remain
configurable, recoverable, and independent of whether a write succeeds.

This supersedes the candidate-first promotion and policy-gated retrieval requirements in
[relationship-curation-cycle.md](relationship-curation-cycle.md) and the approval-queue assumptions
in [relationship-reconciliation-cycle.md](relationship-reconciliation-cycle.md). Their acceptance
IDs, rationale, history, and compatibility interfaces are preserved. Do not interpret this change
as authorization to delete original episodes, old candidates, canonical history, or audit rows.
Source admission, bounded excerpts, deterministic validation, idempotency, and traceability remain.

## Findings that motivated the change

The live review found bundled profile claims, generic memo facts, missing typed values, a month-only
birth date stored as prose, reported assertions labeled as facts, user feelings without experiencer
roles, and an old “result not yet known” observation remaining current alongside later results.
The existing read contract omitted basis and participant information that agents needed to
interpret claims. These are data-model and contract defects, not reasons to require human approval
before every write.

## Implementation contract

1. Add `claim_basis` (`reported|inferred|unknown`) independently from observation topic. Preserve
   uncertainty; do not interpret source-reported claims as externally verified facts.
2. Standardize new fact values: supported profile text values use `{text}`; birth dates use partial
   date components and precision. Reject generic note fact types in new memory writes.
3. Add a single-operation `/api/memories` contract: stable `request_id`, `action`, optional old ref,
   one typed record, bounded human source, optional reason and concurrency timestamp.
4. Persist canonical change, source Episode/evidence, and common change history atomically. Retry
   the same request idempotently; reject reuse with a different body. Support replacement,
   retraction without replacement, and reattribution across people.
5. Keep one independently correctable claim per row. The agent performs semantic splitting; core
   validation must not pretend a string heuristic can prove atomicity.
6. Reuse observation participant links for speaker/experiencer/target roles. Keep source utterance
   time, event time, validity, and storage time distinct. Unknown dates remain unknown.
7. Expose basis, topic, roles, confidence, and structured provenance in agent reads. Exclude inactive
   replaced/retracted rows from current context. Policy compatibility fields must not hide records.
8. Retain embedding storage, provider configuration, status, and backfill. Do not copy a former
   embedding onto a semantically changed or split claim.
9. Mark candidate-first and AI-use-policy contracts as historical/compatibility paths. New clients
   must not create a hidden approval queue or depend on curation before retrieval.
10. Retain existing source-import authorization separately from ordinary conversation evidence.

The exact agent request structure and examples are maintained once in
[agent-write-instruction-pack.md](../agents/agent-write-instruction-pack.md). The generated OpenAPI
is the executable request-schema authority.

## Existing-record conversion

Before changing live data, capture a consistent database backup and inspect current schema,
application revisions, pending writes, and source linkage. Run the conversion against a restored
copy before the live apply. A successful backup command alone is not proof of recoverability:
restore and check the isolated copy.

Use a deterministic, idempotent conversion with an inspectable manifest. Preserve source IDs and
original row contents through supersession/history rather than destructive replacement. Where a
bundled row becomes several rows, each new claim retains old-row lineage and available evidence.
Do not invent quotations, exact dates, authors, confidence, or source links missing from the original.

Data-specific conversion requirements:

- separate supported profile attributes from schedules, context, preferences, and uncertain claims;
- normalize typed values and represent partial birthdays without invented components;
- migrate generic active facts into suitable individual observations;
- separate reported and inferred basis using actual wording/evidence; use unknown when unresolved;
- add participant roles only when the source establishes them;
- supersede obsolete state assertions only when a subsequent record establishes the transition;
- separate provenance prefixes from semantic content while preserving their source linkage;
- preserve old candidates/audits as history and remove their role as new-write approval gates;
- account for the existing pending backlog: migrate supported claims with real evidence, link
  exact duplicates to existing records, and archive invalid-source items with an explicit reason;
  do not silently promote unsupported content or leave a mandatory manual-approval backlog;
- invalidate/rebuild embeddings for changed observation text, keeping provider configuration intact.

Do not implement open-ended LLM interpretation inside an Alembic migration. Structural migration
and a reviewed, bounded live-data transformation are separate steps with separate evidence.

## Acceptance criteria

| ID | Required evidence |
| --- | --- |
| SF01 | One valid human-source request immediately returns an active record; no candidate is required. |
| SF02 | Invalid schema, ontology, source, or inconsistent typed value writes nothing. |
| SF03 | Same request retry returns original references; changed body with same key conflicts. |
| SF04 | Correction atomically preserves old row, creates replacement/evidence/history, and updates current reads. |
| SF05 | Retraction needs no replacement; reattribution changes the correct person without losing old lineage. |
| SF06 | Profile values support known partial dates and reject contradictory or fabricated components. |
| SF07 | AI reads carry basis, topic, confidence, people roles, and structured source attribution. |
| SF08 | AI-use-policy and confirmation compatibility values do not control new storage or current retrieval. |
| SF09 | Embedding provider absence/failure cannot lose the canonical write; changed observations are reindexable. |
| SF10 | Isolated restore and migration rehearsal pass before live conversion; conversion is replay-safe. |
| SF11 | Live old-to-new record accounting, source-link integrity, history, and context readback agree with the manifest. |
| SF12 | Agent documentation JSON examples validate against the implemented input structure. |
| SF13 | Existing frontend remains buildable; its redesign is a plan only, with no unrequested UI rewrite. |
| SF14 | Every former pending item has a traceable migration, existing-record link, or invalid-source archival outcome; no pre-save approval work is left for the user. |

Record actual validation and deployment evidence separately. This document states requirements;
its existence does not claim they have passed or that the live service has been updated.

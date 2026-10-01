# Kinlayer Frontend Rebuild Plan

**Status:** Replacement implementation authorized on 2026-10-01; the working implementation is
`frontend/src/v2/`. Acceptance evidence is tracked in
[frontend v2 verification](../verification/frontend-v2/README.md), separately from deployment.
**Dependency:** [save-first memory schema](save-first-memory-schema.md).

## 2026-10-01 decision delta: replace the old frontend

The earlier schema-delivery request explicitly deferred frontend implementation. After reviewing
the imported `frontend_v2` mockup and its audit, the user authorized discarding the old frontend,
using this design and Korean UI, and adopting the proposed save-first corrections. This follow-up
supersedes the planning-only boundary; it does not erase the earlier decision or UI01–UI09 below.

- `frontend/` is the runnable React/Vite replacement. `frontend_v2/` remains the imported design,
  mock interaction and audit reference; its fictional data and localStorage are not the app backend.
- Primary navigation is People, Memories, Graph and Changes. Search, Settings and read-only legacy
  diagnostics remain secondary. Source detail is reached from an individual memory or change.
- Approval, AI-use-policy and confirmation controls are removed. The old review composition is
  reused for stored memory changes, with exact before/after records and correction evidence.
- New read APIs fill the concrete list, filter, provenance and history gaps described below. The
  existing save-first schema/write contract remains in force; this replacement adds no migration.
- Implementation and the disposable preview do not deploy, restart or migrate the operating
  service, or convert its existing data. Deployment/live evidence must be reported separately.

The current implementation presents event/validity/source times but does not add a time-range
filter to the Memories list. Person/type/basis/status/text filters are server-side. A conversational
copy/send integration remains outside this delivery; no message is sent by the frontend.

## Intended experience

Kinlayer is the inspectable memory behind a conversation. Saving does not wait for a review screen.
The user can inspect what the agent remembers, see where it came from, and correct it naturally in
conversation. The frontend is a secondary inspection and correction surface, not a daily approval
inbox. Remove AI-use-policy and sensitivity controls from the replacement UI.

## Information architecture

| Surface | User purpose | Content/actions |
| --- | --- | --- |
| People | Find a person and understand current context | Names, aliases, structured profile facts, current relations, recent context; exact identity is visible. |
| Memories | Inspect individual stored claims | Search/filter by person, type, basis, event time and active/history status; edit, retract, reattribute. |
| Graph | Inspect a selected person's direct relationships | Ontology-backed relation filters, directed edges, exact memory/source links and a mobile relationship list. |
| Sources | Understand why a memory exists | Bounded human excerpts, actual author, source locator/time, linked claims; no full transcript browser. |
| Changes | Understand what changed | Creation, correction, retraction, reattribution and migration lineage; old/new comparison and reason. |
| Search | Check what an agent can retrieve | Query, matched people, current claims, basis, evidence, time and relevance explanation. |
| Settings | Operate the local service | API connectivity/auth status, embedding provider/model/dimension/index health; secrets remain server-side. |

A person's detail page composes profile, relationships, memories, sources and recent changes. The
initial plan placed Graph outside the main navigation; the approved mockup retains it as a primary
view. Existing candidate/agent-operation history is read-only under diagnostics, with no
“must approve before use” action list. Curation execution is not exposed by the replacement UI.

## Interaction decisions

- Show concise individual claims. Group related claims visually without merging their identities or
  making a single edit affect an entire paragraph.
- Distinguish “reported” from “inferred”; unknown historical basis is visible without suggesting it
  is rejected or awaiting approval. Confidence is secondary diagnostic detail, not a truth badge.
- Render partial dates honestly: year-only, year/month, or full date. Never display an invented day.
- Show who spoke, who felt, and who a claim concerns when these differ.
- Correction opens the exact old record and source context; submit through the same memory API as
  agents. Retraction requires no replacement text. Reattribution selects the intended person.
- Show source timestamps separately from described event time and current validity.
- Superseded/retracted rows appear only in explicit history views and old/new comparisons.
- A failed write preserves the user's draft and explains the actual validation/conflict. Retry reuses
  its request ID; changing the draft creates a new operation. Do not optimistically show success
  until the API confirms the transaction.
- Conversation remains the primary correction path. The UI can present a bounded copyable
  correction request with the exact record ref; a chat integration must not require a new approval
  queue or silently send messages without user action.

## Backend dependencies and original gap inventory

The memory write/history APIs, typed fact values, basis/roles, and context source metadata come from the
schema work. Inventory actual endpoints/OpenAPI before designing screens. The following read
capabilities were identified for verification/addition during the frontend implementation task.
This original inventory is preserved; the implementation mapping follows it:

- paginated/filterable current and historical memories with stable record refs;
- record history already has `/api/memory-changes` with pagination and exact old/new-ref filtering;
  add/verify person-scoped aggregation and a complete cross-kind/cross-person timeline;
- bounded source detail and reverse source-to-memory links;
- exact record concurrency/version fields and consistent stale-write conflict responses;
- aggregate counts that distinguish active records, historical records and missing original sources;
- embedding health and backfill state without exposing provider secrets;
- canonical person resolution for merged aliases and explicit person selection for reattribution.

HTTP API owns every state change. Do not create browser-only corrections, source links, status, or
embedding behavior. Existing low-level endpoints and old UI compatibility fields are not the target
information architecture.

### Implemented read mapping

| Capability | API used by the replacement |
| --- | --- |
| Complete directory filtering and counts | `GET /api/people`: name/alias query, relation type, name/recent-reference sort, pagination and current memory summaries. |
| Current/history memory inventory | `GET /api/memories`: entity, record type, claim basis, text, active/history/all and source filters, with server totals/pagination. |
| Exact memory and historical payload | `GET /api/memories/{record_type}/{record_id}`: typed payload, concurrency timestamp, participant roles, evidence and missing-source marker. |
| Person-scoped and record-scoped changes | `GET /api/memory-changes` with `entity_id` or `record_ref`; individual change detail resolves its old/new refs. |
| Source detail and reverse links | `GET /api/episodes/{id}` and `GET /api/memories?source_episode_id=...&status=all`; a missing original retains its available excerpt without a dead link. |
| Search and graph | Existing context retrieve/pack and ego graph APIs, with current-validity filtering, actual self identity and ontology relation types. |
| Operational visibility | Existing system health/config and embedding status; setting readiness and indexed-record counts are shown separately. |

Memory count summaries count a record once per person even if several participant roles apply.
Merged-person navigation remains readable. New identity creation and name/alias edits use their
existing entity/alias APIs; memory creation or correction never uses legacy fact/edge/observation
PATCH/DELETE. No new embedding mutation or merge execution surface is introduced.

## Earlier schema-delivery transition constraint (historical)

At the schema-delivery stage the old frontend was intentionally unchanged. Its fact/edge/observation
PATCH/DELETE actions cannot modify new or migrated tracked memories: the API returns HTTP 409
`memory_change_required`. The original interim instruction was: until the replacement UI connects its correction actions to
`/api/memories`, use the agent/CLI memory contract for changes. Do not weaken this guard or add a
browser-side workaround to make the old edit forms appear functional. Existing policy/source
controls were retained only pending this rebuild; they did not define backend write policy.

The new frontend must discover `system/config.memory_write`, submit one exact old ref and human
correction source, and render the confirmed receipt/history. `system/health.embedding` is effective
configuration status, not a successful provider call or proof that every record is indexed.

The replacement now checks `GET /api/system/config.memory_write` for endpoint `/api/memories`,
contract version `2`, and `review_required: false` before enabling memory writes. It sends exact
`old_record_ref`/`expected_updated_at`, a human source and idempotency key; failed writes keep the
draft, unchanged retries keep their key, and a changed request gets a new key. Keys also work on LAN
HTTP without `crypto.randomUUID`. The only app data in localStorage is the user-entered API token.

## Delivery sequence and verification boundary

The original sequence is retained for traceability. The approved replacement implements the
frontend/read-API work; successful checks and remaining live/deployment boundaries belong in the
[verification record](../verification/frontend-v2/README.md), not an inferred completion status here.

1. Complete schema implementation, agent contract and verified live conversion.
2. Inventory actual current API responses and settle the read-capability gaps above.
3. Review low-fidelity flows for People → Memory → Source → Change, including correction,
   retraction, reattribution, empty states, ambiguity and concurrent edits.
4. Establish visual tokens/components and responsive navigation; verify Korean text, keyboard
   navigation, focus and contrast with real rendered pages.
5. Implement the new frontend against typed/generated API contracts in a separate focused change.
   Replace all memory PATCH/DELETE edit paths with correct/retract/reattribute and verify
   `memory_change_required` handling before enabling edit controls.
6. Validate real journeys against a restored, non-production dataset; then perform read-only live
   checks and narrowly scoped user-authorized write verification.
7. Retire old approval/policy surfaces only after new routes and historical access are verified.

## Acceptance criteria

| ID | Result |
| --- | --- |
| UI01 | The ordinary navigation contains no pending-approval requirement or AI-use-policy form. |
| UI02 | Every displayed claim has an exact record reference and can expose its source and change history. |
| UI03 | One claim can be corrected/retracted/reattributed independently through `/api/memories`; no legacy mutation bypasses history, and current context reflects the result. |
| UI04 | Basis, uncertainty, partial dates and participant roles survive rendering without stronger claims. |
| UI05 | History preserves prior wording/source and explains replacement or migration lineage. |
| UI06 | Search presents the same current records as the agent API and explains stale/conflicting data clearly. |
| UI07 | Embeddings remain configurable and observable; an unavailable provider does not hide saved memories. |
| UI08 | Mobile/desktop, keyboard, empty/error/loading states and Korean content pass direct browser checks. |
| UI09 | Existing source/audit records remain accessible; no backend state is duplicated in browser storage. |

The original planning-only document made no frontend changes. The subsequent approved delivery
replaces components, routes, styling and interactions in `frontend/`, while preserving this plan's
acceptance IDs and the imported `frontend_v2/` reference.

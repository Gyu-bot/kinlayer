# Kinlayer Frontend Rebuild Plan

**Status:** Planning only. The 2026-10-01 request explicitly defers frontend implementation until
backend/schema and live data conversion are complete.
**Dependency:** [save-first memory schema](save-first-memory-schema.md).

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
| Sources | Understand why a memory exists | Bounded human excerpts, actual author, source locator/time, linked claims; no full transcript browser. |
| Changes | Understand what changed | Creation, correction, retraction, reattribution and migration lineage; old/new comparison and reason. |
| Search | Check what an agent can retrieve | Query, matched people, current claims, basis, evidence, time and relevance explanation. |
| Settings | Operate the local service | API connectivity/auth status, embedding provider/model/dimension/index health; secrets remain server-side. |

A person's detail page composes profile, relationships, memories, sources and recent changes. Graph
view is an optional relationship view rather than the main navigation. Existing candidate/curation
history may be reachable under history/diagnostics, but has no “must approve before use” action list.

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

## Backend dependencies and gaps to settle before UI implementation

The memory write/history APIs, typed fact values, basis/roles, and context source metadata come from the
schema work. Inventory actual endpoints/OpenAPI before designing screens. The following read
capabilities must be verified or added in a later frontend implementation task; they are not claims
that these APIs already exist:

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

## Current frontend transition constraint

The old frontend is intentionally unchanged in this schema delivery. Its fact/edge/observation
PATCH/DELETE actions cannot modify new or migrated tracked memories: the API returns HTTP 409
`memory_change_required`. Until the replacement UI connects its correction actions to
`/api/memories`, use the agent/CLI memory contract for changes. Do not weaken this guard or add a
browser-side workaround to make the old edit forms appear functional. Existing policy/source
controls are retained only pending this planned rebuild; they do not define backend write policy.

The new frontend must discover `system/config.memory_write`, submit one exact old ref and human
correction source, and render the confirmed receipt/history. `system/health.embedding` is effective
configuration status, not a successful provider call or proof that every record is indexed.

## Delivery sequence

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

No frontend components, routes, styling, or interaction code are changed by this plan.

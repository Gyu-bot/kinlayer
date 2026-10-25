---
name: kinlayer-local
description: "Use for Kinlayer person reads and save-first memory writes."
version: 2.3.0
author: Gyu-bot
license: MIT
metadata:
  hermes:
    tags: [kinlayer, relationship-memory, personal-context, local-api, retrieval]
    related_skills: [gyurin-personal-context, hermes-agent]
---

# Kinlayer Local

Use this skill for the smallest safe read of real-person relationship memory and for Kinlayer's save-first write contract. `gyurin-personal-context` decides whether person context matters; Kinlayer owns canonical people, aliases, edges, person facts, observations, cautions, interaction context, provenance, and change history.

## Read boundary and routing

Load when a named or identifiable real person could materially change relationship advice, a message/calendar briefing, or a person-context audit. Pair with `gyurin-personal-context` for personal judgment. Do not use it for gyurin-level social patterns, generic profile recall, or ordinary Discord-history search.

Use this order: constrained Kinlayer tool when available → repo-owned deterministic helper when present → documented API/debug route only when necessary. Discover runtime connection settings from active configuration; do not hardcode or disclose local addresses in ordinary chat. Read `references/api-read-and-audit.md` for read commands, endpoint shapes, and write/history audit. Read `references/save-first-memory-writes.md` before any memory create/correct/retract/reattribute. For separately authorized source-material storage, read `references/authorized-material-import.md` and check activation before use. Read `references/approval-safe-access.md` when generic command approval is the issue.

Resolve identity before using a person's context or taking any person-targeted action. This gate covers answer-time recall, context packs, registrations, aliases, memory writes/corrections, relationship profiles, and authorized imports—not only new-person creation. Reuse a clearly established same-conversation identity unless new evidence conflicts. A name match, even `single_strong_match`, is candidate evidence rather than proof when the relationship or other context conflicts; `no_match` is not permission to create.

For an unfamiliar name, shortened name, pronoun, homonym, or conflicting identity, inspect the smallest relevant candidate set and bounded source-backed relationship/trait context. Candidate-card reads for disambiguation are allowed, but must not be applied as the mentioned person's facts before resolution. Include protected self when checking whether an apparent new person is the owner; never turn the owner's name into a second entity or infer the speaker of a quoted first-person statement.

If identity remains uncertain, **pause the person-dependent work and ask gyurin one natural clarification before continuing, even in the middle of an ongoing conversation**. Anchor the question in the candidate's verified relationship to gyurin and one useful distinguishing trait or interaction when available, not merely two similar names. Use only actually retrieved or current-session evidence; preserve reported/inferred status and never invent a relationship, recent contact, or date. If no safe distinguishing context exists, say that and ask how gyurin knows the person. Reveal only the minimum needed to distinguish candidates.

The CURRENT conversational agent owns semantic person identity, not an auxiliary classifier or a spelling rule. In personal-context-router 0.15.0, use the native `kinlayer_identity` tool: `lookup` retrieves the smallest source-backed candidate set; then `decide` passes the chosen existing candidate, evidence refs, exact native conversation quotes and excluded alternatives to the writer. Include `mention_surfaces` explicitly when multiple spellings of this same person should be authorized; the writer never expands spellings itself. A contextually clear shortened, unfamiliar or variant name needs no extra user confirmation. Ask one natural question only if genuinely unresolved after comparing actual conversational context and the bounded candidates. `unresolved`, lookup failure or missing handoff blocks that write without imposing a question. `status` is a no-backend/no-write runtime probe.

After clarification resume the topic without repeating supplied facts. Clarification does not authorize aliases, merges, creation, source changes or historical replay. Decisions bind only the current native profile/backend/session/sender/turn and expire with that turn; repeat the handoff, not the question, on a new turn. Old deferred claims/journals remain history and are not automatically released by a new semantic decision. The post-turn writer remains the sole automatic owner using current genuine human text only; do not duplicate it with manual writes. Failed/unknown/malformed/incomplete lookups never become new people. Retrieve only relevant context, never inventory unrelated people.

## User-facing context contract

Explain naturally why the context is relevant, based on current user-provided facts or retrieved past context. A single answer may combine supported identity, relationship, and situation context; do not make gyurin repeat facts already present in the request or safely retrieved. Do not expose record refs, internal status codes, base URLs, or schema mechanics unless he is explicitly debugging Kinlayer.

Read `claim_basis` (`reported`, `inferred`, `unknown`), confidence, topic (`observation_type`), participant roles (`related_entities`), and structured provenance with each record. `reported` means a human source said it, not external verification; `inferred` stays an inference; `unknown` is not upgraded. Ordinary context uses current (active/disputed) records; superseded/deleted records are history, read only through explicit change-history queries. Separate what Kinlayer indicates, your judgment, and material uncertainty. A current user correction wins over stored context. If the read fails or matters but is unavailable, say so plainly and use only an appropriate fallback with uncertainty labeled.

## Write and canonical boundary

Kinlayer is **save-first**: a valid memory is stored immediately through `POST /api/memories` (one independently correctable claim per request) and fixed later through correct/retract/reattribute. There is no candidate, curation, or human-approval stage before ordinary memories exist. Confirm the deployment advertises `memory_write = {endpoint: /api/memories, review_required: false, contract_version: "2"}`; if not, stop and report rather than falling back to legacy candidates.

At each session start fetch the live ontology through the repository helper's `ontology` command or `GET /api/ontology`. Read `version` and full definitions, not just type names. In the helper these are `version` and `definitions.edge_types`; `values` also contains readable legacy types and is not a write allowlist. New relationships require `write_supported: true`. Invalidate any API-instance-scoped cache when the version changes, and refresh before an unknown type or after an ontology validation error. Missing/offline definitions never authorize guessing. The relationship revision adds no appointment/meeting tracker; preserve source-described 썸 as symmetric without inferring verified mutual attraction. See the write reference for direction, legacy correction, and property rules.

- Answer-time retrieval never writes back a card, observation, or summary.
- Automatic post-turn writes belong to `personal-context-router`, using the current turn's human-authored text only.
- Ordinary conversational facts and clear corrections use the post-turn owner once; do not duplicate them with answer-time CLI/API writes. Separately authorized agent-operated repairs outside that automatic path follow `references/save-first-memory-writes.md`: resolve the exact person, read the exact old record, and verify readback. Choose one execution owner before dispatch, never both.
- Legacy `/api/candidates`, curation, reconciliation, and enrichment interfaces are compatibility/history only. Do not create candidates for new memories, accept hidden candidates, or describe a saved memory as pending review.
- Never use legacy PATCH/DELETE on tracked memory records (HTTP 409 `memory_change_required`) or create an unlinked replacement.
- Do not copy person cards into `relationships.md`, memories, or skills.
- Assistant replies, tool output, retrieved Kinlayer/Hindsight/Honcho data, skills, logs, prompts, and compaction are never new human evidence.

User-supplied material and specifically requested human-source reads follow gyurin's scoped storage authorization in `gyurin-personal-context` and `references/authorized-material-import.md`, without requiring another save request. Read-only/no-remember overrides that authorization. Only the designated source/person/time scope is admitted; never arbitrary tool output or unrelated history. Use the source-aware workflow and preserve actual speaker/author separately from requester identity. Never launder attachments or imported text through ordinary `/api/memories` as the user's own statement.

## Audit versus repair

When an unresolved identity blocks a write, inspect the exact native handoff and source-backed candidates before blaming user ambiguity. Version 0.15.0 removes the auxiliary identity verdict and surface/display equality gate; a missing, forged, conflicting, stale or cross-scope decision is a system/write-authorization issue, not a request for repetitive confirmation. The plugin never appends a question behind the agent's back. Read `router/identity.py` and `docs/identity-guard.md` in the installed package after updates.

Separate identity context from claim evidence: conversation history may establish the referent, but only this turn's genuine human text may support a new ordinary memory. Reuse a clearly established referent for advice; never treat a failed handoff as proof the user was unclear. Native middleware captures IDs independently of tool arguments; the writer validates the process-local proof and current candidate/source snapshot before any new write. Missing proof stays unresolved.

**Audit is read-only.** Compare the router decision log with the exact record, its provenance, and `/api/memory-changes` history. It may conclude saved, failed validation, conflict, ambiguous identity, or runtime/API failure. It must not resend a write, patch router code, or restart services. A repair is a separately authorized correction with its own readback.

## Completion check

- The requested person was resolved without identity guessing.
- The smallest relevant context was used and its provenance/uncertainty remained clear.
- No answer-time read caused a write, duplicate storage, or canonical change.
- Any write used one claim per request, explicit basis/confidence, a bounded human source, and a stable request ID; its result was read back. Errors, timeouts, and conflicts were reported as such, never as saved or pending review.

## Relationship profile axes

Kinlayer now carries the user's perspective toward a person as four independent current axes,
separate from relationship kinds. Fetch `ontology.relationship_profile` and its independent version;
read its labels/descriptions/values. The helper `relationship-profile --entity-id ID` and context
cards/packs retain exact source-backed axis records. Null means unset, never a default low value.

All axes require explicit user statements or UI choices (`reported`), including importance and
connection state. Rare contact does not imply low closeness, low importance or disconnection;
family and missing logs do not supply an assessment. Importance only softly prioritizes already
relevant context. No decay, interaction counting or meeting/calendar logging is introduced.

The automatic post-turn writer resolves self and the target, reads the current profile, and uses
exact-axis correction when a current row exists. An explicit reset retracts only that axis; an
already-unset axis is a no-op. Failed/malformed reads are never treated as empty. Read the write
reference before any separately authorized manual operation; do not duplicate the post-turn writer.

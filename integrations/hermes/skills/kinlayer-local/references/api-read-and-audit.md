# Kinlayer API reads and write audit

Use this reference when a Kinlayer read needs command/API detail or a saved/failed write needs diagnosis. Read the active Hermes configuration for the base URL; do not rely on or disclose a hardcoded local address in ordinary chat.

## Read route

1. Prefer a constrained Kinlayer tool when installed.
2. Otherwise use the repo-owned `scripts/kinlayer_client.py` read/debug subcommands with the configured base URL. Its compact card/retrieve/pack output preserves typed facts, edges, claim basis/confidence, participant roles, and structured provenance while omitting embeddings and legacy approval fields. It stays read-only; use exact record/Episode/history GETs for details not exposed by a helper subcommand.
3. Use raw HTTP for an API/schema diagnostic the helper cannot perform. `/api/system/health` is health; `/api/system/config` advertises `memory_write`; `/openapi.json` is the live wire schema.

Routine read sequence:

- Apply the main skill's identity gate before using a person card or acting on an entity ID. A clearly bound identity can be reused within the conversation unless contradicted.
- Resolve with `POST /api/entities/resolve` or bounded entity search. The existing resolver accepts `surface`, `aliases`, and `source.include_self`; self is excluded by default. Supply only source-supported aliases, and include self when checking a possibly duplicated owner identity. A shortened-name search only discovers candidates; it does not prove identity.
- Read the smallest candidate context necessary to compare the relationship to gyurin and distinctive traits. Keep candidate evidence separate from confirmed subject context. A name-only `single_strong_match` cannot override contextual conflict. Failed/incomplete lookup is not `no_match`.
- Unresolved identity → pause and ask one relationship/trait-grounded clarification, including during an ongoing discussion; do not first deliver advice based on the guessed candidate. If no candidate context is available, ask how gyurin knows the person.
- One clear person → use `GET /api/entities/{id}/context-card`; for a broad briefing use `/api/context/retrieve` or `/api/context/pack` while preserving separate identities and uncertainties.
- Clarification alone never creates, aliases, merges, or replays memory writes. Resume the original work after resolution under its existing authorization and evidence contract.

Context-card sections: `profile_facts`, `relationship_edges`, `stable_context`, `recent_context`, `communication_context`, `cautions`, `provisional_context`, `provenance_summary` (structured evidence with `actor`, `source_type`, `source_ref`, `source_occurred_at`, `excerpt`), and `retrieval_hints`. Keep each record's `claim_basis`, confidence, `observation_type`, `related_entities` roles, and source attribution in the model context. Recursively drop `embedding` vectors and embedding metadata before printing. Records may still contain legacy `claim_type`, `ai_use_policy`, or `source_candidate_id`; these are inert compatibility fields, not use or approval gates.

## Hermes identity helper and natural clarification

When PCR's identity command is installed, use the active profile's `hermes context-router identity-resolve --surface <name> --human-context <verbatim-current-human-message>`. Optional `--hint-query <exact-current-human-span>` may be supplied at most twice to search distinguishing relationship/trait content as well as names. Do not pass secrets or a whole conversation; preserve the actual human text rather than reconstructing confirmation.

The command is read-only and returns `mode: read_only_candidates`, bounded source-backed candidates/hints, uncertainties and `write_authorized: false`. Its stateless `clarification_needed` does not override an already grounded native same-session identity. Use the current conversation to judge read-only identity; when genuinely ambiguous, ask one natural question anchored in the relationship and distinguishing context. Never require a code, ID, exact sentence or copied hint. A natural short affirmation answers only its clear preceding identity question; otherwise clarify, not guess.

The native `kinlayer_identity` tool binds automatic-writer decisions through trusted tool-execution middleware and pre/post hooks to the actual profile/backend/session/sender/turn, not CLI-supplied IDs/history. The CURRENT agent reasons over its actual conversation and source-backed candidate hints. A clear variant or unfamiliar-but-identifiable name needs no repeated confirmation. Pass `decide` with exact context quotes, supplied evidence refs and excluded alternatives; explicitly list `mention_surfaces` if multiple spellings should be authorized. Decisions expire with the turn; on a new turn repeat the handoff, not the user's prior facts or a confirmation ritual. Private PCB-only routes retain their separate stricter workflow boundary.

A confirmation is identity context, not a new factual claim. PCR 0.15.0 preserves old deferred/pending history without clearing or replaying it. Missing/invalid/stale/cross-scope handoffs leave new writes unresolved and do not demand a question. The plugin never appends an identity question to the final answer. API failures, partial searches and unknown outcomes never permit creation or replay. Read the plugin's `docs/identity-guard.md` for current tested limits; source/disk changes do not establish Gateway activation.

## Identity API boundaries

- The existing resolver scores names/canonical names/active aliases; its accepted `relation_hint` is not implemented as contextual matching in the inspected backend. Join bounded candidate cards, `/api/people` relationship filters or `/api/memories?q=...` content search instead. Content search is literal, not semantic identity proof.
- Resolver results are top-N without pagination; `ambiguity` is computed before truncation. Never infer uniqueness from the returned list length. Entity/people/memory lists expose pagination: incomplete or failed search cannot authorize a new identity.
- Entity creation has no request-id receipt contract. After an uncertain create, do not issue another POST or assume memory-write idempotency covers it. Cross-client create races need backend support; name uniqueness is not a safe substitute because different people can share a name.
- Alias CRUD exists but is not part of `/api/memories` or its source/change-history contract. Do not automatically write aliases merely because an identity was clarified.
- Protected self cannot be merged by the ordinary merge path. Repairing an existing self duplicate needs a separately authorized, supported self-preserving repair; never work around protection by removing the role.

## Write and history audit

Start from the router decision log (`~/.hermes/logs/context-router.jsonl`) or the write receipt, then read:

- the exact record (`/api/observations/{id}`, `/api/entity-facts/{id}`, `/api/edges/{id}` for `entity_edges:` refs) and its status;
- `GET /api/memory-changes?record_ref=<type:id>&limit=50&offset=0` and `GET /api/memory-changes/{change_id}` for lineage;
- `GET /api/episodes/{source_episode_id}` for the human source author/excerpt; the history `actor` is the writer, not the speaker.

Interpretation:

- a 200 receipt plus a readable active record means saved; there is no review stage;
- `superseded`/`deleted` old records are history after correct/reattribute/retract, not data loss;
- 409 means conflict (same request ID with a changed body, stale or non-current target, or `memory_change_required` for a legacy PATCH/DELETE), 422 validation, 404 missing target; none of these is a pending review;
- missing context can also be ambiguous identity, the router not reaching Kinlayer, or an API/runtime problem; verify each layer.

Migrated history has `change_kind: migrate` with writer `system`. Legacy candidates remain readable for history; a new memory never needs one.

## Classifier failures before any write

When router decisions show `llm_classifier_error`, trace the classifier's effective provider/model separately from the conversational model. Inspect the request-format contract before blaming Kinlayer or replaying writes: `PluginLlm` translates `json_mode=True` without a schema into `json_object`, while some providers accept only `json_schema`. Reproduce with synthetic text and the provider's local request validator, with network dispatch and persistence disabled.

Use the plugin-owned auxiliary slot `auxiliary.personal_context_router_classifier` for claim-extraction provider, model, and `reasoning_effort`, not semantic person identity. Leave legacy `runtime_context_router.classifier.provider/model` empty to let the slot resolve. The router's classifier timeout overrides that slot timeout. A fresh-process check does not activate changed code in a long-lived Gateway; require authorized activation and native route evidence before claiming recovery.

## Legacy compatibility jobs

Curation, reconciliation, and enrichment remain compatibility/history interfaces. They are not prerequisites for new memories and must not become a new approval loop. Never use the curation CLI as a read-only probe: even shadow mode can persist runs. Do not reserialize or re-sign historical source-pack, reconciliation, or import payloads under the new envelope; their digests stay as recorded.

## User-facing and repair boundary

Give a natural summary of the supported identity/relationship/situation context and why it matters; show IDs, statuses, or endpoint names only when debugging is requested. An audit is read-only: no resend, restart, router patch, or correction without separate authorization and its own readback.

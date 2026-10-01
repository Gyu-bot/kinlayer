# Periodic Relationship Curation Cycle — Implementation Plan

> Sensitivity is retired. See [retirement and compatibility contract](../specs/sensitivity-retirement.md).

**Status:** Repository Phases 1-4 implemented; Phase 5 adapter handoff ready
**Approved by user:** 2026-08-24
**Execution branch:** `codex/kinlayer-curation-cycle`
**Source baseline:** `origin/main` at `1ff177c`

## 1. Goal

Add a separate post-ingestion curation stage that periodically revisits pending relationship-memory candidates, reads only their bounded user-authored evidence and relevant canonical person context, removes duplication and ambiguity, and promotes safe consolidated results into canonical Kinlayer records.

This is a two-pass memory design:

```text
conversation turn
→ fast post-turn extraction
→ pending candidates

periodic curation cycle
→ group and compare related candidates
→ bounded source review
→ structured curation decisions
→ deterministic validation and execution
→ canonical promotion or unresolved pending state
```

The feature borrows only the concept of a separate “dreaming” or consolidation stage. It does **not** copy Honcho’s formal-logic, representation, induction, abduction, peer-card, or model-routing algorithms.

## 2. User-facing outcome

The user should not have to review every candidate individually. Most low-risk, well-grounded observations about an already resolved person should be consolidated and promoted automatically during a periodic curation cycle. Only ambiguous identity, structural relationship changes, sensitive profile facts, conflicting records, and other high-risk cases should remain for explicit review.

The cycle must also prevent the failure modes already observed in dogfood usage:

- duplicate `new_entity` candidates for the same unresolved name;
- a one-character spelling variant becoming a separate person without review;
- honorific role labels such as “executive” or “team lead” becoming person entities;
- one observation mixing different people or unrelated causes;
- multiple near-identical observations becoming duplicate canonical records;
- transient follow-up state being promoted as a timeless fact;
- a successful schema validation being mistaken for canonical acceptance;
- an accept attempt being reported as successful without `canonical_record_ref` and record/card readback.

Public tests and documentation must use synthetic names and examples. Do not publish real third-party names or private relationship details.

## 3. Architectural boundary

### Kinlayer owns

- candidate, evidence, episode, and canonical-record storage;
- bounded curation source-pack construction;
- curation run and decision persistence;
- ontology and deterministic validation;
- allow/deny policy for automatic execution;
- candidate consolidation and canonical writes;
- transactional state transitions;
- idempotency, audit, readback, and recovery;
- provisional pending-context output contracts.

### Hermes or another external agent adapter owns

- deciding when to invoke an LLM curator;
- passing the bounded source pack to the model;
- producing a structured curation plan that matches Kinlayer’s schema;
- scheduling periodic runs;
- performing targeted session lookup only when a source pack explicitly reports insufficient or ambiguous evidence.

### Kinlayer core must not

- embed a provider-specific LLM client or API key;
- scan arbitrary Hermes sessions or raw transcript databases;
- run open-ended personhood or relationship-relevance classification over unbounded text;
- accept assistant messages, tool output, retrieved memory, prompts, logs, or summaries as evidence;
- let an LLM directly mutate canonical tables;
- expose full raw prompts, full provider responses, full conversation bodies, secrets, or unbounded logs in curation records.

The external curator proposes a plan. Kinlayer remains the deterministic authority that decides whether each proposed action is executable.

## 4. Input model and bounded evidence

Pending candidates are the incremental change feed. The normal cycle must not rescan all sessions.

A curation source pack may contain only:

- pending candidate IDs and typed payloads;
- candidate confidence, status, and suggested action;
- candidate evidence IDs;
- bounded user-authored evidence excerpts;
- episode IDs, source refs, body hashes, actor, source type, and recorded timestamps;
- the target entity’s canonical context card or a compact projection of it;
- related pending candidates for the same resolved entity or normalized unresolved name;
- deterministic validation warnings and normalizations;
- exact duplicate or conflict signals computed from canonical records and other candidates.

Candidate payloads in a source pack are typed, allowlisted, bounded projections rather than raw DB
JSON. Unknown/raw keys are removed fail-closed; reserved raw prompt/provider/session/transcript/tool
markers and over-limit payloads are never returned. A non-empty submitted run must use the exact
server-returned start/completed cursor window and input count. Across the whole plan, every
server-derived candidate ID must appear exactly once: no omission, duplicate membership, or extra ID.
Multi-candidate consolidation remains valid when each source belongs only to that decision. Empty
source windows accept only zero decisions/count. Violations fail before run/decision persistence.

Replay preparation may include an optional tuple `upper_cursor`. Candidate selection stays lower
exclusive and becomes upper inclusive on `(created_at,id)`; limit and `has_more` must never inspect
beyond that tuple, including same-timestamp larger IDs. Run source-window validation uses the same
completed tuple upper bound.

To preserve cursor continuity across a proven empty replay interval, an APPLY run may set only the
allowlisted `diagnostics.replay_checkpoint=true` flag with zero decisions/count and complete ordered
start/end cursor pairs. Kinlayer must re-query `(start,end]`, reject if any pending candidate exists,
then create/evaluate/execute one empty completed run with exact DB readback and no canonical/candidate
mutation. Ordinary empty runs remain cursorless. Checkpoint validation never deletes or resolves data.

It must not include:

- full episode bodies;
- full Hermes sessions;
- assistant-authored replies;
- tool, subagent, process, or system output;
- Hindsight/Honcho/Kinlayer retrieved text as new evidence;
- model chain-of-thought or hidden reasoning;
- full provider requests or responses.

If source evidence is insufficient, the source pack should return a structured reason such as `needs_source_lookup`, `ambiguous_identity`, or `missing_temporal_scope`. A Hermes adapter may then perform a bounded lookup around the referenced source turn and submit only additional user-authored excerpts as a new episode/candidate or clarification input. It must not silently widen to an all-session sweep.

## 5. Curation modes

The capability needs three runtime modes:

```text
disabled  — no curation preparation or execution
shadow    — build packs and persist proposed decisions, but do not change candidate/canonical state
apply     — execute only decisions that pass the deterministic automatic-action policy
```

Requirements:

- Default configuration is `disabled` until deployment is explicitly activated.
- Implementation and tests must support all three modes.
- Starting implementation does not authorize applying a run against the live relationship database.
- A deployment may move from `shadow` to `apply` only after shadow output has been inspected against representative pending candidates.
- A policy-version change must be recorded on every run and must not reinterpret an already completed run silently.

Proposed effective setting:

```text
KINLAYER_CURATION_MODE=disabled|shadow|apply
```

Kinlayer does not schedule itself in the first implementation. Hermes or another adapter owns periodic invocation.

## 6. Persistent state

Add durable curation-run state rather than relying on agent conversation continuity.

### `curation_runs`

Minimum fields:

```text
id
mode
status                 pending | planning | ready | executing | completed | partial | failed
cursor_started_at
cursor_started_id
cursor_completed_at
cursor_completed_id
policy_version
planner_name nullable
planner_model nullable
planner_version nullable
input_candidate_count
planned_decision_count
executed_decision_count
blocked_decision_count
error_code nullable
diagnostics json
started_at
completed_at nullable
created_at
updated_at
```

### `curation_decisions`

Minimum fields:

```text
id
run_id
action
status                 proposed | allowed | blocked | executing | executed | failed
risk_level             low | medium | high
candidate_ids json
target_entity_id nullable
proposed_payload json
evidence_episode_ids json
reason_codes json
policy_version
idempotency_key unique
canonical_record_ref nullable
readback_status nullable
readback_summary json
api_error_code nullable
created_at
updated_at
executed_at nullable
```

Do not store raw session content or complete provider responses in either table.

`diagnostics` and `proposed_payload` reject reserved raw prompt/provider/session/transcript/tool keys
recursively and enforce JSON-only depth, node, string, and byte ceilings before persistence. Read
schemas apply the same checks so an unsafe legacy row fails closed rather than being returned.

A run is resumable from persisted decisions. Retrying the same decision must not create a second canonical record.

## 7. Curation action schema

The external curator submits structured decisions using an allowlisted action enum:

```text
accept_existing
edit_accept_existing
consolidate_accept
archive_exact_duplicate
mark_needs_clarification
defer
recommend_merge_review
recommend_conflict_review
```

Each decision must include:

```json
{
  "action": "consolidate_accept",
  "candidate_ids": ["candidate-a", "candidate-b"],
  "target_entity_id": "entity-id",
  "proposed_payload": {},
  "evidence_episode_ids": ["episode-a", "episode-b"],
  "reason_codes": ["same_subject", "overlapping_claims", "atomic_consolidation"],
  "risk_level": "low",
  "planner": {
    "name": "hermes-kinlayer-curator",
    "model": "provider/model",
    "version": "adapter-policy-version"
  }
}
```

The planner’s `risk_level`, confidence, and reason codes are advisory. Kinlayer must recompute executable eligibility from stored candidates, evidence, ontology, and canonical state.

## 8. Deterministic automatic-action policy

### Automatically executable in `apply` mode

Only existing-entity observations may be promoted automatically in the first release.

All conditions must hold:

- every source candidate is still `pending`;
- every source candidate has `candidate_type=observation`;
- all source candidates resolve to the same active target entity;
- the target is not protected self unless the existing candidate contract explicitly allows that observation;
- every evidence item references an existing episode;
- episode actor/source policy proves the excerpt is user-authored;
- evidence excerpts are bounded and non-empty;
- candidate and proposed payloads use active ontology values;
- no deterministic validation error or warning remains;
- proposed content is self-contained, atomic, and within the active content limit;
- related entity IDs resolve and remain active;
- point-in-time or temporary context has usable temporal scope;
- the observation type is auto-action-eligible;
- no canonical conflict is detected;
- no existing active canonical record is an exact normalized duplicate;
- the decision idempotency key has not already completed;
- post-write canonical integrity verification succeeds before commit.

For `claim_type=pattern`, automatic execution additionally requires evidence from at least two distinct episodes. A single source that verbally claims recurrence remains reviewable but is not automatically executed in the first release.

### Never automatically executable in the first release

- `new_entity`;
- `alias`;
- `profile_field`;
- `relationship_edge`;
- `merge`;
- `conflict`;
- `supersede`;
- candidates with unresolved or fuzzy identity;
- candidates whose target is an honorific role or generic profession rather than a resolved person;
- self-harm, medical, legal, financial-account, contact, credential, or similarly high-impact context;
- any decision that changes identity or graph structure;
- any decision that depends on assistant/tool/retrieved text as evidence;
- any action requiring an ontology value that is missing or ambiguous.

Contact-like content includes deterministic phone, email, address, and contact keywords/patterns and
is blocked regardless of planner-proposed wording. The check applies to both
stored source candidates and the proposed payload.

These decisions remain pending, become `needs_clarification`, or are surfaced as review recommendations. The LLM may recommend them but cannot cause direct canonical mutation.

### Duplicate handling

- Exact normalized duplicate pending candidates may be archived or marked superseded automatically only when the retained candidate and duplicate relationship are deterministic.
- Semantic similarity alone is not sufficient for automatic rejection or archival.
- Similar unresolved names must become identity-review recommendations, not automatic aliases or merges.

## 9. Consolidation semantics

`consolidate_accept` must not accept several overlapping candidates separately.

Implement one transactional service operation that:

1. locks all source candidates;
2. verifies they are pending and target the same active entity;
3. validates that the requested decision references only evidence already attached to those candidates;
4. validates the consolidated observation payload through the existing candidate and ontology guards;
5. creates one replacement/consolidated candidate or an equivalent auditable intermediate record;
6. copies all eligible candidate evidence links without copying full episode bodies;
7. writes one canonical observation;
8. sets its `source_candidate_id` to the consolidated review record;
9. marks source candidates as superseded or archived with a machine-readable resolution note;
10. records the new `canonical_record_ref` on the curation decision;
11. verifies the canonical row and its evidence links inside the transaction;
12. commits all state transitions atomically.

Any error before commit must roll back the canonical write and leave the original candidates pending. Do not leave partially resolved source candidates.

## 10. Readback and truthful completion

A curation decision is not complete merely because an accept method returned.

Before commit, verify:

- the canonical row exists;
- its record type matches the decision;
- its subject/target entity matches;
- expected candidate/episode evidence links exist;
- source candidate state transitions are internally consistent.

After commit, read back:

- the decision and run;
- all affected candidates;
- `canonical_record_ref`;
- the exact canonical record;
- the target person context card or compact canonical projection;
- processed duplicate/superseded candidate states.

If transactional verification fails, roll back and keep source candidates pending. If the transaction committed but an external post-commit readback is unavailable, record `verification_unknown`, do not claim full success, and make retry idempotently verify the committed state rather than writing again.

The first canonical transaction persists `canonical_record_ref` with `status=executing` and
`readback_status=verification_unknown`, never `verified`. A separate fresh-session reconciliation
must reload the run, decision, affected candidates, exact canonical content/evidence, and compact
target projection before setting `executed/verified`. Resume sees a persisted canonical ref and runs
reconciliation only. Manual and curation acceptance share the same locked candidate canonicalization
boundary; partial unique indexes on canonical `source_candidate_id` provide a second DB guard.

## 11. Provisional pending context

Add an explicit, opt-in provisional context section so recent useful candidates are not invisible before the next curation cycle.

Requirements:

- disabled by default in existing endpoints unless requested;
- returned separately from canonical context;
- labelled `provisional` or `unreviewed`;
- limited to recent `observation` candidates for an exactly resolved existing entity;
- bounded by age and item count;
- excluded when identity is ambiguous, candidate type is structural, or policy marks it unsafe;
- never presented as a confirmed fact;
- never reused as evidence for a new candidate or curation decision.

Update context-card/context-pack contracts without merging provisional entries into existing canonical fields.

## 12. API and CLI surface

Exact naming may be refined after inspecting router conventions, but the behavior must include:

### API

```text
POST /api/curation/source-packs
POST /api/curation/runs
GET  /api/curation/runs
GET  /api/curation/runs/{run_id}
POST /api/curation/runs/{run_id}/execute
POST /api/curation/runs/{run_id}/resume
```

Responsibilities:

- source-pack endpoint creates a bounded incremental pack and cursor;
- optional upper replay cursor is full-tuple inclusive and cannot widen `has_more`;
- run creation validates the structured plan but does not execute when mode is `shadow`;
- run creation requires exact-once candidate coverage of the complete server-derived source window;
- a verified empty APPLY replay checkpoint may advance cursor continuity only after a zero-row
  server requery of the exact tuple window;
- resume recovers persisted `pending|planning` plans to exact-readback `ready` state without
  candidate/canonical writes; this is allowed in either enabled server mode after policy-version
  validation, including stored shadow runs after a server move to apply;
- ready shadow resume is idempotent and non-writing;
- execute and apply-run resume from execution/reconciliation states apply only deterministic
  allowlisted decisions and require configured server mode `apply`;
- list/get surfaces counts, blocked reasons, canonical refs, and readback status without raw provider payloads.

### CLI

```text
kinlayer curation prepare --limit 50 --json
kinlayer curation plan-file <path> --mode shadow --json
kinlayer curation execute <run_id> --json
kinlayer curation resume <run_id> --json
kinlayer curation show <run_id> --json
```

The CLI must use the canonical API and preserve existing token/base-URL behavior.

## 13. Hermes adapter boundary

After the Kinlayer API and deterministic executor stabilize, add a profile-local Hermes adapter outside this repository.

The adapter should:

- request a source pack;
- call the configured Hermes model with a strict structured-output schema;
- submit the curation plan to Kinlayer;
- run in `shadow` or `apply` according to explicit configuration;
- use Kinlayer run cursors rather than cron continuity;
- schedule periodically without scanning all sessions;
- perform targeted `session_search` only after a structured source-pack insufficiency signal;
- submit only bounded user-authored excerpts as new evidence;
- report high-risk unresolved items separately;
- never store raw prompts/provider responses in Kinlayer or Hermes logs.

Hermes implementation and activation are separate state changes:

- code may be developed after the Kinlayer contract is stable;
- Gateway activation or restart requires separate authorization at deployment time;
- live `apply` mode requires a separate explicit activation decision after shadow verification.

## 14. Implementation sequence

### Phase 1 — Kinlayer curation contract and durable state

- Add curation schemas and action enums.
- Add `curation_runs` and `curation_decisions` migration/models.
- Add repository/service methods and API read surfaces.
- Implement idempotency and run cursor semantics.
- Keep execution in `shadow` only until the deterministic policy exists.

### Phase 2 — Bounded source packs and deterministic policy

- Build candidate-driven source packs.
- Add canonical duplicate/conflict checks.
- Add automatic-action eligibility evaluator with reason codes.
- Prove non-user evidence and unsupported candidate types are blocked.

### Phase 3 — Transactional executor and consolidation

- Refactor candidate canonical writes only as needed for caller-managed transactions.
- Implement accept/edit-accept reuse, `consolidate_accept`, duplicate archival, rollback, and readback.
- Ensure failure leaves source candidates pending.

### Phase 4 — CLI, provisional context, and docs

- Add CLI curation commands.
- Add opt-in provisional context output.
- Update active API/data/candidate/context/agent specs and smoke scripts.
- Keep Web scope to a read-only run/audit view only if needed for observability; do not make Web the only state-changing surface.

### Phase 5 — Hermes periodic curator

- Implement the profile-local Hermes adapter after Kinlayer API stabilization.
- Add bounded scheduling and structured model output.
- Run representative shadow cycles.
- Do not restart Gateway or enable live apply without separate deployment authorization.

## 15. Implementation checklist and acceptance criteria

### Task 1 — Durable run/decision model and schemas

- [x] Add migration and SQLAlchemy models.
- [x] Add Pydantic request/response schemas and enums.
- [x] Add idempotency uniqueness and status indexes.
- [x] Add migration/model tests.

Acceptance:

- empty DB migration succeeds;
- run/decision rows round-trip without raw prompt/provider fields;
- duplicate idempotency keys are rejected deterministically;
- invalid status/action transitions fail.

### Task 2 — Bounded source-pack builder

- [x] Select pending candidates incrementally from cursor.
- [x] Join bounded evidence and compact canonical target context.
- [x] Group by exact target entity or normalized unresolved identity key.
- [x] Enforce candidate/evidence/age/count budgets.
- [x] Return insufficiency and ambiguity reason codes.

Acceptance:

- no full episode body is returned;
- assistant/tool/system episodes are excluded as evidence;
- unrelated sessions are never scanned;
- cursor retry returns stable content;
- duplicate unresolved-name candidates appear in one review group without being merged automatically.

### Task 3 — Deterministic policy evaluator

- [x] Revalidate stored candidate payloads and ontology values.
- [x] Enforce automatic-action allowlist and hard denylist.
- [x] Detect exact canonical/pending duplicates.
- [x] Validate evidence ownership and temporal requirements.
- [x] Persist blocked reason codes.

Acceptance:

- only eligible existing-entity observations can become `allowed`;
- structural, identity, sensitive, warned, ambiguous, and conflicting candidates remain blocked;
- planner confidence alone cannot bypass a blocked condition;
- pattern auto-action requires at least two distinct episodes.

### Task 4 — Transactional executor and readback

- [x] Execute allowed accept/edit-accept decisions.
- [x] Implement transactional `consolidate_accept`.
- [x] Implement exact-duplicate archival/supersession.
- [x] Verify canonical/evidence/source-candidate state before commit.
- [x] Add idempotent post-commit readback and resume.

Acceptance:

- one consolidated canonical observation is created from overlapping candidates;
- all expected evidence links survive;
- source candidates transition consistently;
- injected failure rolls back and leaves sources pending;
- retry does not create a duplicate canonical record;
- completed decisions have verified `canonical_record_ref` and readback status.
- pending/planning resume reuses persisted decisions, performs no canonical write, and is idempotent;
- stale policy recovery fails before changing run, decision, candidate, or canonical state.

### Task 5 — API and CLI

- [x] Add source-pack, run, execute, resume, list, and get endpoints.
- [x] Add CLI prepare/plan-file/execute/resume/show commands.
- [x] Use durable redacted run/decision records as the curation audit trail.

Acceptance:

- API and CLI expose identical state;
- shadow mode never mutates candidate/canonical state;
- disabled mode rejects execution;
- apply mode executes only `allowed` decisions;
- enabled shadow/apply modes may perform non-writing pending/planning recovery, while apply execution
  states still require configured `apply`;
- error responses preserve candidate state and actionable reason codes.

### Task 6 — Provisional context

- [x] Add opt-in provisional context fields to context card/pack.
- [x] Enforce exact entity, observation-only, recency, count, and policy bounds.
- [x] Keep canonical and provisional content structurally separate.

Acceptance:

- existing clients remain compatible when provisional context is omitted;
- pending identity/structural/high-risk candidates never appear;
- provisional entries are visibly unreviewed;
- provisional text cannot become write evidence.

### Task 7 — Active docs, smoke coverage, and synthetic regressions

- [x] Update API, data-model, candidate-lifecycle, context-output, Web/CLI, and agent integration docs.
- [x] Update the Korean roadmap.
- [x] Add synthetic regressions for duplicate names, spelling variants, honorific roles, mixed-subject observations, transient facts, and failed readback.
- [x] Add API/CLI smoke coverage plus focused apply/block/rollback/resume/readback tests.

Acceptance:

- active docs match code and no longer describe curation as deferred;
- public fixtures contain no real person names or private relationship content;
- focused backend tests, lint, CLI tests, and smoke scripts pass;
- service-backed checks are reported honestly if unavailable.

### Task 8 — Hermes adapter handoff and implementation

- [x] Publish the exact source-pack and plan JSON schemas for external adapters.
- [x] Document targeted session-lookup fallback and evidence restrictions.
- [ ] Implement the profile-local Hermes adapter after Tasks 1–7 stabilize.
- [ ] Run shadow mode without live canonical writes.

Acceptance:

- Hermes can prepare and submit one valid shadow plan;
- no unbounded session sweep occurs;
- no raw provider request/response is persisted;
- Kinlayer rejects malformed or over-authorized plans;
- Gateway remains untouched until separate activation authorization.

## 16. Verification commands

Use focused checks during implementation, then one proportional regression pass.

```bash
uv run ruff check backend/src/kinlayer_backend backend/tests scripts
uv run pytest backend/tests
cd frontend && npm test -- --run
cd frontend && npm run build
```

Before Docker or service-backed smoke tests, inspect current Honcho and Kinlayer port bindings. Do not start or restart live services blindly.

Service-backed acceptance, when authorized and available:

```bash
python3 scripts/smoke-acceptance-api.py --api-url http://127.0.0.1:8765
KINLAYER_API_URL=http://127.0.0.1:8765 scripts/smoke-acceptance-cli.sh
```

## 17. Commit and delivery strategy

Use one implementation branch: `codex/kinlayer-curation-cycle`.

Recommended commits:

```text
feat(curation): add run and decision state
feat(curation): build bounded candidate source packs
feat(curation): enforce automatic-action policy
feat(curation): execute and verify canonical promotion
feat(cli): add curation workflow commands
feat(context): expose bounded provisional candidates
docs(curation): align contracts and adapter guidance
feat(hermes): add periodic curator adapter   # separate profile-local scope
```

Do not push implementation commits or activate live curation until Som has inspected the actual diff and verification evidence. The planning commit may be pushed so an external Codex session can start from the approved contract.

## 18. Success criteria

- Pending relationship candidates are periodically revisited without manual item-by-item review.
- The normal cycle is incremental and candidate-driven, not a full session sweep.
- Safe existing-entity observations can be consolidated and promoted in a separate curation stage.
- Identity, graph, sensitive, ambiguous, and conflicting changes remain review exceptions.
- Canonical writes retain bounded user-authored provenance.
- No curation decision is reported complete without verified canonical state and readback.
- Failed execution does not strand candidates in a false accepted state.
- Curation runs are resumable, idempotent, auditable, and free of raw prompts/transcripts/secrets.
- Hermes owns LLM interpretation and scheduling; Kinlayer owns deterministic policy and canonical state.

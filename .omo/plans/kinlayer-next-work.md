# kinlayer-next-work - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** This is the parent overview for the structured profile fact work set. Actual execution should start from the more specific slug plans in this directory.

**Why this approach:** Validation comes first because every promotion path eventually writes the same canonical fact records. Promotion creates a new structured record and deprecates the old loose one, so history stays inspectable.

**What it will NOT do:** It will not run LLM-based background curation, create a separate contacts table, or silently promote facts from keywords.

**Effort:** Large
**Risk:** Medium - multiple write paths must agree on validation, supersession, provenance, and UI behavior.
**Decisions to sanity-check:** `memo` stays general for now; promotion replaces-and-deprecates instead of mutating in place; phone validation uses a minimum seven-digit rule.

Your next move: choose and approve one of the child slug plans listed in the index. Full execution detail follows below.

---

> TL;DR (machine): Rollup only; actual implementation plans are `structured-profile-fact-validation.md`, `profile-fact-promotion-core.md`, `profile-fact-promotion-interfaces.md`, and `profile-fact-docs-smoke.md`.

## Scope
### Must have
- Treat `.omo/plans/index.md` and this file as the active execution-plan SSOT.
- Treat child slug plans as the implementation entrypoints.
- Preserve `docs/archive/planning/implementation-plan-2026-06-27.md` as historical input only.
- Validate supported structured profile fact content before canonical writes are committed.
- Validate through direct entity fact writes, candidate create/accept/edit-accept, explicit correction apply, and agent write validation.
- Add an explicit promotion path from a general `entity_facts` record to a structured `entity_facts` record.
- Support promotion through HTTP API, CLI, accepted `profile_field` candidates, and `/people/:id`.
- Preserve provenance and auditability by creating a replacement structured record and deprecating the original general record.
- Update active specs, agent guidance, and smoke checks in the same implementation package.

### Must NOT have (guardrails, anti-slop, scope boundaries)
- Do not treat `docs/archive/` as active SSOT.
- Do not implement optional LLM-assisted background curation.
- Do not add a separate contact/profile table.
- Do not silently auto-promote facts with keyword heuristics.
- Do not make Web-only state changes; the API is canonical.
- Do not invent ontology-controlled values.
- Do not store full raw conversation bodies.
- Do not start Docker, browser QA, or local services before inspecting current bindings.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: TDD for validation and promotion behavior; tests-after for docs/smoke script updates.
- Backend: `uv run pytest backend/tests/test_entities_api.py backend/tests/test_candidates_api.py backend/tests/test_corrections_api.py backend/tests/test_agent_write_filter.py`
- CLI/API smoke: inspect Docker bindings first, then run `scripts/smoke-slice0.sh`, `python3 scripts/load-acceptance-fixtures.py --api-url http://127.0.0.1:8765`, `python3 scripts/smoke-acceptance-api.py --api-url http://127.0.0.1:8765`, and `KINLAYER_API_URL=http://127.0.0.1:8765 scripts/smoke-acceptance-cli.sh` when service-backed verification is needed.
- Frontend: `cd frontend && npm test` and browser visual QA against `http://127.0.0.1:5173/people/<id>` after local binding inspection.
- Static checks: `uv run ruff check .`, `cd frontend && npm run build`, and Markdown/link sanity checks for touched docs.
- Evidence: one file per todo under `.omo/evidence/task-<N>-kinlayer-next-work.md`, plus final review notes under `.omo/evidence/final-kinlayer-next-work.md`.

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.
- Wave 1: backend validation and promotion contracts. Todos 1-3 can start with separate test files, then merge on the shared validator.
- Wave 2: CLI, Web, and docs/smoke updates after API contracts stabilize. Todos 4-6 can run mostly in parallel once todo 2 defines the endpoint shape.
- Wave 3: optional curation deferral and final verification. Todo 7 is documentation-only and can run with final checks.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | none | 2, 3, 4, 5, 6 | none |
| 2 | 1 | 4, 5, 6 | 3 after validator interface is stable |
| 3 | 1, 2 | 5, 6 | 4 |
| 4 | 2 | 6 | 3, 5 |
| 5 | 2 | 6 | 3, 4 |
| 6 | 1, 2, 3, 4, 5 | final verification | 7 |
| 7 | none | final verification | 4, 5, 6 |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [x] 1. Add structured profile fact validation at the canonical fact write boundary.
  What to do / Must NOT do: Add tests first for valid and invalid `email`, `phone`, `birth_date`, `legal_name`, `address`, `organization`, and `role` facts. Implement one shared validator called by `EntityService.create_fact` and `EntityService.patch_fact` when a supported structured `fact_type` is present. Keep general facts valid without type-specific validation. Do not infer structured types from content or add a new table.
  Parallelization: Wave 1 | Blocked by: none | Blocks: 2, 3, 4, 5, 6
  References (executor has NO interview context - be exhaustive): `backend/src/kinlayer_backend/services/entities.py:26-45`, `backend/src/kinlayer_backend/services/entities.py:119-130`, `docs/archive/planning/implementation-plan-2026-06-27.md:1535-1576`, `frontend/src/routes/PersonDetail.tsx:38-47`
  Acceptance criteria (agent-executable): `uv run pytest backend/tests/test_entities_api.py backend/tests/test_candidates_api.py backend/tests/test_corrections_api.py backend/tests/test_agent_write_filter.py -k "fact or profile or correction or agent_write"` passes and includes failing-before/fixed-after cases for each supported structured type.
  QA scenarios (name the exact tool + invocation): `uv run pytest backend/tests/test_entities_api.py -k structured_profile_fact_validation` covers accepted normalized values and rejected invalid values; evidence `.omo/evidence/task-1-kinlayer-next-work.md`.
  Commit: Y | `feat(profile-facts): validate structured fact content`

- [x] 2. Add explicit API/service promotion from general fact to structured fact.
  What to do / Must NOT do: Add a service method and API endpoint for promoting an existing general `entity_facts:<id>` record to a supported structured fact type. The operation must create a new structured fact, copy safe provenance/policy/confidence/evidence fields, set predictable `value.field_path`, and mark the original fact deprecated or superseded in the same transaction. Reject already deleted/deprecated sources, unsupported structured types, invalid content, wrong-entity requests, and repeated promotion attempts. Do not mutate the original fact in place.
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 3, 4, 5, 6
  References (executor has NO interview context - be exhaustive): `backend/src/kinlayer_backend/services/entities.py:119-135`, `backend/src/kinlayer_backend/models.py:347-348`, `docs/archive/planning/implementation-plan-2026-06-27.md:1323-1373`
  Acceptance criteria (agent-executable): targeted backend tests prove success returns old and new record refs, the source no longer appears as active general fact, the new record appears as active structured fact, and repeated promotion returns `409 conflict`.
  QA scenarios (name the exact tool + invocation): `uv run pytest backend/tests/test_entities_api.py -k promote` covers happy path, invalid content, unsupported type, stale/deprecated source, and idempotency; evidence `.omo/evidence/task-2-kinlayer-next-work.md`.
  Commit: Y | `feat(profile-facts): add explicit promotion API`

- [x] 3. Make candidate accept/edit-accept support referenced structured promotion.
  What to do / Must NOT do: Require candidate-originated promotion to use `candidate_type=profile_field` with `supersedes_record_ref="entity_facts:<source_id>"`. On accept/edit-accept, validate content through the shared validator, create the structured replacement, deprecate the source general fact, copy candidate evidence, and set `canonical_record_ref` to the new fact. Preserve current normal `profile_field` creation when no source ref is supplied. Do not allow an agent-originated candidate to bypass review or promote an unrelated source fact.
  Parallelization: Wave 1 | Blocked by: 1, 2 | Blocks: 5, 6
  References (executor has NO interview context - be exhaustive): `backend/src/kinlayer_backend/services/candidates.py:180-187`, `backend/src/kinlayer_backend/services/candidates.py:233-296`, `backend/src/kinlayer_backend/services/agent_write_filter.py:159-166`, `backend/src/kinlayer_backend/schemas/candidates.py:130-179`, `docs/specs/candidate-lifecycle-and-payload.md:144-145`, `docs/specs/candidate-lifecycle-and-payload.md:266`
  Acceptance criteria (agent-executable): `uv run pytest backend/tests/test_candidates_api.py backend/tests/test_agent_write_filter.py -k "profile_field or supersedes_record_ref or promote"` proves normal creation still works, referenced promotion works, invalid referenced promotion fails with `validation_error`, and review status transitions stay unchanged.
  QA scenarios (name the exact tool + invocation): `uv run pytest backend/tests/test_candidates_api.py -k profile_field_promotion` covers accept and edit-accept; evidence `.omo/evidence/task-3-kinlayer-next-work.md`.
  Commit: Y | `feat(candidates): support profile fact promotion review`

- [x] 4. Add a named CLI promotion command.
  What to do / Must NOT do: Add a `kinlayer fact promote <fact_id>` command with options for `--fact-type`, `--content`, `--field-path`, `--sensitivity`, `--ai-use-policy`, `--json`, and the active API URL/token behavior already used by existing commands. Default `field_path` to `profile.<fact_type>`. Emit old and new refs in text and JSON modes. Do not force users through raw JSON candidate files for a direct user promotion.
  Parallelization: Wave 2 | Blocked by: 2 | Blocks: 6
  References (executor has NO interview context - be exhaustive): `backend/src/kinlayer_backend/cli.py:519-573`, `docs/specs/cli-spec.md:181-190`, `docs/specs/cli-spec.md:306-315`, `docs/archive/planning/implementation-plan-2026-06-27.md:1366-1367`
  Acceptance criteria (agent-executable): CLI tests or smoke checks prove text and `--json` output include the replacement and source refs, invalid content surfaces the API `validation_error`, and existing candidate/correction commands still work.
  QA scenarios (name the exact tool + invocation): `KINLAYER_API_URL=http://127.0.0.1:8765 scripts/smoke-acceptance-cli.sh` after binding inspection, plus targeted unit coverage where available; evidence `.omo/evidence/task-4-kinlayer-next-work.md`.
  Commit: Y | `feat(cli): add fact promotion command`

- [x] 5. Add Web promotion workflow on person detail.
  What to do / Must NOT do: Add a promotion action for general profile facts on `/people/:id`. The operator chooses a structured fact type, confirms content and policy fields, sees validation errors from the API, and after success sees the fact move from General Profile Facts to Structured Profile Facts. Replace the hardcoded structured type boundary with a shared frontend constant or ontology-derived helper that matches backend-supported structured types. Do not create Web-only state or silently promote on edit.
  Parallelization: Wave 2 | Blocked by: 2 | Blocks: 6
  References (executor has NO interview context - be exhaustive): `frontend/src/routes/PersonDetail.tsx:38-47`, `frontend/src/routes/PersonDetail.tsx:232-248`, `frontend/src/routes/PersonDetail.tsx:287-289`, `frontend/src/routes/PersonDetail.tsx:421-454`, `frontend/src/api/client.ts`
  Acceptance criteria (agent-executable): `cd frontend && npm test -- --run` passes with tests for successful promotion and validation-error display; `cd frontend && npm run build` passes.
  QA scenarios (name the exact tool + invocation): after inspecting bindings and starting only needed Kinlayer services, use the Codex in-app browser at `http://127.0.0.1:5173/people/<id>` to perform a happy-path promotion and one invalid promotion; evidence `.omo/evidence/task-5-kinlayer-next-work.md`.
  Commit: Y | `feat(web): promote general profile facts`

- [x] 6. Update active specs, agent pack, and acceptance smoke coverage.
  What to do / Must NOT do: Update `docs/specs/api-spec.md`, `docs/specs/cli-spec.md`, `docs/specs/candidate-lifecycle-and-payload.md`, `docs/specs/web-ui-spec.md`, `docs/specs/data-model.md`, and `docs/agents/agent-write-instruction-pack.md` to describe structured validation, promotion semantics, supported types, candidate `supersedes_record_ref`, and CLI/Web behavior. Extend `scripts/smoke-acceptance-api.py` and `scripts/smoke-acceptance-cli.sh` to cover one successful promotion and one validation failure. Do not update archived docs except for the already archived source snapshot.
  Parallelization: Wave 2 | Blocked by: 1, 2, 3, 4, 5 | Blocks: final verification
  References (executor has NO interview context - be exhaustive): `docs/specs/api-spec.md:817`, `docs/specs/candidate-lifecycle-and-payload.md:266`, `docs/specs/cli-spec.md:181-190`, `docs/specs/cli-spec.md:306-315`, `docs/agents/agent-write-instruction-pack.md:480-486`, `scripts/smoke-acceptance-api.py:512-523`
  Acceptance criteria (agent-executable): `rg -n "promote|structured profile fact|supersedes_record_ref|validation_error" docs/specs docs/agents scripts` shows active coverage, and the smoke scripts pass in a service-backed run.
  QA scenarios (name the exact tool + invocation): run `python3 scripts/smoke-acceptance-api.py --api-url http://127.0.0.1:8765` and `KINLAYER_API_URL=http://127.0.0.1:8765 scripts/smoke-acceptance-cli.sh` after binding inspection; evidence `.omo/evidence/task-6-kinlayer-next-work.md`.
  Commit: Y | `docs(profile-facts): document promotion and validation`

- [x] 7. Keep optional LLM-assisted background curation parked behind a later plan.
  What to do / Must NOT do: Record T052 as deferred in the OMO index and Korean user roadmap. If the user later approves it, create a separate OMO plan that starts from active specs and code, not from archived task text. Do not implement curation queues, LLM calls, or new background jobs in this package.
  Parallelization: Wave 3 | Blocked by: none | Blocks: final verification
  References (executor has NO interview context - be exhaustive): `docs/archive/planning/implementation-plan-2026-06-27.md:1429-1479`, `.omo/plans/index.md`, `docs/kinlayer-roadmap.md`
  Acceptance criteria (agent-executable): `.omo/plans/index.md` and `docs/kinlayer-roadmap.md` both identify optional curation as deferred and not part of `kinlayer-next-work`.
  QA scenarios (name the exact tool + invocation): `rg -n "LLM-assisted|curation|보류|별도 OMO" .omo/plans docs/kinlayer-roadmap.md` confirms deferral language; evidence `.omo/evidence/task-7-kinlayer-next-work.md`.
  Commit: Y | `docs(planning): defer optional curation`

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [x] F1. Plan compliance audit
- [x] F2. Code quality review
- [x] F3. Real manual QA
- [x] F4. Scope fidelity

## Commit strategy
- Do not implement directly from this rollup unless the user explicitly asks to run the whole work set as one package.
- Use one branch for the full structured profile fact package unless the user asks to split it.
- Prefer the atomic commits listed in each todo during implementation.
- Do not commit, push, open a PR, merge, or update `main` without explicit user approval in that implementation turn.
- Before any implementation branch work, fetch the remote and base on latest `origin/main`.

## Success criteria
- The old root `implementation-plan.md` is no longer active and is preserved only under `docs/archive/planning/`.
- The OMO index and this plan are the active execution planning SSOT.
- Invalid structured fact content cannot be written through direct API, candidate review, correction apply, or agent write validation.
- A general profile fact can be promoted explicitly through API, CLI, candidate review, and Web.
- Promotion preserves auditability by replacing and deprecating rather than mutating in place.
- Active docs and smoke scripts match implemented behavior.
- Optional LLM-assisted curation remains deferred until a separate approval and plan.

# structured-profile-fact-validation - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** Structured profile facts will reject invalid values before they become canonical records, no matter which write path is used.

**Why this approach:** Validation belongs at the canonical fact service boundary first, then candidate/correction/agent paths can share it instead of duplicating rules.

**What it will NOT do:** It will not promote facts, add Web UI, run LLM extraction, or introduce a new profile/contact table.

**Effort:** Medium
**Risk:** Medium - validation touches several canonical write paths.
**Decisions to sanity-check:** `memo` stays general; `birth_date` requires `YYYY-MM-DD`; phone requires at least seven digits.

Your next move: approve this slug when you want validation implemented first. Full execution detail follows below.

---

> TL;DR (machine): Medium effort, medium risk; add shared structured fact content validation and tests across canonical write paths.

## Scope
### Must have
- Define the supported structured validation set: `legal_name`, `birth_date`, `phone`, `email`, `address`, `organization`, `role`.
- Validate structured content through `EntityService.create_fact` and `EntityService.patch_fact`.
- Ensure direct API, candidate accept/edit-accept, correction apply, and agent write validation cannot create invalid structured facts.
- Keep general facts and unsupported broad fact types working as general records.
- Return consistent `validation_error` API failures.
### Must NOT have (guardrails, anti-slop, scope boundaries)
- Do not infer structure from keywords.
- Do not add a new table or schema migration unless implementation proves existing columns cannot express the rules.
- Do not implement promotion UI/API in this slug.
- Do not treat archived docs as current SSOT.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: TDD with pytest for backend write paths.
- Backend: `uv run pytest backend/tests/test_entities_api.py backend/tests/test_candidates_api.py backend/tests/test_corrections_api.py backend/tests/test_agent_write_filter.py -k "fact or profile or correction or agent_write"`
- Static: `uv run ruff check backend/src/kinlayer_backend backend/tests`
- Evidence: `.omo/evidence/task-<N>-structured-profile-fact-validation.md`

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.
- Wave 1: characterize current write-path gaps with failing tests.
- Wave 2: implement shared validator and route alternate write paths through it.
- Wave 3: docs/spec sync for validation-only behavior.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | none | 2, 3 | none |
| 2 | 1 | 3, final verification | none |
| 3 | 2 | final verification | none |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [x] 1. Add tests that expose missing structured fact content validation.
  What to do / Must NOT do: Add failing tests for valid and invalid `email`, `phone`, `birth_date`, `legal_name`, `address`, `organization`, and `role` writes through direct fact API, accepted `profile_field` candidate, correction apply, and agent write validation. Do not change production code in this todo except fixtures/helpers required for tests.
  Parallelization: Wave 1 | Blocked by: none | Blocks: 2, 3
  References (executor has NO interview context - be exhaustive): `backend/src/kinlayer_backend/services/entities.py:119`, `backend/src/kinlayer_backend/services/candidates.py:274`, `backend/src/kinlayer_backend/services/agent_write_filter.py:159`, `docs/archive/planning/implementation-plan-2026-06-27.md:1535`
  Acceptance criteria (agent-executable): the new targeted tests fail before implementation for invalid structured content and pass for general facts that should remain valid.
  QA scenarios (name the exact tool + invocation): `uv run pytest backend/tests/test_entities_api.py backend/tests/test_candidates_api.py backend/tests/test_corrections_api.py backend/tests/test_agent_write_filter.py -k "structured_profile_fact_validation"`; evidence `.omo/evidence/task-1-structured-profile-fact-validation.md`.
  Commit: Y | `test(profile-facts): cover structured content validation`

- [x] 2. Implement shared structured fact validator.
  What to do / Must NOT do: Add one backend validator used by `EntityService.create_fact` and `EntityService.patch_fact`; normalize only conservative values such as trimmed email domain case and phone digit checks while preserving display content. Do not duplicate validation rules in every router.
  Parallelization: Wave 2 | Blocked by: 1 | Blocks: 3, final verification
  References (executor has NO interview context - be exhaustive): `backend/src/kinlayer_backend/services/entities.py:26`, `backend/src/kinlayer_backend/services/entities.py:119`, `backend/src/kinlayer_backend/services/entities.py:125`
  Acceptance criteria (agent-executable): `uv run pytest backend/tests/test_entities_api.py -k "structured_profile_fact_validation"` passes and invalid direct writes return `validation_error`.
  QA scenarios (name the exact tool + invocation): happy path creates `email`, `phone`, and `birth_date`; failure path rejects malformed values; evidence `.omo/evidence/task-2-structured-profile-fact-validation.md`.
  Commit: Y | `feat(profile-facts): validate structured fact content`

- [x] 3. Prove alternate write paths share the same validation.
  What to do / Must NOT do: Route or verify candidate accept/edit-accept, correction apply, and agent write validation through the shared rules. Do not add separate looser validation for agent-originated data.
  Parallelization: Wave 3 | Blocked by: 2 | Blocks: final verification
  References (executor has NO interview context - be exhaustive): `backend/src/kinlayer_backend/services/candidates.py:180`, `backend/src/kinlayer_backend/services/candidates.py:274`, `backend/src/kinlayer_backend/services/corrections.py`, `backend/src/kinlayer_backend/services/agent_write_filter.py:159`
  Acceptance criteria (agent-executable): `uv run pytest backend/tests/test_candidates_api.py backend/tests/test_corrections_api.py backend/tests/test_agent_write_filter.py -k "profile_field or structured or correction"` passes with invalid structured values blocked.
  QA scenarios (name the exact tool + invocation): candidate happy/failure, correction happy/failure, agent validate happy/failure; evidence `.omo/evidence/task-3-structured-profile-fact-validation.md`.
  Commit: Y | `fix(profile-facts): enforce validation on alternate writes`

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [x] F1. Plan compliance audit
- [x] F2. Code quality review
- [x] F3. Real manual QA
- [x] F4. Scope fidelity

## Commit strategy
- Keep this slug as the first implementation package.
- Do not commit, push, or open a PR unless the user explicitly asks in the implementation turn.

## Success criteria
- Invalid structured fact content is rejected across every canonical write path.
- General profile facts continue to work.
- Error responses are consistent and test-covered.

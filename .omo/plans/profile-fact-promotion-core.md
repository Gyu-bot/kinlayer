# profile-fact-promotion-core - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** A canonical API/service workflow can promote a general profile fact into a structured profile fact while preserving history.

**Why this approach:** Promotion should create a new structured record and deprecate the original general record, so provenance remains inspectable.

**What it will NOT do:** It will not add CLI/Web controls or background LLM curation.

**Effort:** Medium
**Risk:** Medium - promotion changes record lifecycle semantics.
**Decisions to sanity-check:** Repeated promotion returns conflict; candidate-originated promotion requires `supersedes_record_ref`.

Your next move: approve this slug after or alongside validation. Full execution detail follows below.

---

> TL;DR (machine): Medium effort, medium risk; add API/service and candidate-review promotion semantics.

## Scope
### Must have
- Add explicit API/service promotion for `entity_facts:<id>`.
- Create a new structured fact and deprecate/supersede the original general fact in one transaction.
- Reuse structured validation from `structured-profile-fact-validation.md`.
- Support `profile_field` candidate accept/edit-accept with `supersedes_record_ref`.
- Preserve evidence, policy, sensitivity, confidence, and canonical record refs where safe.
### Must NOT have (guardrails, anti-slop, scope boundaries)
- Do not mutate the original fact in place.
- Do not promote deleted/deprecated facts.
- Do not allow unrelated source/target entity promotion.
- Do not add CLI/Web behavior in this slug.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: TDD with backend pytest.
- Backend: `uv run pytest backend/tests/test_entities_api.py backend/tests/test_candidates_api.py -k "promote or profile_field"`
- Static: `uv run ruff check backend/src/kinlayer_backend backend/tests`
- Evidence: `.omo/evidence/task-<N>-profile-fact-promotion-core.md`

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.
- Wave 1: API/service promotion behavior.
- Wave 2: candidate review promotion behavior.
- Wave 3: lifecycle regression checks.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | structured-profile-fact-validation | 2, 3 | none |
| 2 | 1 | 3, final verification | none |
| 3 | 1, 2 | final verification | none |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [x] 1. Add API/service promotion from general fact to structured fact.
  What to do / Must NOT do: Implement a service method and route that accepts source fact id, structured `fact_type`, content/value, field path, sensitivity, and AI use policy. It must write a new active structured fact and mark the source fact deprecated/superseded in one transaction. Do not mutate the source content or type in place.
  Parallelization: Wave 1 | Blocked by: `structured-profile-fact-validation.md` | Blocks: 2, 3
  References (executor has NO interview context - be exhaustive): `backend/src/kinlayer_backend/services/entities.py:119`, `backend/src/kinlayer_backend/api/entities.py`, `backend/src/kinlayer_backend/models.py`, `docs/archive/planning/implementation-plan-2026-06-27.md:1323`
  Acceptance criteria (agent-executable): `uv run pytest backend/tests/test_entities_api.py -k promote` proves success returns source and replacement refs, active lists move the fact to structured, invalid content fails, and repeated promotion returns `409 conflict`.
  QA scenarios (name the exact tool + invocation): API happy promotion and stale source failure; evidence `.omo/evidence/task-1-profile-fact-promotion-core.md`.
  Commit: Y | `feat(profile-facts): add promotion service`

- [x] 2. Support candidate review promotion with `supersedes_record_ref`.
  What to do / Must NOT do: When a `profile_field` candidate has `supersedes_record_ref=entity_facts:<id>`, accept/edit-accept should call the same promotion service and set `canonical_record_ref` to the new fact. Normal `profile_field` candidates without a source ref must continue to create profile facts as before.
  Parallelization: Wave 2 | Blocked by: 1 | Blocks: 3
  References (executor has NO interview context - be exhaustive): `backend/src/kinlayer_backend/services/candidates.py:180`, `backend/src/kinlayer_backend/services/candidates.py:274`, `backend/src/kinlayer_backend/schemas/candidates.py:130`
  Acceptance criteria (agent-executable): `uv run pytest backend/tests/test_candidates_api.py -k "profile_field and promote"` covers accept, edit-accept, unrelated source rejection, and invalid structured content rejection.
  QA scenarios (name the exact tool + invocation): candidate happy promotion and candidate invalid source failure; evidence `.omo/evidence/task-2-profile-fact-promotion-core.md`.
  Commit: Y | `feat(candidates): promote profile facts from review`

- [x] 3. Protect lifecycle and provenance regressions.
  What to do / Must NOT do: Add assertions for evidence copying/linking, policy/sensitivity preservation, deprecated source exclusion from active views, and context-card consistency. Do not loosen existing deletion or correction semantics.
  Parallelization: Wave 3 | Blocked by: 1, 2 | Blocks: final verification
  References (executor has NO interview context - be exhaustive): `backend/src/kinlayer_backend/services/context.py`, `backend/src/kinlayer_backend/repositories/entities.py`, `backend/src/kinlayer_backend/services/candidates.py:294`
  Acceptance criteria (agent-executable): `uv run pytest backend/tests/test_entities_api.py backend/tests/test_candidates_api.py backend/tests/test_context_api.py -k "promote or context or evidence"` passes.
  QA scenarios (name the exact tool + invocation): context card includes replacement and excludes deprecated source; evidence `.omo/evidence/task-3-profile-fact-promotion-core.md`.
  Commit: Y | `test(profile-facts): lock promotion lifecycle`

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [x] F1. Plan compliance audit
- [x] F2. Code quality review
- [x] F3. Real manual QA
- [x] F4. Scope fidelity

## Commit strategy
- Implement after `structured-profile-fact-validation.md`, or in the same branch after validation tests are green.

## Success criteria
- API/service promotion works transactionally.
- Candidate review promotion works without bypassing review.
- Provenance and active record views remain consistent.

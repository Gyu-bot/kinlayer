# profile-fact-docs-smoke - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** Active specs, agent guidance, and acceptance smoke scripts will match the structured profile fact validation and promotion behavior.

**Why this approach:** The contract docs and smoke scripts should move with behavior so future agents do not re-infer old task text from the archive.

**What it will NOT do:** It will not edit archived docs except to reference them as history.

**Effort:** Short
**Risk:** Low - documentation and smoke changes depend on implemented API shape.
**Decisions to sanity-check:** Keep `.omo/plans` as plan SSOT; keep `docs/kinlayer-roadmap.md` human-facing.

Your next move: approve this slug with or after implementation. Full execution detail follows below.

---

> TL;DR (machine): Short, low risk; update specs, agent docs, smoke scripts, and roadmap links after behavior lands.

## Scope
### Must have
- Update active API, CLI, candidate lifecycle, Web UI, data model, and agent write docs.
- Update acceptance smoke scripts for one promotion success and one validation failure.
- Update `.omo/plans/index.md` statuses as implementation progresses.
- Keep `docs/kinlayer-roadmap.md` aligned with user-facing directions.
### Must NOT have (guardrails, anti-slop, scope boundaries)
- Do not update archived planning docs for active truth.
- Do not document behavior before verifying implemented API/CLI names.
- Do not add broad new roadmap items outside structured profile facts.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: tests-after; docs follow implemented behavior.
- Smoke: `python3 scripts/smoke-acceptance-api.py --api-url http://127.0.0.1:8765` and `KINLAYER_API_URL=http://127.0.0.1:8765 scripts/smoke-acceptance-cli.sh` after service binding inspection.
- Static docs: `rg -n "promote|structured profile fact|supersedes_record_ref|validation_error" docs/specs docs/agents scripts .omo/plans docs/kinlayer-roadmap.md`
- Evidence: `.omo/evidence/task-<N>-profile-fact-docs-smoke.md`

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.
- Wave 1: active specs and agent pack.
- Wave 2: acceptance smoke scripts and OMO/user roadmap status.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | validation/core/interfaces implementation | 2, final verification | none |
| 2 | 1 | final verification | none |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [x] 1. Update active specs and agent guidance.
  What to do / Must NOT do: Update active docs with supported structured types, validation rules, promotion API/CLI/Web behavior, candidate `supersedes_record_ref`, provenance semantics, and deferred LLM curation boundary. Do not rely on archived task numbers as live contract.
  Parallelization: Wave 1 | Blocked by: behavior implementation | Blocks: 2
  References (executor has NO interview context - be exhaustive): `docs/specs/api-spec.md`, `docs/specs/cli-spec.md`, `docs/specs/candidate-lifecycle-and-payload.md`, `docs/specs/web-ui-spec.md`, `docs/specs/data-model.md`, `docs/agents/agent-write-instruction-pack.md`
  Acceptance criteria (agent-executable): `rg -n "promote|structured profile fact|supersedes_record_ref|validation_error" docs/specs docs/agents` shows current behavior documented.
  QA scenarios (name the exact tool + invocation): markdown fence and trailing-whitespace checks for touched docs; evidence `.omo/evidence/task-1-profile-fact-docs-smoke.md`.
  Commit: Y | `docs(profile-facts): document validation and promotion`

- [x] 2. Extend smoke scripts and plan status.
  What to do / Must NOT do: Add API/CLI smoke coverage for one successful promotion and one validation failure. Update `.omo/plans/index.md` and `docs/kinlayer-roadmap.md` status only after implementation evidence exists.
  Parallelization: Wave 2 | Blocked by: 1 | Blocks: final verification
  References (executor has NO interview context - be exhaustive): `scripts/smoke-acceptance-api.py`, `scripts/smoke-acceptance-cli.sh`, `.omo/plans/index.md`, `docs/kinlayer-roadmap.md`
  Acceptance criteria (agent-executable): service-backed API and CLI smoke scripts pass after binding inspection, or blockers are recorded with exact failure output.
  QA scenarios (name the exact tool + invocation): `python3 scripts/smoke-acceptance-api.py --api-url http://127.0.0.1:8765`; `KINLAYER_API_URL=http://127.0.0.1:8765 scripts/smoke-acceptance-cli.sh`; evidence `.omo/evidence/task-2-profile-fact-docs-smoke.md`.
  Commit: Y | `test(profile-facts): smoke validation and promotion`

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [x] F1. Plan compliance audit
- [x] F2. Code quality review
- [x] F3. Real manual QA
- [x] F4. Scope fidelity

## Commit strategy
- Run this after behavior slugs, or in the same implementation branch as final docs/smoke cleanup.

## Success criteria
- Active docs and smoke scripts match actual behavior.
- Archived docs remain historical only.
- OMO index and Korean roadmap point at the implemented plan set.

# profile-fact-promotion-interfaces - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** Operators can promote profile facts from the CLI and Web UI using the canonical promotion API.

**Why this approach:** Interfaces should stay thin and call the API, so promotion behavior is not duplicated in the client.

**What it will NOT do:** It will not create Web-only state or raw JSON-only operator flows.

**Effort:** Medium
**Risk:** Medium - Web and CLI must expose validation errors consistently.
**Decisions to sanity-check:** CLI command name is `kinlayer fact promote`; Web shows promotion only for general facts.

Your next move: approve this slug after the core API exists. Full execution detail follows below.

---

> TL;DR (machine): Medium effort, medium risk; add CLI and Web promotion surfaces backed by API.

## Scope
### Must have
- Add `kinlayer fact promote <fact_id>` with text and JSON output.
- Add API client support for fact promotion.
- Add `/people/:id` promotion workflow for general profile facts.
- Display API validation errors in CLI and Web.
- Verify frontend tests/build and CLI smoke.
### Must NOT have (guardrails, anti-slop, scope boundaries)
- Do not implement promotion logic in the frontend.
- Do not add hidden browser-only state.
- Do not start local browser/server checks before inspecting current ports.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: tests-after for CLI surface, TDD/RTL for Web behavior if current tests cover the route.
- CLI: targeted CLI tests or `KINLAYER_API_URL=http://127.0.0.1:8765 scripts/smoke-acceptance-cli.sh`
- Frontend: `cd frontend && npm test -- --run` and `cd frontend && npm run build`
- Evidence: `.omo/evidence/task-<N>-profile-fact-promotion-interfaces.md`

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.
- Wave 1: CLI command and API client wrapper.
- Wave 2: Web promotion UI.
- Wave 3: interface QA and browser verification.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | profile-fact-promotion-core | 2, 3 | none |
| 2 | profile-fact-promotion-core | 3 | 1 |
| 3 | 1, 2 | final verification | none |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [x] 1. Add CLI promotion command.
  What to do / Must NOT do: Add `kinlayer fact promote <fact_id> --fact-type ... --content ... --field-path ... --sensitivity ... --ai-use-policy ... --json`. Reuse existing API URL/token request helpers. Do not require raw JSON files for the direct user promotion path.
  Parallelization: Wave 1 | Blocked by: `profile-fact-promotion-core.md` | Blocks: 3
  References (executor has NO interview context - be exhaustive): `backend/src/kinlayer_backend/cli.py:519`, `docs/specs/cli-spec.md:181`, `docs/archive/planning/implementation-plan-2026-06-27.md:1366`
  Acceptance criteria (agent-executable): CLI happy path outputs source and replacement refs; invalid content surfaces `validation_error`.
  QA scenarios (name the exact tool + invocation): `KINLAYER_API_URL=http://127.0.0.1:8765 scripts/smoke-acceptance-cli.sh` after binding inspection; evidence `.omo/evidence/task-1-profile-fact-promotion-interfaces.md`.
  Commit: Y | `feat(cli): add fact promotion command`

- [x] 2. Add Web promotion workflow.
  What to do / Must NOT do: Add API client method and `/people/:id` UI flow to promote only general facts. Show a small review form with structured fact type, content, sensitivity, and AI use policy. Refresh data after success and show API validation errors after failure.
  Parallelization: Wave 2 | Blocked by: `profile-fact-promotion-core.md` | Blocks: 3
  References (executor has NO interview context - be exhaustive): `frontend/src/routes/PersonDetail.tsx:38`, `frontend/src/routes/PersonDetail.tsx:421`, `frontend/src/api/client.ts`
  Acceptance criteria (agent-executable): `cd frontend && npm test -- --run` covers successful promotion and validation-error display; `cd frontend && npm run build` passes.
  QA scenarios (name the exact tool + invocation): browser happy and invalid promotion on `http://127.0.0.1:5173/people/<id>` after port inspection; evidence `.omo/evidence/task-2-profile-fact-promotion-interfaces.md`.
  Commit: Y | `feat(web): promote general profile facts`

- [x] 3. Run interface regression checks.
  What to do / Must NOT do: Verify CLI, Web tests, frontend build, and one browser/manual QA path. Do not skip browser QA if Web changed and a local app can be started safely.
  Parallelization: Wave 3 | Blocked by: 1, 2 | Blocks: final verification
  References (executor has NO interview context - be exhaustive): `AGENTS.md`, `frontend/package.json`, `scripts/smoke-acceptance-cli.sh`
  Acceptance criteria (agent-executable): CLI smoke, frontend tests, frontend build, and browser QA evidence all exist or a concrete blocker is recorded.
  QA scenarios (name the exact tool + invocation): `docker ps --format '{{.Names}} {{.Ports}}'` before service/browser checks; evidence `.omo/evidence/task-3-profile-fact-promotion-interfaces.md`.
  Commit: Y | `test(profile-facts): verify promotion interfaces`

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [x] F1. Plan compliance audit
- [x] F2. Code quality review
- [x] F3. Real manual QA
- [x] F4. Scope fidelity

## Commit strategy
- Implement after `profile-fact-promotion-core.md`.

## Success criteria
- CLI and Web expose the canonical promotion flow.
- Validation errors are visible to operators.
- Frontend and CLI verification pass.

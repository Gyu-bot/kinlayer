# Optional Background Curation Plan-Only Boundary

## TL;DR
> Summary:      This slug is complete as a deferred plan-only boundary. Optional LLM-assisted background curation is not implemented now and must not be executed from this file.
> Deliverables:
> - A completed OMO boundary refresh for optional background curation.
> - Active-code/spec references that future planning must re-check before any implementation.
> - Explicit LLM, privacy, evidence, candidate-review, and approval guardrails.
> Effort:       Quick
> Risk:         Medium - the current artifact is low-risk, but future curation would cross LLM and privacy trust boundaries.

## Scope
### Must have
- Preserve the deferred status from `.omo/plans/index.md:24-28`: optional background curation depends on structured profile fact work and requires a separate plan/approval pass.
- Treat current Todo 1 as the only work in this slug: refresh and verify the plan boundary, not implementation.
- State that future curation requires explicit user approval and a new or reopened OMO implementation plan before any backend, frontend, docs-product, schema, queue, job, or provider work.
- Ground future planning in active code and specs, including the current candidate review, deterministic agent-write validation, correction, evidence, and privacy boundaries.
- Keep future LLM-assisted curation disabled by default, review-only, and candidate-producing only.
- Require future work to use bounded user-authored evidence excerpts, source refs, body hashes, and metadata; never full raw conversation bodies, full raw prompts, full provider responses, bearer tokens, API keys, raw request bodies, or unbounded logs.

### Must NOT have (guardrails, anti-slop, scope boundaries)
- Do not implement curation now.
- Do not leave unchecked implementation tasks in this plan that would cause `start-work` to keep trying to build curation now.
- Do not add backend, frontend, migration, smoke, product docs, provider SDK, queue, scheduler, or network behavior from this slug.
- Do not bypass candidate review by auto-accepting candidates, directly applying corrections, directly promoting facts, or directly mutating canonical records.
- Do not use assistant messages, tool output, retrieved context packs/cards, system/developer/skill prompts, logs, compacted summaries, previous memory output, or agent-generated interpretations as evidence.
- Do not let an LLM invent ontology values, fact types, relation types, candidate types, source types, `ai_use_policy`, sensitivity values, or semantic rewrites.
- Do not treat archived `T052` or archived implementation-plan text as active SSOT when it conflicts with live code or active specs.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: none for product code; this is a plan-only boundary repair.
- QA policy: verify by static plan/evidence checks and diff-scope checks only.
- Evidence: `.omo/evidence/task-1-optional-background-curation.md`
- Required commands:
  - `git diff --check -- .omo/plans/optional-background-curation.md .omo/evidence/task-1-optional-background-curation.md .omo/start-work/ledger.jsonl`
  - `rg -n "LLM|privacy|full raw|explicit user approval|separate.*plan|disabled|review" .omo/plans/optional-background-curation.md .omo/evidence/task-1-optional-background-curation.md`
  - `git diff --name-only`

## Execution strategy
### Parallel execution waves
> This slug has no active implementation waves. Future implementation is intentionally not decomposed here.

Wave 1 (plan-only, complete):
- Task 1: Refresh optional curation deferred boundary and verify no implementation tasks remain.

Future work gate:
- A user must explicitly approve optional curation work.
- A planner must create a new OMO implementation plan or reopen this plan with fresh approval.
- That future plan must re-check active code/specs before any implementation task is added.

Critical path: Task 1 only

### Dependency matrix
| Task | Depends on | Blocks | Can parallelize with |
|------|------------|--------|----------------------|
| 1    | none       | future curation planning only | none |

## Todos
> Implementation + Test = ONE task. Never separate.
> This plan currently has no implementation tasks.

- [x] 1. Refresh active optional curation boundary

  What to do: Re-read active plan index, rollup, roadmap, active specs, and live code boundaries. Keep optional LLM-assisted background curation parked as deferred, plan-only work. Record that future curation requires explicit user approval and a separate plan before implementation. Remove unchecked implementation backlog tasks from this file.
  Must NOT do: Do not add or request backend/frontend/docs product behavior, migrations, queues, LLM calls, provider SDKs, jobs, schedulers, curation APIs, curation CLI commands, curation UI, or smoke scripts in this slug.

  Parallelization: Can parallel: NO | Wave 1 | Blocks: [future curation planning only] | Blocked by: []

  References (executor has NO interview context - be exhaustive):
  - Pattern:  `.omo/plans/index.md:24-28` - optional background curation is Deferred and requires a separate plan/approval pass.
  - Pattern:  `.omo/plans/kinlayer-next-work.md:123-129` - current structured profile package must keep optional curation parked and must not implement curation queues, LLM calls, or new background jobs.
  - Pattern:  `docs/kinlayer-roadmap.md:129-138` - Korean roadmap says optional LLM-assisted background curation is out of current scope and requires a separate OMO plan.
  - Pattern:  `docs/specs/candidate-lifecycle-and-payload.md:13-30` - candidate review is the control boundary; Kinlayer does not run post-turn LLM extraction and rejects non-user-authored evidence sources.
  - Pattern:  `docs/specs/api-spec.md:34-44` - core API rules exclude post-turn LLM extraction and require current-turn user-authored evidence.
  - Pattern:  `docs/specs/api-spec.md:576-598` - episodes are provenance units with metadata, bounded excerpts, and hashes; full raw body storage is out of MVP.
  - Pattern:  `docs/specs/api-spec.md:657-708` - `/api/agent-writes/validate` is deterministic, dry-run, no-persistence validation with no LLM calls or semantic rewriting.
  - Pattern:  `docs/specs/api-spec.md:733-790` - candidate accept/edit-accept are explicit review actions that write canonical records.
  - Pattern:  `docs/specs/api-spec.md:826-876` - direct correction apply requires explicit user correction; agent-inferred corrections must use candidates instead.
  - Pattern:  `docs/specs/data-model.md:377-411` - episodes store bounded excerpts and hashes; `full_body` and full raw body storage are out of MVP.
  - Pattern:  `docs/specs/data-model.md:638-668` - audit rows must not store full prompts, bearer tokens, API keys, raw transcripts, or unbounded request bodies.
  - Pattern:  `docs/agents/agent-write-instruction-pack.md:172-195` - evidence must be small, attributable, user-authored, and minimum necessary.
  - Pattern:  `docs/agents/agent-write-instruction-pack.md:935-943` - agents must fetch ontology values, use bounded evidence, and no-write/clarify when entity/record/ontology values are ambiguous.
  - Pattern:  `docs/agents/agent-write-instruction-pack.md:963-965` - future LLM-assisted background curation may exist later only as optional review-only workflow, never direct canonical writes, and still through deterministic validation.
  - API/Type: `backend/src/kinlayer_backend/api/agent_writes.py:17-19` - active dry-run validation endpoint delegates to `AgentWriteFilter`.
  - API/Type: `backend/src/kinlayer_backend/services/agent_write_filter.py:80-125` - validation/enforcement returns structured accepted payload or diagnostics.
  - API/Type: `backend/src/kinlayer_backend/services/agent_write_filter.py:135-245` - candidate/correction validation checks controlled values, evidence, entity refs, profile fields, and record refs.
  - API/Type: `backend/src/kinlayer_backend/api/candidates.py:111-168` - accept/edit-accept are explicit candidate review endpoints.
  - API/Type: `backend/src/kinlayer_backend/services/candidates.py:144-190` - accept/edit-accept write canonical records only through candidate review.
  - API/Type: `backend/src/kinlayer_backend/services/corrections.py:32-51` - direct correction apply requires `user_explicit` and writes correction evidence before superseding records.
  - API/Type: `backend/src/kinlayer_backend/services/structured_facts.py:89-111` - active structured fact validators define supported structured fact types.
  - External: none - provider-specific LLM documentation is intentionally absent until the user explicitly approves a provider-selection planning pass.

  Acceptance criteria (agent-executable only):
  - [x] `rg -n "LLM|privacy|full raw|explicit user approval|separate.*plan|disabled|review" .omo/plans/optional-background-curation.md .omo/evidence/task-1-optional-background-curation.md` returns the current LLM/privacy guardrails and approval boundary.
  - [x] `rg -n "^- \\[ \\] [0-9]+\\.|^- Task [2-9]:|^- Task 10:|^  Commit: YES" .omo/plans/optional-background-curation.md` returns no unchecked implementation tasks or implementation commit instructions.
  - [x] `git diff --name-only` for this lane is reviewed and any product/backend/frontend/docs implementation files are confirmed unrelated to this plan-only repair.
  - [x] `git diff --check -- .omo/plans/optional-background-curation.md .omo/evidence/task-1-optional-background-curation.md .omo/start-work/ledger.jsonl` exits 0.

  QA scenarios (MANDATORY - task incomplete without these):
  ```
  Scenario: deferred curation boundary is discoverable
    Tool:     bash
    Steps:    rg -n "LLM|privacy|full raw|explicit user approval|separate.*plan|disabled|review" .omo/plans/optional-background-curation.md .omo/evidence/task-1-optional-background-curation.md
    Expected: Output includes disabled-by-default, review-only, no full raw storage, explicit user approval, and separate plan guardrails.
    Evidence: .omo/evidence/task-1-optional-background-curation.md

  Scenario: no active implementation backlog remains
    Tool:     bash
    Steps:    rg -n "^- \\[ \\] [0-9]+\\.|^- Task [2-9]:|^- Task 10:|^  Commit: YES" .omo/plans/optional-background-curation.md
    Expected: Command exits with no matches; this plan has only completed plan-boundary Todo 1 and no implementation commit instructions.
    Evidence: .omo/evidence/task-1-optional-background-curation.md

  Scenario: lane diff scope remains plan-only for optional curation
    Tool:     bash
    Steps:    git diff --name-only
    Expected: The optional-curation repair changes only `.omo/plans/optional-background-curation.md`, `.omo/evidence/task-1-optional-background-curation.md`, and `.omo/start-work/ledger.jsonl`; any backend/frontend/product docs files in the shared worktree are residual from other lanes and not part of this repair.
    Evidence: .omo/evidence/task-1-optional-background-curation.md
  ```

  Commit: NO | Message: `n/a` | Files: [`.omo/plans/optional-background-curation.md`, `.omo/evidence/task-1-optional-background-curation.md`, `.omo/start-work/ledger.jsonl`]

## Final verification wave
> Plan-only verification is complete for this boundary repair. No product code review, browser QA, or runtime service QA is applicable because this slug intentionally implements nothing.
- [x] F1. Plan compliance audit - Task 1 is complete, no unchecked implementation tasks remain, and acceptance criteria are static/agent-executable.
- [x] F2. Code quality review - not applicable to product code; diff check covers the plan/evidence/ledger artifacts.
- [x] F3. Real manual QA - not applicable to UI/runtime behavior; static QA scenarios are recorded in Task 1 evidence.
- [x] F4. Scope fidelity - this plan remains deferred, requires explicit user approval and a separate plan before curation, and ships no backend/frontend/docs product behavior.

## Commit strategy
- No commit, push, PR, or merge for this plan-only repair.
- If optional curation is later approved, create or reopen an OMO implementation plan first, then use that future plan's commit strategy.
- A future implementation plan must stay provider-neutral until a provider-selection approval gate captures official provider docs and privacy/security constraints.

## Success criteria
- This plan contains no unchecked implementation backlog tasks.
- Future optional LLM-assisted background curation is explicitly blocked on user approval plus a separate plan.
- Active code/spec references and LLM/privacy guardrails are present.
- Verification confirms the optional-curation repair did not add product/backend/frontend/docs implementation files.

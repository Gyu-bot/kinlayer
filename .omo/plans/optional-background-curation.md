# optional-background-curation - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** A parked future plan boundary for optional LLM-assisted background curation, without implementing it now.

**Why this approach:** Curation depends on validated structured facts and needs its own approval because it introduces LLM behavior and background workflow risk.

**What it will NOT do:** It will not add LLM calls, queues, jobs, schema changes, or curation UI in the current package.

**Effort:** Deferred
**Risk:** High - future work would touch extraction trust boundaries and background processing.
**Decisions to sanity-check:** This remains parked until the user explicitly asks for a separate plan.

Your next move: do nothing now; request this slug later if curation becomes a priority. Full execution detail follows below.

---

> TL;DR (machine): Deferred; document curation boundary only, no implementation.

## Scope
### Must have
- Keep optional LLM-assisted curation out of the structured profile fact implementation.
- Require a separate OMO planning pass before implementation.
- Re-ground in active specs/code when revived.
### Must NOT have (guardrails, anti-slop, scope boundaries)
- Do not implement LLM extraction, classification, queues, jobs, or curation UI now.
- Do not store full raw conversation bodies.
- Do not bypass explicit user review for inferred memory.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: none now; this is deferred planning boundary only.
- Evidence: `.omo/evidence/task-<N>-optional-background-curation.md` only when this slug is revived.

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.
- No implementation waves in this package.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | structured fact implementation complete | future curation planning | none |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [ ] 1. Re-plan optional curation only after explicit user approval.
  What to do / Must NOT do: When revived, inspect current structured fact behavior, agent write boundaries, candidate review flow, and privacy constraints before proposing curation. Do not start from archived T052 text alone.
  Parallelization: Deferred | Blocked by: structured profile fact implementation complete and user approval | Blocks: future curation work
  References (executor has NO interview context - be exhaustive): `docs/archive/planning/implementation-plan-2026-06-27.md:1429`, `docs/agents/agent-write-instruction-pack.md`, `.omo/plans/index.md`
  Acceptance criteria (agent-executable): a new or updated OMO plan exists with active-code references and explicit LLM/privacy guardrails.
  QA scenarios (name the exact tool + invocation): future plan review only; evidence `.omo/evidence/task-1-optional-background-curation.md`.
  Commit: N | deferred boundary only

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [ ] F1. Plan compliance audit
- [ ] F2. Code quality review
- [ ] F3. Real manual QA
- [ ] F4. Scope fidelity

## Commit strategy
- No implementation commit from this slug until separately approved.

## Success criteria
- Optional curation remains clearly out of scope for the current structured fact work.
- Future revival requires a separate plan and approval.

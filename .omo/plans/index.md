# Kinlayer OMO Plan Index

**Status:** Active planning SSOT
**Updated:** 2026-07-04

## Source of Truth Rules

- Active execution plans live under `.omo/plans/`.
- Planning drafts, assumptions, and approval gates live under `.omo/drafts/`.
- Historical planning snapshots under `docs/archive/` are reference-only and excluded from SSOT.
- The archived root roadmap is preserved at `docs/archive/planning/implementation-plan-2026-06-27.md`.
- The Korean user-facing roadmap is `docs/kinlayer-roadmap.md`; it explains how to direct implementation, while this directory remains the execution SSOT.

## Active Plans

| Plan | Status | Purpose | Approval |
| --- | --- | --- | --- |
| `kinlayer-next-work.md` | Rollup | Parent overview for the next structured profile fact work set. Use the slug plans below for actual execution. | Not directly implemented |
| `structured-profile-fact-validation.md` | Completed | Shared structured profile fact content validation across direct, candidate, correction, and agent write paths is implemented and gate-reviewed. | Confirmed by `.omo/evidence/combined-profile-facts-validation-core-gate-review.md` |
| `profile-fact-promotion-core.md` | Completed | Canonical API/service promotion and candidate review promotion semantics are implemented and gate-reviewed. | Confirmed by `.omo/evidence/profile-fact-promotion-core-done-claim.md` and follow-up gates |
| `profile-fact-promotion-interfaces.md` | Completed | CLI and Web promotion surfaces backed by the canonical API are implemented and gate-reviewed. | Confirmed by `.omo/evidence/profile-fact-promotion-interfaces-final-gate-rerun.md` |
| `profile-fact-docs-smoke.md` | Completed for docs/script coverage; service-backed smoke blocked/not run | Active specs and agent guidance are updated; API/CLI acceptance smoke scripts now cover promotion success and `validation_error` failure, but service-backed API/CLI smoke execution remains blocked by the local environment and is not claimed as run. | Confirmed by `.omo/evidence/profile-fact-docs-smoke-final-gate-rerun.md` and blocker details in `.omo/evidence/task-2-profile-fact-docs-smoke.md` |

## Deferred Plans

| Topic | Status | Reason |
| --- | --- | --- |
| `optional-background-curation.md` | Deferred, plan-only gate confirmed | Depends on the structured profile fact workflow and needs a separate implementation approval pass. |

## Operating Notes

- Start future implementation from the most specific slug plan, then update evidence under `.omo/evidence/`.
- If code or active specs conflict with archived planning text, trust live code and active specs first.
- Do not revive task numbers from the archived roadmap unless they help explain provenance; execution should follow OMO todo batches.

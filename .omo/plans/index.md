# Kinlayer OMO Plan Index

**Status:** Active planning SSOT
**Updated:** 2026-06-27

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
| `structured-profile-fact-validation.md` | Awaiting user approval | Add shared structured profile fact content validation across direct, candidate, correction, and agent write paths. | Required before implementation |
| `profile-fact-promotion-core.md` | Awaiting user approval | Add canonical API/service promotion and candidate review promotion semantics. | Required before implementation |
| `profile-fact-promotion-interfaces.md` | Awaiting user approval | Add CLI and Web promotion surfaces backed by the canonical API. | Required before implementation |
| `profile-fact-docs-smoke.md` | Awaiting user approval | Update active specs, agent guidance, smoke scripts, and plan status after behavior lands. | Required before implementation |

## Deferred Plans

| Topic | Status | Reason |
| --- | --- | --- |
| `optional-background-curation.md` | Deferred | Depends on the structured profile fact workflow and needs a separate plan/approval pass. |

## Operating Notes

- Start future implementation from the most specific slug plan, then update evidence under `.omo/evidence/`.
- If code or active specs conflict with archived planning text, trust live code and active specs first.
- Do not revive task numbers from the archived roadmap unless they help explain provenance; execution should follow OMO todo batches.

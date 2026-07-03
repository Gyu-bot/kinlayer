---
slug: kinlayer-next-work
status: awaiting-approval
intent: clear
pending-action: user approval before implementation
approach: Replace the archived task-number roadmap with an OMO SSOT plan focused on the remaining structured profile-fact work.
---

# Draft: kinlayer-next-work

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
<!-- id | outcome (one line) | status: active|deferred | evidence path -->
| id | outcome | status | evidence path |
| --- | --- | --- | --- |
| A | Structured profile fact content validation blocks invalid canonical writes through every write path. | active | `.omo/evidence/task-1-kinlayer-next-work.md` |
| B | General profile facts can be explicitly promoted to structured facts through API and CLI while preserving auditability. | active | `.omo/evidence/task-2-kinlayer-next-work.md` |
| C | Candidate accept/edit-accept can perform referenced structured promotion without bypassing review. | active | `.omo/evidence/task-3-kinlayer-next-work.md` |
| D | Web person detail exposes an operator promotion workflow backed by the API. | active | `.omo/evidence/task-4-kinlayer-next-work.md` |
| E | Specs, agent pack, and smoke scripts describe and verify the new behavior. | active | `.omo/evidence/task-5-kinlayer-next-work.md` |
| F | Optional LLM-assisted background curation remains parked until structured facts are complete and approved. | deferred | `.omo/evidence/task-6-kinlayer-next-work.md` |

## Open assumptions (announced defaults)
<!-- Record any default you adopt instead of asking, so the user can veto it at the gate. -->
<!-- assumption | adopted default | rationale | reversible? -->
| assumption | adopted default | rationale | reversible? |
| --- | --- | --- | --- |
| Structured profile fact validation | Validate only an explicit supported structured subset: `legal_name`, `birth_date`, `phone`, `email`, `address`, `organization`, `role`. Leave `memo` and broad context facts general unless later promoted by product decision. | Current UI already separates structured/general facts, but broad ontology values are not all machine-validated. Narrow validation avoids inventing semantics. | Yes |
| Promotion semantics | Create a replacement structured `entity_facts` row and deprecate/supersede the source general fact; do not mutate the source in place. | Preserves provenance and avoids silent history loss. | Yes |
| Candidate-originated promotion | Require `profile_field` candidate with `supersedes_record_ref` pointing at `entity_facts:<source_id>`. | Uses an existing candidate field and keeps review explicit. | Yes |
| CLI command | Add a named `kinlayer fact promote` command instead of requiring raw JSON candidate submission. | Gives the user and agents a stable operator command. | Yes |
| Email validation | Accept one trimmed plain email value, normalize only whitespace and lowercase domain, reject display names, comma-separated values, and missing domain. | Avoids overfitting while blocking common invalid data. | Yes |
| Phone validation | Require at least seven digits after stripping common punctuation, preserve entered display text in `content`. | Useful minimum without forcing an international formatting library in this pass. | Yes |
| Date validation | `birth_date` accepts ISO `YYYY-MM-DD` only. | Keeps comparison/query semantics deterministic. | Yes |

## Findings (cited - path:lines)
- `docs/archive/planning/implementation-plan-2026-06-27.md:128-147` recorded T050 and T054 as the current Ready queue, with T052 still Backlog.
- `docs/archive/planning/implementation-plan-2026-06-27.md:1323-1373` defined explicit structured profile fact promotion as the remaining workflow gap.
- `docs/archive/planning/implementation-plan-2026-06-27.md:1535-1576` defined structured profile fact content validation and called out alternate write paths.
- `backend/src/kinlayer_backend/services/entities.py:119-123` is the shared canonical fact creation choke point.
- `backend/src/kinlayer_backend/services/candidates.py:180-187` validates `profile_field` candidate registry values before review.
- `backend/src/kinlayer_backend/services/candidates.py:274-296` writes accepted `profile_field` candidates into `entity_facts`.
- `backend/src/kinlayer_backend/services/agent_write_filter.py:159-166` validates agent `profile_field` writes before they enter review.
- `frontend/src/routes/PersonDetail.tsx:38-47` currently uses a local structured fact type list.
- `frontend/src/routes/PersonDetail.tsx:287-289` separates structured and general profile facts client-side.
- `frontend/src/routes/PersonDetail.tsx:421-454` displays structured and general fact sections but has no promotion action.
- `backend/src/kinlayer_backend/cli.py:519-559` provides candidate edit-accept and supersede commands, but no direct fact promotion command.

## Decisions (with rationale)
- `.omo/plans/index.md` becomes the active planning SSOT. The old root `implementation-plan.md` is archived as historical input only.
- `kinlayer-next-work` merges old T050 and T054 into one executable plan because promotion without content validation would create unsafe alternate write paths.
- T052 optional LLM-assisted background curation is intentionally not part of the implementation package. It depends on the structured fact workflow and needs a separate approval pass.
- The first implementation wave should be tests-first because validation and promotion touch multiple write paths and can regress silently.
- All behavior-changing API/CLI/Web work must update active specs and smoke scripts in the same implementation package.

## Scope IN
- Structured profile fact content validation across direct fact API, candidate accept/edit-accept, correction apply, and agent write validation.
- Explicit general-to-structured fact promotion through API, CLI, candidate review, and Web person detail.
- Provenance-preserving replacement semantics for promoted records.
- Active docs/spec updates and smoke coverage for the new behavior.
- Korean user-facing roadmap at `docs/kinlayer-roadmap.md` for directing future implementation.

## Scope OUT (Must NOT have)
- No use of `docs/archive/` as active SSOT.
- No LLM extraction, classification, or background curation in this package.
- No new profile/contact table.
- No silent keyword-based auto-promotion.
- No Web-only state changes; the HTTP API remains canonical.
- No invented ontology-controlled values.
- No Docker/browser/service changes unless the implementation or QA step first inspects current bindings.

## Open questions
- Should `memo` be treated as structured or general after the first validation pass? Default: general.
- Should phone validation later adopt a region-aware library? Default: not in this package.

## Approval gate
status: awaiting-approval
<!-- When exploration is exhausted and unknowns are answered, set status: awaiting-approval. -->
<!-- That durable record is the loop guard: on a later turn read it and resume at the gate instead of re-running exploration. -->

# Docs Knowledge

## OVERVIEW

Active documentation lives in `specs/`, `agents/`, and `plans/`; `archive/` is historical
and excluded from SSOT.

## STRUCTURE

```text
docs/
├── specs/    # active product/API/model/CLI/Web contracts
├── agents/   # active agent integration and write guidance
├── plans/    # active implementation plans
├── kinlayer-roadmap.md  # Korean user-facing implementation guide
└── archive/  # ignored for SSOT; do not update for active truth
```

## WHERE TO LOOK

| Task | Location | Notes |
| --- | --- | --- |
| Product/API/model contract | `specs/` | More specific specs win over PRD prose |
| Agent write behavior | `agents/agent-write-instruction-pack.md` | Operational instruction pack |
| Integration ideas | `agents/agent-integration-notes.md` | Adapter/runtime planning, not core extraction |
| Active write contract | `plans/save-first-memory-schema.md` | Immediate writes, schema and live data conversion |
| Next implementation | `plans/runtime-correctness.md` | RC-A safety fixes first; later writer/merge and retrieval stages |
| Shared target contract | `plans/record-lifecycle-contract.md` | Planned identity, cross-kind lineage, provenance, validity and version compatibility |
| Model integrity | `plans/data-model-integrity.md` | Shared writer/lineage before relationship constraints; assessment split with observation phase 2 |
| Automatic indexing | `plans/embedding-auto-index.md` | Post-commit indexing, recovery and unchanged concurrency tokens |
| Observation ontology | `plans/observation-ontology-v1.md` | Planned `observation-v1` after common integrity foundation |
| Review evidence | `verification/schema-logic-review-2026-10-22.md` | Observed failures, reproduction and verification limits; not implementation SSOT |
| Frontend | `plans/frontend-rebuild.md` | Approved replacement, implemented in `frontend/src/v2/` |
| Relationship ontology | `plans/relationship-ontology.md` | `relationship-v1` and relationship profile axes |
| User-facing roadmap | `kinlayer-roadmap.md` | Korean guide for directing future implementation |
| Documentation map | `README.md` | Active/archive boundaries |
| Historical context | `archive/` | Reference only; never active SSOT |

## CONVENTIONS

- Keep root docs sparse. Do not add new root Markdown unless explicitly approved.
- Active execution plans live in `plans/`; specs and roadmap may summarize or
  link them but must not fork a second execution SSOT.
- Keep plans and completion criteria independent of retired agent plugins. Private local
  evidence belongs outside the checkout; maintained, shareable verification belongs in
  `verification/`. Historical task ledgers are not current execution instructions.
- The archived `implementation-plan.md` snapshot is historical only.
- When docs and code conflict, inspect live routers/services/schemas first, then
  update active docs.
- `docs/archive/` can contain stale self-described active documents; ignore them
  for current truth.

## ANTI-PATTERNS

- Editing archived planning docs to make current behavior true.
- Duplicating long behavioral rules across many docs. Put the canonical rule in
  the nearest active spec or agent pack, then link.
- Treating PRD examples as schema truth when a specific spec or code path differs.

# Docs Knowledge

## OVERVIEW

Active documentation lives in `specs/` and `agents/`; `archive/` is historical
and excluded from SSOT.

## STRUCTURE

```text
docs/
├── specs/    # active product/API/model/CLI/Web contracts
├── agents/   # active agent integration and write guidance
├── kinlayer-roadmap.md  # Korean user-facing implementation guide
└── archive/  # ignored for SSOT; do not update for active truth
```

## WHERE TO LOOK

| Task | Location | Notes |
| --- | --- | --- |
| Product/API/model contract | `specs/` | More specific specs win over PRD prose |
| Agent write behavior | `agents/agent-write-instruction-pack.md` | Operational instruction pack |
| Integration ideas | `agents/agent-integration-notes.md` | Adapter/runtime planning, not core extraction |
| User-facing roadmap | `kinlayer-roadmap.md` | Korean guide for directing future implementation |
| Documentation map | `README.md` | Active/archive boundaries |
| Historical context | `archive/` | Reference only; never active SSOT |

## CONVENTIONS

- Keep root docs sparse. Do not add new root Markdown unless explicitly approved.
- Active execution plans live in `.omo/plans/`; docs may summarize or link them
  but must not fork a second execution SSOT.
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

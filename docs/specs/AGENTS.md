# Specs Knowledge

## OVERVIEW

Active product contracts; keep them synchronized with live code, not archive docs.

## WHERE TO LOOK

| Task | Location | Notes |
| --- | --- | --- |
| Product boundary | `prd.md` | Principles and scope; not endpoint detail |
| HTTP API | `api-spec.md` | Endpoint contract; verify routers/services |
| Data model | `data-model.md` | Tables/statuses/evidence/audit model |
| CLI | `cli-spec.md` | Verify against `backend/src/kinlayer_backend/cli.py` |
| Web | `web-ui-spec.md` | Verify against `frontend/src/App.tsx` and routes |
| Retrieval/context | `context-output-contract.md` | Verify against context/retrieval services |
| Candidate lifecycle | `candidate-lifecycle-and-payload.md` | Verify against candidate schemas/service |
| Ontology | `ontology-design.md` | Verify against `services/ontology.py` |
| Acceptance | `acceptance-scenarios.md` | Keep journey-level; fixture detail belongs in scripts/tests |

## CONVENTIONS

- HTTP API remains the canonical capability layer; CLI/Web are clients.
- Postgres is the canonical store; models/migrations own table truth.
- Use exact canonical values from `services/ontology.py` or ontology API responses.
- `merge` candidate accept is implemented; `conflict` and `supersede` are review
  payloads until specific execution workflows exist.
- `GET /api/system/config` examples must show effective non-secret config, not
  desired defaults.

## ANTI-PATTERNS

- Static enum lists that drift from `REGISTRY_SEEDS`.
- Saying `accept` writes canonical records for every candidate type.
- Describing `kinlayer init` as local config creation; current behavior prepares
  protected self through the API.
- Adding future endpoints as if they already exist.

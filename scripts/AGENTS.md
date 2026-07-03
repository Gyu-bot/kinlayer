# Scripts Knowledge

## OVERVIEW

Operational checks, fixture loaders, API/CLI acceptance, and smoke scripts.

## WHERE TO LOOK

| Task | Location | Notes |
| --- | --- | --- |
| Full local smoke | `smoke-slice0.sh` | Docker, health, CLI status, ruff, pytest, frontend build |
| API acceptance | `load-acceptance-fixtures.py`, `smoke-acceptance-api.py` | Uses running API on `127.0.0.1:8765` |
| CLI acceptance | `smoke-acceptance-cli.sh` | Uses `KINLAYER_API_URL` and optional token |
| Web manual QA | `web-smoke-checklist.md` | Route-by-route checklist |

## CONVENTIONS

- Before starting Docker or network checks, inspect current bindings first.
- Preserve honcho containers and ports: `8000`, `6379`, `5432`.
- Scripts should target Kinlayer defaults unless args/env override: API `8765`,
  Web `5173`, Postgres host `127.0.0.1:15432`.
- Keep smoke scripts explicit and bounded. They should fail loudly on real
  contract drift.
- Prefer maintained CLI JSON commands and smoke scripts over ad-hoc HTTP snippets
  for repeatable inspection.

## ANTI-PATTERNS

- Starting containers before checking port state.
- Writing ad-hoc curl snippets into docs when a maintained script/helper exists.
- Mixing destructive cleanup into smoke scripts.
- Assuming token mode is always on. Token checks are conditional on
  `KINLAYER_API_TOKEN`.

## COMMANDS

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
scripts/smoke-slice0.sh
python3 scripts/load-acceptance-fixtures.py --api-url http://127.0.0.1:8765
python3 scripts/smoke-acceptance-api.py --api-url http://127.0.0.1:8765
KINLAYER_API_URL=http://127.0.0.1:8765 scripts/smoke-acceptance-cli.sh
uv run kinlayer status --json
```

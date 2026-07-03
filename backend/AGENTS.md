# Backend Knowledge

## OVERVIEW

FastAPI, Typer, SQLAlchemy, Alembic, and service-layer domain behavior live here.

## STRUCTURE

```text
backend/
├── src/kinlayer_backend/
│   ├── api/          # FastAPI routers
│   ├── schemas/      # Pydantic request/response contracts
│   ├── services/     # domain behavior and side effects
│   ├── repositories/ # DB access helpers
│   ├── models.py     # SQLAlchemy table/model truth
│   ├── main.py       # app factory and router/auth wiring
│   ├── cli.py        # Typer CLI
│   └── config.py     # KINLAYER_* settings
├── alembic/          # migrations
└── tests/            # backend/API/CLI tests
```

## WHERE TO LOOK

| Task | Location | Notes |
| --- | --- | --- |
| Add/change endpoint | `src/kinlayer_backend/api/` | Routers call services; no Web-only writes |
| Request/response shape | `src/kinlayer_backend/schemas/` | Keep docs/specs aligned |
| State transitions | `src/kinlayer_backend/services/` | Candidate, correction, retrieval, ontology side effects |
| DB schema | `src/kinlayer_backend/models.py`, `alembic/versions/` | Migration plus model must match |
| CLI behavior | `src/kinlayer_backend/cli.py` | CLI wraps API/debug workflows |
| Tests | `tests/` | SQLite TestClient by default; Postgres checked by smoke |

## CONVENTIONS

- `main.py:create_app()` is the HTTP entrypoint truth: routers, token middleware,
  CORS, startup ontology seed, protected self bootstrap.
- `config.py:Settings` owns env defaults. Compose may override bind host and DB URL.
- `services/ontology.py:REGISTRY_SEEDS` owns controlled values. Docs must not invent
  `relation_type`, `observation_type`, `fact_type`, or policy values.
- `created_by = ai_agent` candidate/correction payloads must pass `AgentWriteFilter`
  before persistence.
- Candidate `accept` writes canonical records for `new_entity`, `alias`,
  `profile_field`, `relationship_edge`, `observation`, and `merge`.
- Candidate `conflict` and `supersede` validate as payloads but do not have direct
  canonical accept execution yet.
- Explicit correction apply requires `correction_source.user_explicit = true` and
  exactly one supported `old_record_ref`.

## ANTI-PATTERNS

- Updating schemas without router/service tests.
- Treating doc examples as current enum truth when `ontology.py` differs.
- Hard-deleting relationship context by default; use soft delete, archive,
  deprecate, supersede, or merge semantics.
- Adding LLM extraction/classification to Kinlayer core. Agents/adapters decide
  extraction; Kinlayer validates and stores.

## COMMANDS

```bash
uv run ruff check backend/src/kinlayer_backend backend/tests scripts
uv run pytest backend/tests
uv run alembic upgrade head
uv run kinlayer status --json
```

# Kinlayer

Kinlayer is a local-first relationship context layer for AI agents. It stores, reviews, retrieves, and explains person/relationship context while keeping the user in control of trusted and surfaceable context.

## Local Defaults

- API: `http://127.0.0.1:8765`
- Web: `http://127.0.0.1:5173`
- Postgres host port: `127.0.0.1:15432`

These ports intentionally avoid active honcho bindings on this machine.

## Setup

```bash
uv sync
cd frontend
npm install
```

## Run

Check Docker port state before starting containers:

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
docker compose up -d
```

Run migrations:

```bash
uv run alembic upgrade head
```

Check the API and CLI:

```bash
curl http://127.0.0.1:8765/api/system/health
uv run kinlayer status
```

Run the frontend locally without Docker:

```bash
cd frontend
npm run dev
```

## Primary Documents

- `prd.md` — product requirements and principles.
- `implementation-plan.md` — canonical vertical-slice implementation baseline.
- `initial-implementation-plan.md` — historical initial draft.
- `api-spec.md` — HTTP API contract.
- `data-model.md` — canonical data model.
- `cli-spec.md` — CLI contract.
- `web-ui-spec.md` — Web UI behavior.
- `acceptance-scenarios.md` — MVP acceptance scenarios.
- `interview-ledger.md` — decision ledger and rationale.

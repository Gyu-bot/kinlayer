# PROJECT KNOWLEDGE BASE

**Snapshot:** 2026-06-27
**Commit:** fb9a20a
**Branch:** codex/omo-agents

## OVERVIEW

Kinlayer is a local-first relationship context layer for AI agents. The stack is
FastAPI, SQLAlchemy, Alembic, Typer, Postgres/pgvector, React/Vite, and Docker
Compose.

## STRUCTURE

```text
kinlayer/
├── backend/        # FastAPI, CLI, DB models, migrations, tests
├── frontend/       # React/Vite control plane
├── scripts/        # smoke, fixture, deterministic agent/debug helpers
├── docs/
│   ├── specs/      # active product/API/model/CLI/Web contracts
│   ├── agents/     # active agent integration/write guidance
│   ├── kinlayer-roadmap.md  # Korean user-facing implementation roadmap
│   └── archive/    # historical only; not SSOT
├── .omo/
│   ├── plans/      # active execution-plan SSOT
│   └── drafts/     # plan assumptions, topology ledgers, approval gates
├── README.md       # product overview and local runbook
└── AGENTS.md       # this router and project-wide operating rules
```

## WHERE TO LOOK

| Task | Location | Notes |
| --- | --- | --- |
| Runtime/API truth | `backend/src/kinlayer_backend/main.py` | FastAPI app, routers, token middleware, startup seeds |
| CLI truth | `backend/src/kinlayer_backend/cli.py` | Typer commands; `pyproject.toml` only wires the console script |
| Config truth | `backend/src/kinlayer_backend/config.py`, `docker-compose.yml`, `.env.example` | Env names, defaults, ports |
| Domain/model truth | `backend/src/kinlayer_backend/models.py` | Tables, statuses, evidence/audit rows |
| Ontology truth | `backend/src/kinlayer_backend/services/ontology.py` | `REGISTRY_SEEDS`, allowed edge/observation types |
| Candidate/correction truth | `backend/src/kinlayer_backend/services/candidates.py`, `services/corrections.py` | Accept/edit-accept/correction side effects |
| Web routes | `frontend/src/App.tsx`, `frontend/src/routes/` | Browser-visible surfaces |
| Product specs | `docs/specs/` | Active contracts; update when behavior changes |
| Agent write rules | `docs/agents/agent-write-instruction-pack.md` | Required for agent/adapter writes |
| Execution plans | `.omo/plans/` | Active planning SSOT; `index.md` routes current packages |
| User roadmap | `docs/kinlayer-roadmap.md` | Korean planning guide for requesting implementation |
| Validation | `scripts/smoke-slice0.sh`, `backend/tests/`, `frontend/package.json` | No GitHub Actions currently |

## CODE MAP

| Symbol | Type | Location | Role |
| --- | --- | --- | --- |
| `create_app` | function | `backend/src/kinlayer_backend/main.py` | App factory, router registration, auth middleware |
| `Settings` | class | `backend/src/kinlayer_backend/config.py` | Effective `KINLAYER_*` config |
| `REGISTRY_SEEDS` | constant | `backend/src/kinlayer_backend/services/ontology.py` | Seed registry values; use code before docs |
| `CandidateService` | class | `backend/src/kinlayer_backend/services/candidates.py` | Candidate lifecycle and canonical writes |
| `AgentWriteFilter` | class | `backend/src/kinlayer_backend/services/agent_write_filter.py` | Deterministic gate for `created_by = ai_agent` writes |
| `CorrectionService` | class | `backend/src/kinlayer_backend/services/corrections.py` | Explicit user correction apply path |
| `RetrievalService` | class | `backend/src/kinlayer_backend/services/retrieval.py` | Scoring, penalties, policy buckets |
| `App` | component | `frontend/src/App.tsx` | Route shell and visible navigation |

## CONVENTIONS

- Korean user messages get Korean replies unless they ask otherwise.
- Before Docker, network, local service, or host changes, inspect current state first.
- Before test Docker containers, re-check honcho bindings: `127.0.0.1:8000`,
  `127.0.0.1:6379`, `127.0.0.1:5432`. Kinlayer defaults stay on API `8765`,
  Web `5173`, Postgres `127.0.0.1:15432`.
- Web/API intentionally bind beyond loopback in Docker; Postgres stays loopback-only.
- For repo work, inspect branch, worktree, remote tracking, and `origin/main` first.
- Do not commit, push, or merge directly to `main` unless the user explicitly asks.
- New work branches must be based on the latest `origin/main`.
- UI changes need browser or equivalent visual verification when feasible.
- Keep root Markdown sparse: `README.md`, `AGENTS.md`.
- Use `.omo/plans/` as the active execution-plan SSOT.
- Use `docs/kinlayer-roadmap.md` as the Korean user-facing implementation guide.
- `docs/archive/planning/implementation-plan-2026-06-27.md` is historical only.

## ANTI-PATTERNS

- Treating `docs/archive/` as active SSOT. It is historical material only.
- Treating archived `implementation-plan.md` task numbers as the active plan.
- Trusting old memory or archived docs over live code paths.
- Creating Web-only state-changing behavior; the HTTP API is canonical.
- Modeling cautions, feelings, reply strategy, preferences, or recent interaction
  interpretation as relationship edges. Use observations.
- Inventing ontology-controlled values. Fetch or read the active registry.
- Storing full raw conversation bodies; use bounded excerpts and hashes.
- Rewriting broad docs when the request only asks for a scoped rule or spec fix.

## COMMANDS

```bash
uv run ruff check .
uv run pytest
cd frontend && npm test
cd frontend && npm run build
scripts/smoke-slice0.sh
python3 scripts/load-acceptance-fixtures.py --api-url http://127.0.0.1:8765
python3 scripts/smoke-acceptance-api.py --api-url http://127.0.0.1:8765
KINLAYER_API_URL=http://127.0.0.1:8765 scripts/smoke-acceptance-cli.sh
```

## NOTES

- LSP may be unavailable in this workspace; use live file reads and targeted `rg`.
- Current checkout has no `.github` CI and no `Makefile`; local checks are the gate.
- `docs/specs/` may describe intended behavior, but when there is drift, verify the
  current router/service/schema first and then update the spec.

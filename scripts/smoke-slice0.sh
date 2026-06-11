#!/usr/bin/env bash
set -euo pipefail

echo "== Docker port snapshot =="
docker ps --format 'table {{.Names}}\t{{.Ports}}' || true

echo "== Compose startup =="
docker compose up -d --build

echo "== Alembic =="
uv run alembic upgrade head

echo "== API health =="
for attempt in {1..20}; do
  if curl -fsS http://127.0.0.1:8765/api/system/health 2>/dev/null; then
    echo
    break
  fi
  if [[ "$attempt" == "20" ]]; then
    echo "API health check did not become ready." >&2
    exit 1
  fi
  sleep 1
done

echo "== CLI status =="
uv run kinlayer status --json

if [[ -n "${KINLAYER_API_TOKEN:-}" ]]; then
  echo "== Token mode boundary =="
  curl -fsS http://127.0.0.1:8765/api/system/health >/dev/null
  curl -fsS http://127.0.0.1:8765/api/system/version >/dev/null
  status_without_token="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/api/entities)"
  if [[ "$status_without_token" != "401" ]]; then
    echo "Expected /api/entities without token to return 401, got $status_without_token." >&2
    exit 1
  fi
  curl -fsS -H "Authorization: Bearer ${KINLAYER_API_TOKEN}" \
    http://127.0.0.1:8765/api/entities >/dev/null
fi

echo "== Backend checks =="
uv run ruff check .
uv run pytest

echo "== Frontend build =="
cd frontend
npm run build

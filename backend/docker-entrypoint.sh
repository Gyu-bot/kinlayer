#!/bin/sh
set -eu

uv run alembic upgrade head

exec uv run uvicorn kinlayer_backend.main:app --host 0.0.0.0 --port 8765

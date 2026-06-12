FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml uv.lock* ./
COPY backend ./backend
COPY alembic.ini ./

RUN pip install --no-cache-dir uv \
  && uv sync --frozen --no-dev

EXPOSE 8765

CMD ["sh", "backend/docker-entrypoint.sh"]

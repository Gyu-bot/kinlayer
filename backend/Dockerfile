FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml uv.lock* ./
COPY backend ./backend
COPY alembic.ini ./

RUN pip install --no-cache-dir uv \
  && uv sync --frozen --no-dev

EXPOSE 8765

CMD ["uv", "run", "uvicorn", "kinlayer_backend.main:app", "--host", "0.0.0.0", "--port", "8765"]

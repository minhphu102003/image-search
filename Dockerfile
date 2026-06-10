# ── Base stage: shared Python environment ──
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY alembic.ini ./
COPY alembic/ alembic/
COPY src/ src/

# ── API target: core deps only (small image) ──
FROM base AS api

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "image_search.adapters.input.app:app", \
     "--host", "0.0.0.0", "--port", "8000"]

# ── Worker target: core deps (Jina cloud API + Gemini caption) ──
FROM base AS worker

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "python", "-m", "image_search.adapters.input.ingest_worker"]

# ── Migrate target: run alembic then exit ──
FROM base AS migrate

RUN uv sync --frozen --no-dev

CMD ["sh", "-c", "uv run alembic upgrade head"]

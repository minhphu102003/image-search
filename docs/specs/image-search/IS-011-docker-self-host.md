# Spec: Docker Self-Hosting — Full Stack Containerization

> Specification for Docker and Docker Compose to self-host the entire Image Search Service.

---

## Metadata

| Field        | Value                        |
|-------------|------------------------------|
| **ID**      | IS-011                       |
| **Title**   | Docker Self-Hosting          |
| **Phase**   | 5 — Deployment               |
| **Status**  | Draft                        |
| **Depends** | IS-001 through IS-010        |

---

## 1. Objective

Containerize all services (PostgreSQL+pgvector, Redis, API server, Ingest Worker, DB migrations) into a single `docker compose up` command for self-hosting.

---

## 2. Architecture

```
docker-compose
├── postgres      (pgvector/pgvector:pg16)
├── redis         (redis:7-alpine)
├── migrate       (run-once: alembic upgrade head)
├── api           (uvicorn, port 8000)
└── worker        (ingest worker, CPU-only torch)
```

```
┌─────────────────────────────────────────────┐
│              Docker Network                  │
│                                              │
│  ┌──────────┐  ┌───────┐  ┌──────────────┐  │
│  │ postgres  │  │ redis │  │    migrate   │  │
│  │ :5432    │  │ :6379 │  │ (run + exit) │  │
│  └────┬─────┘  └───┬───┘  └──────────────┘  │
│       │             │                         │
│  ┌────┴─────────────┴────┐                   │
│  │         api           │                   │
│  │  uvicorn :8000        │                   │
│  │  GET /health          │                   │
│  │  POST /api/v1/search  │                   │
│  └───────────────────────┘                   │
│                                              │
│  ┌───────────────────────┐                   │
│  │       worker          │                   │
│  │  ingest worker        │                   │
│  │  (SigLIP 2 + Redis)   │                   │
│  └───────────────────────┘                   │
└─────────────────────────────────────────────┘
```

---

## 3. Detailed Design

### 3.1 Dockerfile (multi-stage, two targets)

```dockerfile
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

# ── Worker target: includes torch + transformers ──
FROM base AS worker

RUN uv sync --frozen --no-dev --extra ai

CMD ["uv", "run", "python", "-m", "image_search.adapters.input.ingest_worker"]

# ── Migrate target: run alembic then exit ──
FROM base AS migrate

RUN uv sync --frozen --no-dev

CMD ["sh", "-c", "uv run alembic upgrade head"]
```

### 3.2 docker-compose.yml

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: beekid
      POSTGRES_PASSWORD: beekid_secret
      POSTGRES_DB: beekid_ai
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U beekid -d beekid_ai"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  migrate:
    build:
      context: .
      target: migrate
    environment:
      IMAGE_SEARCH_DATABASE_URL: postgresql+asyncpg://beekid:beekid_secret@postgres:5432/beekid_ai
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"

  api:
    build:
      context: .
      target: api
    ports:
      - "8000:8000"
    environment:
      IMAGE_SEARCH_DATABASE_URL: postgresql+asyncpg://beekid:beekid_secret@postgres:5432/beekid_ai
      IMAGE_SEARCH_REDIS_URL: redis://redis:6379
      IMAGE_SEARCH_IMAGE_SEARCH_HOST: "0.0.0.0"
      IMAGE_SEARCH_IMAGE_SEARCH_PORT: "8000"
      IMAGE_SEARCH_GEMINI_API_KEY: ${GEMINI_API_KEY:-}
      IMAGE_SEARCH_LOG_FORMAT: json
    depends_on:
      migrate:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  worker:
    build:
      context: .
      target: worker
    environment:
      IMAGE_SEARCH_DATABASE_URL: postgresql+asyncpg://beekid:beekid_secret@postgres:5432/beekid_ai
      IMAGE_SEARCH_REDIS_URL: redis://redis:6379
      IMAGE_SEARCH_WORKER_ID: "1"
      IMAGE_SEARCH_CAPTION_ENABLED: "false"
      IMAGE_SEARCH_GEMINI_API_KEY: ${GEMINI_API_KEY:-}
      IMAGE_SEARCH_SIGLIP_DEVICE: cpu
    depends_on:
      migrate:
        condition: service_completed_successfully

volumes:
  pgdata:
  redisdata:
```

### 3.3 .dockerignore

```
.git
.venv
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
tests/
docs/
scripts/
tools/
*.md
.env
.env.*
Dockerfile
docker-compose.yml
docker-compose.yaml
.dockerignore
```

### 3.4 .env.example

```bash
# ── Database ──
IMAGE_SEARCH_DATABASE_URL=postgresql+asyncpg://beekid:beekid_secret@postgres:5432/beekid_ai

# ── Redis ──
IMAGE_SEARCH_REDIS_URL=redis://redis:6379

# ── SigLIP 2 ──
IMAGE_SEARCH_SIGLIP_MODEL=google/siglip2-so400m-patch16-384
IMAGE_SEARCH_SIGLIP_DEVICE=cpu
IMAGE_SEARCH_EMBED_BATCH_SIZE=8

# ── pgvector HNSW ──
IMAGE_SEARCH_HNSW_M=16
IMAGE_SEARCH_HNSW_EF_CONSTRUCTION=64
IMAGE_SEARCH_HNSW_EF_SEARCH=40

# ── Search ──
IMAGE_SEARCH_IMAGE_SEARCH_APPROACH=1
IMAGE_SEARCH_IMAGE_SEARCH_HOST=0.0.0.0
IMAGE_SEARCH_IMAGE_SEARCH_PORT=8000

# ── Worker ──
IMAGE_SEARCH_WORKER_ID=1
IMAGE_SEARCH_CAPTION_ENABLED=false

# ── Gemini (optional, for approach 3 + captions) ──
GEMINI_API_KEY=

# ── Observability ──
IMAGE_SEARCH_METRICS_ENABLED=true
IMAGE_SEARCH_LOG_LEVEL=INFO
IMAGE_SEARCH_LOG_FORMAT=json
```

---

## 4. Startup Order

```
postgres (healthy) → redis (healthy) → migrate (exit 0) → api + worker
```

- `migrate` uses `depends_on: postgres: condition: service_healthy`
- `api` and `worker` use `depends_on: migrate: condition: service_completed_successfully`
- This ensures DB schema exists before any service connects

---

## 5. Volume Strategy

| Volume    | Purpose                          | Mount              |
|-----------|----------------------------------|--------------------|
| `pgdata`  | PostgreSQL data persistence      | `/var/lib/postgresql/data` |
| `redisdata` | Redis AOF/RDB persistence     | `/data`            |

Image files are **not** volume-mounted in MVP. The ingest worker reads `file_path` from events — in production, this should be a shared volume or object storage URL.

---

## 6. Image Size Estimates

| Target   | Base      | Deps         | Estimated Size |
|----------|-----------|--------------|---------------|
| `api`    | python:3.12-slim (~150MB) | core only | ~400MB |
| `worker` | python:3.12-slim (~150MB) | torch + transformers | ~3.5GB |
| `migrate` | python:3.12-slim (~150MB) | core only | ~400MB |

The worker image is large due to PyTorch CPU. For GPU support, extend the worker target with CUDA base image.

---

## 7. Common Commands

```bash
# Start everything
docker compose up -d

# View logs
docker compose logs -f api
docker compose logs -f worker

# Stop everything
docker compose down

# Stop and remove volumes (destroys data)
docker compose down -v

# Rebuild after code changes
docker compose build
docker compose up -d

# Run migrations manually
docker compose run --rm migrate

# Scale workers (if needed)
docker compose up -d --scale worker=3
```

---

## 8. Acceptance Criteria

- [ ] `docker compose up` starts all 5 services
- [ ] PostgreSQL is ready with pgvector extension and `image_embeddings` table
- [ ] `GET http://localhost:8000/health` returns `{"status": "ok"}`
- [ ] `POST http://localhost:8000/api/v1/image-search` accepts requests
- [ ] Worker connects to Redis and consumes `image:uploaded` events
- [ ] `docker compose down` stops cleanly
- [ ] `docker compose down -v` destroys volumes
- [ ] `.env.example` documents all env vars

---

## 9. Testing Strategy

### Manual Smoke Test
```bash
docker compose up -d
curl http://localhost:8000/health
# expect {"status": "ok", "checks": {"redis": "ok", "postgresql": "ok"}}

curl -X POST http://localhost:8000/api/v1/image-search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "top_k": 5}'
# expect 200 with empty results (no images indexed yet)
```

### CI (future)
- Build images in CI
- Run `docker compose up -d`
- Wait for health check
- Run smoke tests
- Tear down

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Beekid AI Platform — a Vietnamese education platform. This repo contains the **Image Search Service** module: text-to-image retrieval using SigLIP 2 embeddings stored in PostgreSQL + pgvector. The service is part of a larger event-driven system where a NestJS backend emits events via Redis Streams, and Python AI workers consume them.

## Commands

```bash
# Quick reference — run `make help` for full list

# Install dependencies (use uv, not pip)
uv sync                           # core deps
uv sync --extra dev               # + pytest, ruff, mypy
uv sync --extra ai                # + torch, transformers, pillow

# Quality gates
uv run pytest                                                     # all tests
uv run pytest tests/test_domain_entities.py -v                    # single file
uv run pytest tests/test_domain_entities.py::test_func_name -v    # single test
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run mypy src/

# Database migrations (requires running PostgreSQL)
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic revision --autogenerate -m "description"

# Docker
docker compose up -d              # start all services
docker compose down               # stop
docker compose down -v            # stop + delete data
docker compose build              # rebuild after code changes
docker compose logs -f api        # tail API logs
docker compose logs -f worker     # tail worker logs
```

## Architecture

**Clean Architecture** — code is split into `domain/` (pure Python dataclasses/enums) and `infrastructure/` (SQLAlchemy models, Redis, external services). Domain has zero dependencies on infrastructure.

**Directory structure:**
```
Beekid/
├── src/image_search/          # Main source package
│   ├── domain/                # Entities, enums, ports (abstract interfaces)
│   ├── application/           # Use cases — orchestrate domain logic, no framework deps
│   ├── adapters/              # Interface adapters (Ports & Adapters pattern)
│   │   ├── input/             # Driving adapters: REST API, event consumers, upload
│   │   └── output/            # Driven adapters: SQLAlchemy repo, Redis publisher, MinIO
│   └── infrastructure/        # Framework config: DB connection, pydantic-settings, AI models
├── alembic/                   # Database migrations (async via asyncio.run)
├── tests/                     # pytest tests — domain unit tests + DB integration tests
├── docs/
│   ├── architectures/         # System & module architecture diagrams
│   ├── specs/image-search/    # IS-001..IS-012 implementation specs
│   ├── use-cases/             # Use case descriptions
│   └── proposals/             # Feature proposals
├── Makefile                   # Common commands (make help)
├── Dockerfile                 # Multi-stage: api, worker, migrate targets
├── docker-compose.yml         # Full stack: postgres, redis, minio, api, worker
├── scripts/                   # Utility scripts
└── tools/                     # MCP tool configs
```

**Dependency flow:** `adapters/input` → `application` → `domain` ← `adapters/output` ← `infrastructure`. Domain has zero outward dependencies.

**Key tech decisions:**
- `Vector(1024)` for SigLIP 2 image embeddings, `Vector(768)` for optional caption text embeddings
- HNSW indexes with `vector_cosine_ops` for similarity search
- Async SQLAlchemy 2.0 with `asyncpg` driver
- Alembic `env.py` uses `asyncio.run()` for async migration execution and reads `IMAGE_SEARCH_DATABASE_URL` env var
- Test DB is separate (`beekid_ai_test`), configured in `tests/conftest.py`
- MinIO (S3-compatible) for image storage; SigLIP service handles both local paths and HTTP URLs
- All config via pydantic-settings with `IMAGE_SEARCH_` env prefix

**Event-driven integration:** Redis Streams connect this service to the NestJS backend.
- `image:uploaded` (inbound): upload endpoint publishes, ingest worker consumes
- `image:indexed` (outbound): ingest worker publishes after embedding

**Docker services:** postgres (pgvector:pg16), redis (7-alpine), minio, minio-init, migrate (run-once), api (uvicorn:8000), worker (SigLIP 2 + Redis)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/upload` | Upload image to MinIO, trigger auto-ingest |
| POST | `/api/v1/image-search` | Text-to-image search (3 approaches) |
| POST | `/images/ingest` | Internal: save pre-computed embedding |
| POST | `/images/search` | Internal: search by embedding vector |
| GET | `/images/{image_id}` | Get image metadata |
| DELETE | `/images/{image_id}` | Delete image |
| GET | `/health` | Health check (Redis + PostgreSQL) |

## Specs

Implementation specs live in `docs/specs/image-search/IS-*.md`. Each spec has acceptance criteria (checklist) and code snippets. When implementing a spec, follow the patterns from IS-001 (already implemented) for consistency.

## Conventions

- Python 3.12+, use `|` union syntax (not `Optional[]`)
- Vietnamese is used in architecture docs; code and comments are in English
- All async functions use `async def` / `await` (no sync wrappers)
- `uv` is the package manager — do not use pip directly
- Commit messages follow conventional commits: `feat:`, `fix:`, `chore:`, `docs:`

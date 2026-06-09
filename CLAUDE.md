# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Beekid AI Platform — a Vietnamese education platform. This repo contains the **Image Search Service** module: text-to-image retrieval using SigLIP 2 embeddings stored in PostgreSQL + pgvector. The service is part of a larger event-driven system where a NestJS backend emits events via Redis Streams, and Python AI workers consume them.

## Commands

```bash
# Install dependencies (use uv, not pip)
uv sync                           # core deps
uv sync --extra dev               # + pytest, ruff, mypy
uv sync --extra ai                # + torch, transformers, pillow

# Run tests
uv run pytest tests/test_domain_entities.py -v                    # single file
uv run pytest tests/test_domain_entities.py::test_func_name -v    # single test
uv run pytest                                                     # all tests
uv run pytest tests/test_models.py tests/test_repositories.py -v  # integration (needs DB)

# Lint & type check
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run mypy src/

# Database migrations (requires running PostgreSQL)
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic revision --autogenerate -m "description"
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
│   │   ├── input/             # Driving adapters: REST API, event consumers
│   │   └── output/            # Driven adapters: SQLAlchemy repo, Redis publisher
│   └── infrastructure/        # Framework config: DB connection, pydantic-settings, models
├── alembic/                   # Database migrations (async via asyncio.run)
├── tests/                     # pytest tests — domain unit tests + DB integration tests
├── docs/
│   ├── architectures/         # System & module architecture diagrams
│   ├── specs/image-search/    # IS-001..IS-010 implementation specs
│   ├── use-cases/             # Use case descriptions
│   └── proposals/             # Feature proposals
├── scripts/                   # Utility scripts
└── tools/                     # MCP tool configs
```

**Dependency flow:** `adapters/input` → `application` → `domain` ← `adapters/output` ← `infrastructure`. Domain has zero outward dependencies.

**Key tech decisions:**
- `Vector(1024)` for SigLIP 2 image embeddings, `Vector(768)` for optional caption text embeddings
- HNSW indexes with `vector_cosine_ops` for similarity search
- Async SQLAlchemy 2.0 with `asyncpg` driver
- Alembic `env.py` uses `asyncio.run()` for async migration execution
- Alembic prepend_sys_path is set to `src/` so imports resolve correctly
- Test DB is separate (`beekid_ai_test`), configured in `tests/conftest.py`

**Event-driven integration:** Redis Streams connect this service to the NestJS backend. Events: `image:uploaded` (inbound), `image:indexed` (outbound). See `docs/specs/image-search/IS-002-redis-stream-events.md`.

## Specs

Implementation specs live in `docs/specs/image-search/IS-*.md`. Each spec has acceptance criteria (checklist) and code snippets. When implementing a spec, follow the patterns from IS-001 (already implemented) for consistency.

## Conventions

- Python 3.12+, use `|` union syntax (not `Optional[]`)
- Vietnamese is used in architecture docs; code and comments are in English
- All async functions use `async def` / `await` (no sync wrappers)
- `uv` is the package manager — do not use pip directly

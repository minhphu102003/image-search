# Beekid Image Search

Text-to-image search service for the Beekid education platform.

## Quick Start (Docker)

```bash
docker compose up -d
```

That's it. This starts:
- **PostgreSQL** with pgvector (port 5432)
- **Redis** (port 6379)
- **API server** (port 8000)
- **Ingest worker** (SigLIP 2 embeddings)

Verify:

```bash
curl http://localhost:8000/health
# {"status": "ok", "checks": {"redis": "ok", "postgresql": "ok"}}
```

Stop:

```bash
docker compose down        # stop
docker compose down -v     # stop + delete data
```

## Search API

```bash
curl -X POST http://localhost:8000/api/v1/image-search \
  -H "Content-Type: application/json" \
  -d '{"query": "a red car", "top_k": 10, "approach": 1}'
```

| Approach | Name | Speed | Cost |
|----------|------|-------|------|
| 1 | Pure CLIP | ~50ms | Free |
| 2 | Hybrid Caption (RRF) | ~200ms | Free |
| 3 | Multimodal RAG (Gemini) | ~500ms | ~$0.00004/query |

## Local Development

```bash
# Install
uv sync --extra ai --extra dev

# Env vars (copy .env.example → .env, adjust DB/Redis URLs for local)
cp .env.example .env

# Migrate
uv run alembic upgrade head

# Run
uv run uvicorn image_search.adapters.input.app:app --host 0.0.0.0 --port 8000
uv run python -m image_search.adapters.input.ingest_worker
```

## Tests

```bash
uv run pytest                     # all unit tests
uv run ruff check src/ tests/     # lint
uv run mypy src/                  # type check
```

## Architecture

```
Domain (entities, ports) ← Adapters (FastAPI, SQLAlchemy) ← Infrastructure (DB, Redis, AI)
```

```
docs/specs/image-search/    # Implementation specs (IS-001..IS-011)
```

# Beekid Image Search Service

Text-to-image retrieval service for the Beekid education platform. Uses SigLIP 2 embeddings stored in PostgreSQL + pgvector, with an event-driven ingest pipeline via Redis Streams.

## Architecture

```
NestJS Backend
    │ image:uploaded (Redis Stream)
    ▼
┌─────────────────────┐
│  Ingest Worker       │  SigLIP 2 embed → PostgreSQL + pgvector
│  (adapters/input)    │  Optional: Gemini caption + text embedding
└─────────────────────┘
    │ image:indexed (Redis Stream)
    ▼
NestJS Backend

Teacher / QGen Worker
    │ POST /api/v1/image-search {query: "a red car"}
    ▼
┌─────────────────────┐
│  Search API          │  SigLIP text embed → approach delegation
│  (FastAPI)           │  → pgvector cosine search → results
└─────────────────────┘
```

**Clean Architecture** — dependency flow:

```
adapters/input  →  application  →  domain  ←  adapters/output  ←  infrastructure
(FastAPI, worker)   (use cases)    (entities)   (SQLAlchemy repo)   (DB, Redis, AI)
```

Domain has zero outward dependencies. All infrastructure is injected through abstract ports.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API Framework | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 (async, asyncpg) |
| Vector DB | PostgreSQL 16 + pgvector (HNSW indexes) |
| Event Bus | Redis 7.x Streams (XADD / XREADGROUP) |
| Embeddings | SigLIP 2 (`google/siglip2-so400m-patch16-384`, 1024-dim) |
| Captions | Google Gemini 2.0 Flash (optional) |
| Config | pydantic-settings (env vars with `IMAGE_SEARCH_` prefix) |
| Observability | structlog + prometheus-client |
| Package Manager | uv |

## Project Structure

```
src/image_search/
├── domain/                    # Pure Python — entities, enums, abstract ports
│   ├── entities.py            # ImageEmbedding dataclass, ImageStatus enum
│   ├── events.py              # ImageUploadedEvent, ImageIndexedEvent, EventBus ABC
│   ├── embedding_service.py   # EmbeddingService ABC (embed_image, embed_text, batch)
│   ├── caption_service.py     # CaptionService ABC (generate_caption)
│   ├── search_approach.py     # SearchApproach ABC, SearchResult, SearchResponse
│   └── ports/
│       └── repositories.py    # ImageEmbeddingRepositoryPort ABC
├── application/               # Use cases — orchestrate domain logic, no framework deps
│   ├── use_cases.py           # CRUD: Ingest, Search, Get, Delete
│   ├── ingest_worker.py       # IngestWorkerUseCase (embed → save → caption → emit)
│   └── search_images.py       # SearchImagesUseCase (embed query → delegate to approach)
├── adapters/
│   ├── input/
│   │   ├── app.py             # FastAPI factory, health endpoint, Prometheus
│   │   ├── rest_api.py        # CRUD router: /images (ingest, search, get, delete)
│   │   ├── search_router.py   # Search router: POST /api/v1/image-search
│   │   └── ingest_worker.py   # Standalone entry point (python -m)
│   └── output/
│       └── sqlalchemy_repo.py # SqlAlchemyImageEmbeddingRepository
└── infrastructure/
    ├── config.py              # Settings (pydantic-settings, IMAGE_SEARCH_ prefix)
    ├── database/
    │   ├── connection.py      # Async engine, session factory, init_db()
    │   └── models.py          # ImageEmbeddingModel (SQLAlchemy + pgvector Vector)
    ├── redis/
    │   ├── connection.py      # Redis client factory
    │   └── event_bus.py       # RedisEventBus (XADD, XREADGROUP, dead-letter)
    └── ai/
        ├── siglip_service.py  # SigLIPEmbeddingService (HuggingFace transformers)
        └── caption_service.py # GeminiCaptionService (google-generativeai)

alembic/                       # Database migrations
tests/                         # pytest — domain unit tests + integration tests
docs/
├── architectures/             # System & module architecture diagrams
├── specs/image-search/        # IS-001..IS-010 implementation specs
├── use-cases/                 # Use case descriptions
└── proposals/                 # Feature proposals
scripts/                       # Utility scripts
```

## Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL 16 with pgvector extension
- Redis 7.x
- [uv](https://docs.astral.sh/uv/) package manager

### Install

```bash
uv sync                     # core dependencies
uv sync --extra ai          # + torch, transformers, pillow, google-generativeai
uv sync --extra dev         # + pytest, ruff, mypy
```

### Environment Variables

Create a `.env` file (all prefixed with `IMAGE_SEARCH_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `IMAGE_SEARCH_DATABASE_URL` | `postgresql+asyncpg://user:pass@localhost:5432/beekid_ai` | PostgreSQL connection string |
| `IMAGE_SEARCH_REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `IMAGE_SEARCH_SIGLIP_MODEL` | `google/siglip2-so400m-patch16-384` | HuggingFace model ID |
| `IMAGE_SEARCH_SIGLIP_DEVICE` | *(auto-detect)* | `cuda` or `cpu` |
| `IMAGE_SEARCH_EMBED_BATCH_SIZE` | `8` | Batch size for embedding |
| `IMAGE_SEARCH_HNSW_M` | `16` | HNSW graph connections |
| `IMAGE_SEARCH_HNSW_EF_CONSTRUCTION` | `64` | HNSW build quality |
| `IMAGE_SEARCH_HNSW_EF_SEARCH` | `40` | HNSW search quality |
| `IMAGE_SEARCH_IMAGE_SEARCH_APPROACH` | `1` | Default search approach (1=CLIP, 2=Hybrid, 3=RAG) |
| `IMAGE_SEARCH_IMAGE_SEARCH_HOST` | `0.0.0.0` | API bind host |
| `IMAGE_SEARCH_IMAGE_SEARCH_PORT` | `8000` | API bind port |
| `IMAGE_SEARCH_WORKER_ID` | `1` | Ingest worker identifier |
| `IMAGE_SEARCH_CAPTION_ENABLED` | `false` | Enable Gemini captioning during ingest |
| `IMAGE_SEARCH_GEMINI_API_KEY` | *(none)* | Google Gemini API key (required if captions enabled) |

### Database Setup

```bash
# Start PostgreSQL with pgvector, then:
uv run alembic upgrade head
```

### Run

```bash
# Search API server
uv run uvicorn image_search.adapters.input.app:create_app --factory --host 0.0.0.0 --port 8000

# Ingest worker (listens to Redis Stream)
uv run python -m image_search.adapters.input.ingest_worker
```

## API Endpoints

### Search API (`/api/v1`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/image-search` | Text-to-image search |

```bash
curl -X POST http://localhost:8000/api/v1/image-search \
  -H "Content-Type: application/json" \
  -d '{"query": "a red car", "top_k": 10, "approach": 1}'
```

**Approaches:**
- `1` — Pure CLIP: zero-cost pgvector cosine similarity, ~50ms
- `2` — Hybrid Caption: dual-vector RRF fusion, ~200ms
- `3` — Multimodal RAG: Gemini Vision reasoning, ~500ms

### CRUD API (`/images`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/images/ingest` | Ingest with pre-computed embedding |
| `POST` | `/images/search` | Search with raw embedding vector |
| `GET` | `/images/{image_id}` | Get image by ID |
| `DELETE` | `/images/{image_id}` | Delete image by ID |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |

## Development

### Run Tests

```bash
uv run pytest                                                          # all tests
uv run pytest tests/test_domain_entities.py -v                         # single file
uv run pytest tests/test_domain_entities.py::test_func_name -v         # single test
uv run pytest tests/test_models.py tests/test_repositories.py -v       # integration (needs DB)
```

### Lint & Type Check

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run mypy src/
```

### Database Migrations

```bash
uv run alembic upgrade head                # apply migrations
uv run alembic downgrade -1                # rollback one
uv run alembic revision --autogenerate -m "description"   # new migration
```

## Implementation Status

| Spec | Title | Status |
|------|-------|--------|
| IS-001 | Database Schema — `image_embeddings` | Done |
| IS-002 | Redis Stream Event Bus | Done |
| IS-003 | SigLIP 2 Embedding Service | Done |
| IS-004 | Image Ingest Worker | Done |
| IS-005 | Search Foundation — Shared Infrastructure | Done |
| IS-006 | Approach 1 — Pure CLIP Search | Next |
| IS-007 | Approach 2 — Hybrid Caption Search (RRF) | Planned |
| IS-008 | Approach 3 — Multimodal RAG with Gemini | Planned |
| IS-009 | QGen Integration | Planned |
| IS-010 | Observability and Monitoring | Planned |

Detailed specs: [`docs/specs/image-search/`](docs/specs/image-search/)

# Spec: Image Search Foundation — Shared Search Infrastructure

> Specification for FastAPI search endpoint with Clean Architecture and dependency injection.

---

## Metadata

| Field        | Value                                    |
|-------------|------------------------------------------|
| **ID**      | IS-005                                   |
| **Title**   | Image Search Foundation — Shared Infrastructure |
| **Phase**   | 3 — Search                               |
| **Status**  | Draft                                    |
| **Depends** | IS-001, IS-002, IS-003                   |

---

## 1. Objective

Provide a unified FastAPI search endpoint with dependency injection, request validation, and approach delegation. Define shared schemas, configuration, and the abstract search approach interface.

---

## 2. Architecture

```
src/image_search/
├── domain/
│   └── search_approach.py       # Abstract SearchApproach interface
├── application/
│   └── search_images.py         # SearchImagesUseCase
├── infrastructure/
│   └── config.py                # Settings
└── presentation/
    └── api/
        ├── router.py            # FastAPI router
        ├── schemas.py           # Pydantic request/response
        └── dependencies.py      # DI dependencies
```

---

## 3. Detailed Design

### 3.1 Domain — Search Approach Interface

```python
# src/image_search/domain/search_approach.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class SearchResult:
    image_id: str
    file_path: str
    score: float
    caption: str | None = None

@dataclass
class SearchResponse:
    images: list[SearchResult]
    answer: str | None = None

class SearchApproach(ABC):
    @abstractmethod
    async def search(self, query_vector: list[float], top_k: int, query_text: str) -> SearchResponse:
        """Execute search with this approach."""
        ...
```

### 3.2 Application — Use Case

```python
# src/image_search/application/search_images.py
import time
import structlog

from image_search.domain.search_approach import SearchApproach, SearchResponse
from image_search.domain.embedding_service import EmbeddingService

logger = structlog.get_logger()

class SearchImagesUseCase:
    def __init__(self, embedding_service: EmbeddingService, approaches: dict[int, SearchApproach]):
        self.embedding_service = embedding_service
        self.approaches = approaches  # {1: PureClipApproach, 2: HybridCaptionApproach, ...}

    async def execute(self, query: str, top_k: int, approach: int) -> tuple[SearchResponse, float]:
        start = time.time()

        # Embed query
        query_vector = await self.embedding_service.embed_text(query)

        # Delegate to approach
        search_approach = self.approaches[approach]
        result = await search_approach.search(query_vector, top_k, query)

        latency_ms = (time.time() - start) * 1000
        logger.info("search_completed", approach=approach, results=len(result.images), latency_ms=latency_ms)

        return result, latency_ms
```

### 3.3 Presentation — Pydantic Schemas

```python
# src/image_search/presentation/api/schemas.py
from pydantic import BaseModel, Field

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=10, ge=1, le=100)
    approach: int | None = Field(default=None, ge=1, le=3)

class ImageResult(BaseModel):
    image_id: str
    file_path: str
    score: float
    caption: str | None = None

class SearchResponseSchema(BaseModel):
    images: list[ImageResult]
    answer: str | None = None
    approach: int
    latency_ms: float
```

### 3.4 Presentation — Dependencies

```python
# src/image_search/presentation/api/dependencies.py
from functools import lru_cache
from fastapi import Depends

from image_search.infrastructure.config import settings
from image_search.infrastructure.ai.siglip_service import SigLIPEmbeddingService
from image_search.infrastructure.database.connection import async_session
from image_search.infrastructure.database.repositories import PostgresImageRepository
from image_search.application.search_images import SearchImagesUseCase
from image_search.infrastructure.approaches.pure_clip import PureClipApproach
from image_search.infrastructure.approaches.hybrid_caption import HybridCaptionApproach
from image_search.infrastructure.approaches.multimodal_rag import MultimodalRAGApproach

@lru_cache
def get_embedding_service() -> SigLIPEmbeddingService:
    return SigLIPEmbeddingService(settings.siglip_model)

async def get_search_use_case() -> SearchImagesUseCase:
    embedding_service = get_embedding_service()

    async with async_session() as session:
        repository = PostgresImageRepository(session)
        approaches = {
            1: PureClipApproach(repository),
            2: HybridCaptionApproach(repository),
            3: MultimodalRAGApproach(repository, settings.gemini_api_key),
        }
        yield SearchImagesUseCase(embedding_service, approaches)
```

### 3.5 Presentation — Router

```python
# src/image_search/presentation/api/router.py
from fastapi import APIRouter, Depends, HTTPException

from .schemas import SearchRequest, SearchResponseSchema, ImageResult
from .dependencies import get_search_use_case
from application.search_images import SearchImagesUseCase
from infrastructure.config import settings

router = APIRouter(prefix="/api/v1")

@router.post("/image-search", response_model=SearchResponseSchema)
async def search_images(
    req: SearchRequest,
    use_case: SearchImagesUseCase = Depends(get_search_use_case),
):
    approach = req.approach or settings.image_search_approach

    result, latency_ms = await use_case.execute(req.query, req.top_k, approach)

    return SearchResponseSchema(
        images=[ImageResult(**img.__dict__) for img in result.images],
        answer=result.answer,
        approach=approach,
        latency_ms=round(latency_ms, 2),
    )
```

### 3.6 FastAPI App

```python
# src/image_search/presentation/api/app.py
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from .router import router

app = FastAPI(title="Image Search Service")
app.include_router(router)

# Prometheus metrics
Instrumentator().instrument(app).expose(app)

@app.get("/health")
async def health():
    return {"status": "ok"}
```

---

## 4. Configuration

```python
# In Settings class
image_search_approach: int = 1  # Default approach (1, 2, or 3)
image_search_host: str = "0.0.0.0"
image_search_port: int = 8000
```

---

## 5. Error Handling

| Scenario                   | HTTP Code | Response                              |
|---------------------------|-----------|---------------------------------------|
| Empty `query`              | 400       | `{"detail": "query must not be empty"}`|
| `top_k` out of range       | 400       | Validation error from Pydantic        |
| SigLIP embed fails         | 500       | `{"detail": "embedding failed"}`      |
| Database error             | 500       | `{"detail": "search failed"}`         |

---

## 6. Acceptance Criteria

- [ ] `POST /api/v1/image-search` with valid body returns 200
- [ ] Empty `query` returns 422 (Pydantic validation)
- [ ] `top_k=0` returns 422
- [ ] Response includes `latency_ms` > 0
- [ ] Config `IMAGE_SEARCH_APPROACH=2` → default approach is 2
- [ ] Per-request `approach=1` overrides config
- [ ] `/health` returns `{"status": "ok"}`
- [ ] `/metrics` returns Prometheus metrics

---

## 7. Run Server

```bash
uv run uvicorn image_search.presentation.api.app:app --host 0.0.0.0 --port 8000
```

---

## 8. Testing Strategy

### Unit Tests
- Mock `SearchImagesUseCase`
- Request validation: empty query, out-of-range top_k

### Integration Tests
- Full HTTP request → embed → search → response
- With pre-populated database

### API Tests
- 422 for invalid inputs
- 200 for valid inputs

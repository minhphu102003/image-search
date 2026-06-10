# Spec: Cloud Embedding API — Jina AI

> Replace self-hosted SigLIP 2 with Jina AI cloud embedding API. Eliminate GPU dependency, reduce Docker image size, improve embedding quality.

---

## Metadata

| Field        | Value                              |
|-------------|-------------------------------------|
| **ID**      | IS-014                              |
| **Title**   | Cloud Embedding API — Jina AI       |
| **Phase**   | 1 — Foundation                      |
| **Status**  | Draft                               |
| **Depends** | IS-001, IS-003                      |

---

## 1. Objective

Replace the self-hosted SigLIP 2 model (`google/siglip2-so400m-patch16-384`) with Jina AI cloud embedding API (`jina-embeddings-v4`). This eliminates the need for PyTorch/transformers in the worker container, reduces Docker image size from ~3GB to ~200MB, and removes GPU dependency.

**Hybrid strategy:** All expensive work happens at ingest time (once per image). Search is cheap (1 text embedding API call + pgvector cosine search).

```
Ingest (per image, pay once):
  1. Image → Jina API → 1024-dim image embedding
  2. Image → Gemini Vision → caption text
  3. Caption → Jina API → 1024-dim text embedding
  4. Store both vectors in pgvector

Search (per query, cheap):
  1. Query → Jina API → 1024-dim text embedding
  2. pgvector cosine search on both columns → RRF fusion
```

---

## 2. Tech Stack

| Tool                | Purpose                              |
|--------------------|--------------------------------------|
| Jina AI API        | Cloud image + text embeddings        |
| httpx              | Async HTTP client (already in deps)  |
| google-generativeai| Gemini Vision caption generation     |
| pgvector           | Vector similarity search             |

---

## 3. Detailed Design

### 3.1 Architecture — Provider Selection

```
src/image_search/
├── domain/
│   └── embedding_service.py        # Abstract interface (unchanged)
├── infrastructure/
│   ├── ai/
│   │   ├── jina_service.py         # NEW: Jina AI cloud implementation
│   │   ├── siglip_service.py       # Existing: SigLIP self-hosted (fallback)
│   │   └── caption_service.py      # Modified: add HTTP URL support
│   └── config.py                   # Modified: add embedding_provider + jina_* settings
├── adapters/input/
│   ├── ingest_worker.py            # Modified: provider selection
│   └── search_router.py            # Modified: provider selection
```

### 3.2 JinaEmbeddingService

```python
# src/image_search/infrastructure/ai/jina_service.py
import base64

import httpx
import structlog

from image_search.domain.embedding_service import EmbeddingService

logger = structlog.get_logger()

class JinaEmbeddingService(EmbeddingService):
    """Cloud embedding service using Jina AI API."""

    def __init__(
        self,
        api_key: str,
        model: str = "jina-embeddings-v4",
        api_url: str = "https://api.jina.ai/v1/embeddings",
        dimensions: int = 1024,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.api_url = api_url
        self.dimensions = dimensions
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _call_api(self, inputs: list[dict[str, str]], task: str) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": self.model,
            "input": inputs,
            "task": task,
        }
        resp = await self._client.post(self.api_url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]

    async def embed_image(self, image_path: str) -> list[float]:
        if image_path.startswith("http://") or image_path.startswith("https://"):
            input_item: dict[str, str] = {"image": image_path}
        else:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            input_item = {"image": f"data:image/jpeg;base64,{b64}"}

        results = await self._call_api([input_item], task="retrieval.passage")
        return results[0]

    async def embed_text(self, text: str) -> list[float]:
        results = await self._call_api([{"text": text}], task="retrieval.query")
        return results[0]

    async def embed_images_batch(self, image_paths: list[str]) -> list[list[float]]:
        inputs: list[dict[str, str]] = []
        for p in image_paths:
            if p.startswith("http://") or p.startswith("https://"):
                inputs.append({"image": p})
            else:
                with open(p, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                inputs.append({"image": f"data:image/jpeg;base64,{b64}"})
        return await self._call_api(inputs, task="retrieval.passage")

    async def embed_texts_batch(self, texts: list[str]) -> list[list[float]]:
        inputs = [{"text": t} for t in texts]
        return await self._call_api(inputs, task="retrieval.query")
```

### 3.3 Provider Selection Logic

```python
# In ingest_worker.py and search_router.py
def create_embedding_service(settings: Settings) -> EmbeddingService:
    if settings.embedding_provider == "jina":
        if not settings.jina_api_key:
            raise ValueError("IMAGE_SEARCH_JINA_API_KEY is required when embedding_provider='jina'")
        from image_search.infrastructure.ai.jina_service import JinaEmbeddingService
        return JinaEmbeddingService(
            api_key=settings.jina_api_key,
            model=settings.jina_model,
            api_url=settings.jina_api_url,
            dimensions=settings.jina_dimensions,
        )
    elif settings.embedding_provider == "siglip":
        from image_search.infrastructure.ai.siglip_service import SigLIPEmbeddingService
        return SigLIPEmbeddingService(
            model_name=settings.siglip_model,
            device=settings.siglip_device,
        )
    else:
        raise ValueError(f"Unknown embedding_provider: {settings.embedding_provider}")
```

### 3.4 Jina AI API Specification

| Property         | Value                                    |
|-----------------|------------------------------------------|
| Endpoint        | `https://api.jina.ai/v1/embeddings`     |
| Model           | `jina-embeddings-v4`                     |
| Image Dims      | 1024 (MRL, configurable down to 128)    |
| Text Dims       | 1024 (MRL, configurable down to 128)    |
| Auth            | Bearer token (`JINA_API_KEY`)            |
| Task Types      | `retrieval.query`, `retrieval.passage`   |
| Image Input     | URL string or base64 data URI            |
| Text Input      | Plain string                             |
| Rate Limit (Free) | 100 RPM, 100K TPM                     |
| Rate Limit (Paid) | 500 RPM, 2M TPM                       |

### 3.5 DB Migration — Unify Caption Embedding Dimension

```python
# alembic/versions/002_unify_caption_embedding_dim.py
def upgrade():
    # Alter caption_embedding: Vector(768) → Vector(1024)
    op.execute("ALTER TABLE image_embeddings ALTER COLUMN caption_embedding TYPE vector(1024)")

    # Recreate HNSW index with new dimensions
    op.execute("DROP INDEX IF EXISTS idx_image_embeddings_caption_hnsw")
    op.execute("""
        CREATE INDEX idx_image_embeddings_caption_hnsw
        ON image_embeddings
        USING hnsw (caption_embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE caption_embedding IS NOT NULL
    """)

    # Update default model_name
    op.alter_column("image_embeddings", "model_name", server_default="jina-embeddings-v4")
```

---

## 4. Configuration

```python
# In Settings class
embedding_provider: str = "jina"        # "jina" or "siglip"
jina_api_key: str | None = None
jina_model: str = "jina-embeddings-v4"
jina_api_url: str = "https://api.jina.ai/v1/embeddings"
jina_dimensions: int = 1024
```

| Env Var                           | Default                                | Description              |
|----------------------------------|----------------------------------------|--------------------------|
| `IMAGE_SEARCH_EMBEDDING_PROVIDER`| `jina`                                 | Provider selection       |
| `IMAGE_SEARCH_JINA_API_KEY`      | None                                   | Jina AI API key          |
| `IMAGE_SEARCH_JINA_MODEL`        | `jina-embeddings-v4`                   | Jina model ID            |
| `IMAGE_SEARCH_JINA_API_URL`      | `https://api.jina.ai/v1/embeddings`   | API endpoint             |
| `IMAGE_SEARCH_JINA_DIMENSIONS`   | `1024`                                 | Embedding dimensions     |

Existing `IMAGE_SEARCH_SIGLIP_*` vars remain for backward compatibility when `embedding_provider=siglip`.

---

## 5. Error Handling

| Scenario                          | Action                                       |
|----------------------------------|----------------------------------------------|
| Missing `jina_api_key`           | Raise `ValueError` at startup                |
| API 429 (rate limit)            | Retry with exponential backoff (3 attempts)  |
| API 500/502/503                  | Retry with exponential backoff (3 attempts)  |
| API timeout (30s)               | Raise `httpx.TimeoutException`, fail image   |
| Invalid image format             | API returns 400, log error, mark FAILED      |
| Network unreachable              | Fail immediately, mark image as FAILED       |

---

## 6. Acceptance Criteria

- [ ] `JinaEmbeddingService.embed_image(url)` returns `list` of exactly `1024` floats
- [ ] `JinaEmbeddingService.embed_text("a red car")` returns `list` of exactly `1024` floats
- [ ] Provider selection: `embedding_provider=jina` uses Jina, `=siglip` uses SigLIP
- [ ] Ingest pipeline: image embed + caption + caption embed all work with Jina
- [ ] Search pipeline: text embed + cosine search + RRF fusion work with Jina
- [ ] DB migration 002: `caption_embedding` column is `Vector(1024)` after upgrade
- [ ] Docker worker image builds without torch/transformers (~200MB vs ~3GB)
- [ ] Existing tests pass with updated mock dimensions
- [ ] `ruff check` and `mypy` pass

---

## 7. Testing Strategy

### Unit Tests
- Mock `httpx.AsyncClient.post` to return fake Jina API responses
- Test `embed_image` with URL input (passes URL directly)
- Test `embed_image` with local file (base64 encodes)
- Test `embed_text` with task type `retrieval.query`
- Test `embed_images_batch` and `embed_texts_batch`
- Test error handling: 429, 500, timeout
- Test provider selection: jina vs siglip vs invalid

### Integration Tests
- End-to-end: upload image → ingest → search → verify results
- DB migration up/down with Vector(1024)
- Caption embedding stored with correct dimensions

### Performance Tests
- Single image embed latency via Jina API (< 2s including network)
- Batch embed throughput (10 images < 5s)

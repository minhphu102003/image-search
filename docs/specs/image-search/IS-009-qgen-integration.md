# Spec: QGen Integration — Image Context for Question Generation

> Specification for how QGen Worker invokes Image Search to enrich questions with visual context.

---

## Metadata

| Field        | Value                        |
|-------------|------------------------------|
| **ID**      | IS-009                       |
| **Title**   | QGen Integration — Image Context |
| **Phase**   | 4 — Integration              |
| **Status**  | Draft                        |
| **Depends** | IS-005, IS-008               |

---

## 1. Objective

Enable QGen Worker to retrieve relevant images when generating questions that reference visual content. Define integration pattern and data contract.

---

## 2. Architecture

```
QGen Worker (separate service)
    │
    └── httpx.AsyncClient
        └── POST /api/v1/image-search (IS-005)
            └── Image Search Service
```

---

## 3. Detailed Design

### 3.1 Integration Pattern: Sync HTTP (Recommended for MVP)

```python
# In QGen Worker codebase (separate repo)
import httpx
import structlog

logger = structlog.get_logger()

class ImageSearchClient:
    """Client for Image Search Service."""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 10.0):
        self.base_url = base_url
        self.timeout = timeout

    async def search(self, query: str, top_k: int = 5, approach: int = 3) -> dict:
        """
        Call Image Search Service.

        Returns:
            {
                "images": [{"image_id", "file_path", "score", "caption"}],
                "answer": str | None,
                "approach": int,
                "latency_ms": float
            }
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/image-search",
                    json={"query": query, "top_k": top_k, "approach": approach},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.warning("image_search_failed", error=str(e))
            return {"images": [], "answer": None}
```

### 3.2 Usage in QGen Pipeline

```python
# In QGen Worker
async def generate_questions(doc_id: str, content: str):
    # 1. Text retrieval (LightRAG)
    text_chunks = await lightrag_retrieve(content)

    # 2. Image retrieval (Image Search)
    image_client = ImageSearchClient(settings.image_search_url)
    image_context = await image_client.search(content, top_k=5, approach=3)

    # 3. Build generator context
    context = build_context(
        text_chunks=text_chunks,
        images=image_context["images"],
        image_answer=image_context.get("answer"),
    )

    # 4. Generate questions
    questions = await gemini_generate(context)

    return questions
```

### 3.3 Data Contract

**Request:**
```json
{
  "query": "charts showing student performance trends",
  "top_k": 5,
  "approach": 3
}
```

**Response:**
```json
{
  "images": [
    {
      "image_id": "img-042",
      "file_path": "/images/chart_performance.jpg",
      "score": 0.78,
      "caption": "Bar chart showing student scores over 3 years"
    }
  ],
  "answer": "The images show performance trends with improvement in math scores...",
  "approach": 3,
  "latency_ms": 423.5
}
```

---

## 4. Configuration

```python
# In QGen Worker Settings
image_search_url: str = "http://localhost:8000"
image_search_timeout: float = 10.0
image_search_top_k: int = 5
```

---

## 5. Error Handling

| Scenario                    | Action                              |
|----------------------------|-------------------------------------|
| Image Search unavailable    | Log warning, proceed without images |
| HTTP timeout                | Log warning, proceed without images |
| Invalid response            | Log error, proceed without images   |

**Key principle**: Image context is always optional. QGen must never fail because of Image Search.

---

## 6. Acceptance Criteria

- [ ] QGen can call `POST /api/v1/image-search` and receive valid response
- [ ] If Image Search is down, QGen proceeds without images
- [ ] Images are included in Generator context
- [ ] Generated questions reference images when relevant
- [ ] Latency: image search adds < 500ms to QGen pipeline

---

## 7. Testing Strategy

### Unit Tests
- Mock HTTP client → returns expected structure
- HTTP timeout → returns empty context

### Integration Tests
- QGen + Image Search running together
- Image Search down → QGen still works

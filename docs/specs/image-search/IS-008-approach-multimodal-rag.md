# Spec: Approach 3 — Multimodal RAG with Gemini Vision

> Specification for image-grounded question answering using pgvector + Gemini 2.0 Flash.

---

## Metadata

| Field        | Value                              |
|-------------|-------------------------------------|
| **ID**      | IS-008                              |
| **Title**   | Approach 3 — Multimodal RAG         |
| **Phase**   | 3 — Search                          |
| **Status**  | Draft                               |
| **Depends** | IS-005                              |

---

## 1. Objective

Implement multimodal RAG as a `SearchApproach` strategy: retrieve top-5 images via pgvector, send to Gemini 2.0 Flash for visual reasoning, return images + natural language answer.

---

## 2. Architecture

```
src/image_search/
├── domain/
│   └── search_approach.py       # Abstract SearchApproach (IS-005)
├── infrastructure/
│   └── approaches/
│       └── multimodal_rag.py    # MultimodalRAGApproach implementation
```

---

## 3. Detailed Design

### 3.1 Implementation

```python
# src/image_search/infrastructure/approaches/multimodal_rag.py
from PIL import Image
import google.generativeai as genai
import structlog

from image_search.domain.search_approach import SearchApproach, SearchResponse, SearchResult
from image_search.domain.repositories import ImageRepository

logger = structlog.get_logger()

SYSTEM_PROMPT = """You are an image analysis assistant for an education platform.
Given a set of images and a user question:
1. Identify which images are relevant to the question
2. Describe what you see in the relevant images
3. Provide a concise, informative answer grounded in the images
4. Reference specific images by their position (Image 1, Image 2, etc.)"""

class MultimodalRAGApproach(SearchApproach):
    def __init__(self, repository: ImageRepository, gemini_api_key: str, top_k_retrieve: int = 5):
        self.repository = repository
        self.top_k_retrieve = top_k_retrieve
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash", system_instruction=SYSTEM_PROMPT)

    async def search(self, query_vector: list[float], top_k: int, query_text: str) -> SearchResponse:
        # Step 1: Retrieve top-5 from pgvector
        rows = await self.repository.cosine_search(
            embedding=query_vector, top_k=self.top_k_retrieve, model_name="siglip2-384"
        )

        if not rows:
            return SearchResponse(images=[], answer="No images found.")

        # Step 2: Load images
        image_parts = []
        for row in rows:
            try:
                img = Image.open(row["file_path"])
                image_parts.append(img)
            except Exception as e:
                logger.warning("image_load_failed", path=row["file_path"], error=str(e))

        # Step 3: Build prompt
        user_message = f"User question: {query_text}\n\nAnalyze the following {len(image_parts)} images and answer the question."

        # Step 4: Call Gemini
        try:
            prompt_parts = [user_message] + image_parts
            response = await self.model.generate_content_async(prompt_parts)
            answer = response.text.strip()
        except Exception as e:
            logger.error("gemini_failed", error=str(e))
            answer = None

        # Step 5: Format response
        return SearchResponse(
            images=[
                SearchResult(
                    image_id=r["image_id"],
                    file_path=r["file_path"],
                    score=round(r["score"], 4),
                    caption=r.get("caption"),
                )
                for r in rows
            ],
            answer=answer,
        )
```

---

## 4. Configuration

```python
# In Settings class
gemini_api_key: str | None = None
gemini_model: str = "gemini-2.0-flash"
gemini_max_tokens: int = 4096
rag_top_k: int = 5
```

---

## 5. Error Handling

| Scenario                | Action                                    |
|------------------------|-------------------------------------------|
| Gemini API fails        | Return images without answer              |
| Gemini timeout          | Return images without answer              |
| Image file not found    | Skip that image, continue                 |
| Fewer than 5 images     | Send whatever is available                |

---

## 6. Acceptance Criteria

- [ ] Implements `SearchApproach` interface
- [ ] Returns 5 images + coherent answer
- [ ] Answer references specific images
- [ ] Latency < 500ms (pgvector + Gemini)
- [ ] Gemini fails → returns images with `answer: None`
- [ ] Cost ≈ $0.00004 per query

---

## 7. Testing Strategy

### Unit Tests
- Mock Gemini → correct response structure
- Mock repository → returns expected images
- Empty results → returns "No images found"

### Integration Tests
- Full pipeline with real Gemini API
- Gemini timeout → graceful degradation

### Semantic Tests
- Architecture query → answer mentions buildings

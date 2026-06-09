# Spec: Approach 1 — Pure CLIP Search

> Specification for zero-cost vector similarity search using Clean Architecture strategy pattern.

---

## Metadata

| Field        | Value                       |
|-------------|------------------------------|
| **ID**      | IS-006                       |
| **Title**   | Approach 1 — Pure CLIP Search |
| **Phase**   | 3 — Search                   |
| **Status**  | Draft                        |
| **Depends** | IS-005                       |

---

## 1. Objective

Implement the simplest search approach as a `SearchApproach` strategy: pgvector cosine similarity on the `embedding` column. Zero cost, ~50ms latency.

---

## 2. Architecture

```
src/image_search/
├── domain/
│   └── search_approach.py       # Abstract SearchApproach (IS-005)
├── infrastructure/
│   └── approaches/
│       └── pure_clip.py         # PureClipApproach implementation
```

---

## 3. Detailed Design

### 3.1 Implementation

```python
# src/image_search/infrastructure/approaches/pure_clip.py
from image_search.domain.search_approach import SearchApproach, SearchResponse, SearchResult
from image_search.domain.repositories import ImageRepository

class PureClipApproach(SearchApproach):
    def __init__(self, repository: ImageRepository):
        self.repository = repository

    async def search(self, query_vector: list[float], top_k: int, query_text: str) -> SearchResponse:
        rows = await self.repository.cosine_search(
            embedding=query_vector,
            top_k=top_k,
            model_name="siglip2-384",
        )

        return SearchResponse(
            images=[
                SearchResult(
                    image_id=r["image_id"],
                    file_path=r["file_path"],
                    score=round(r["score"], 4),
                    caption=r.get("caption"),
                )
                for r in rows
            ]
        )
```

### 3.2 Repository Method

```python
# Add to ImageRepository interface
@abstractmethod
async def cosine_search(self, embedding: list[float], top_k: int, model_name: str) -> list[dict]:
    """Cosine similarity search on embedding column."""
    ...
```

```python
# PostgresImageRepository implementation
async def cosine_search(self, embedding: list[float], top_k: int, model_name: str) -> list[dict]:
    await self.session.execute("SET LOCAL hnsw.ef_search = 40")
    result = await self.session.execute(
        text("""
            SELECT image_id, file_path, caption,
                   1 - (embedding <=> :embedding) AS score
            FROM image_embeddings
            WHERE model_name = :model_name AND status = 'INDEXED'
            ORDER BY embedding <=> :embedding
            LIMIT :top_k
        """),
        {"embedding": str(embedding), "model_name": model_name, "top_k": top_k},
    )
    return [dict(row._mapping) for row in result]
```

### 3.3 SQL Query

```sql
SELECT image_id, file_path, caption,
       1 - (embedding <=> $1) AS score
FROM image_embeddings
WHERE model_name = 'siglip2-384' AND status = 'INDEXED'
ORDER BY embedding <=> $1
LIMIT $2;
```

---

## 4. Configuration

```python
# In Settings class
hnsw_ef_search: int = 40
min_score_threshold: float = 0.0
```

---

## 5. Acceptance Criteria

- [ ] Implements `SearchApproach` interface
- [ ] Searching "a red car" returns cars ranked higher than buildings
- [ ] Latency < 50ms for top-10 from 10K images
- [ ] Returns exactly `top_k` results (or fewer)
- [ ] Empty database returns `{"images": []}`
- [ ] Scores between 0.0 and 1.0, sorted descending

---

## 6. Testing Strategy

### Unit Tests
- Mock repository → returns expected results
- Empty results → returns empty list

### Integration Tests
- With seed data: "a red car" → car image as top-1
- Performance: latency < 50ms with 10K rows

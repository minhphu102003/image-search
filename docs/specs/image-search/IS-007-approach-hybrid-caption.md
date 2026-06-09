# Spec: Approach 2 — Hybrid Caption Search (RRF Fusion)

> Specification for hybrid search combining CLIP + caption embeddings using Reciprocal Rank Fusion.

---

## Metadata

| Field        | Value                              |
|-------------|-------------------------------------|
| **ID**      | IS-007                              |
| **Title**   | Approach 2 — Hybrid Caption Search  |
| **Phase**   | 3 — Search                          |
| **Status**  | Draft                               |
| **Depends** | IS-005                              |

---

## 1. Objective

Implement hybrid search as a `SearchApproach` strategy: dual pgvector search on `embedding` + `caption_embedding`, merged with Reciprocal Rank Fusion (RRF).

---

## 2. Architecture

```
src/image_search/
├── domain/
│   └── search_approach.py       # Abstract SearchApproach (IS-005)
├── infrastructure/
│   └── approaches/
│       └── hybrid_caption.py    # HybridCaptionApproach implementation
```

---

## 3. Detailed Design

### 3.1 RRF Algorithm

```python
def reciprocal_rank_fusion(
    result_lists: list[list[dict]],
    k: int = 60,
) -> list[dict]:
    """
    RRF_score(d) = sum(1 / (k + rank_i(d)))
    k=60 is the standard RRF constant.
    """
    scores: dict[str, float] = {}
    image_data: dict[str, dict] = {}

    for result_list in result_lists:
        for rank, item in enumerate(result_list, start=1):
            image_id = item["image_id"]
            rrf_score = 1.0 / (k + rank)
            scores[image_id] = scores.get(image_id, 0.0) + rrf_score
            if image_id not in image_data:
                image_data[image_id] = item

    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    return [
        {**image_data[img_id], "score": round(scores[img_id], 6)}
        for img_id in sorted_ids
    ]
```

### 3.2 Implementation

```python
# src/image_search/infrastructure/approaches/hybrid_caption.py
from image_search.domain.search_approach import SearchApproach, SearchResponse, SearchResult
from image_search.domain.repositories import ImageRepository

class HybridCaptionApproach(SearchApproach):
    def __init__(self, repository: ImageRepository, rrf_k: int = 60):
        self.repository = repository
        self.rrf_k = rrf_k

    async def search(self, query_vector: list[float], top_k: int, query_text: str) -> SearchResponse:
        # Search 1: CLIP embedding
        clip_results = await self.repository.cosine_search(
            embedding=query_vector, top_k=top_k, model_name="siglip2-384"
        )

        # Search 2: Caption embedding
        caption_results = await self.repository.caption_search(
            embedding=query_vector, top_k=top_k
        )

        # RRF fusion
        if not caption_results:
            # Fallback to CLIP only
            merged = clip_results
        else:
            merged = reciprocal_rank_fusion(
                [clip_results, caption_results], k=self.rrf_k
            )

        return SearchResponse(
            images=[
                SearchResult(
                    image_id=r["image_id"],
                    file_path=r.get("file_path", ""),
                    score=r["score"],
                    caption=r.get("caption"),
                )
                for r in merged[:top_k]
            ]
        )
```

### 3.3 Repository Methods

```python
# Add to ImageRepository interface
@abstractmethod
async def caption_search(self, embedding: list[float], top_k: int) -> list[dict]:
    """Cosine similarity search on caption_embedding column."""
    ...
```

```python
# PostgresImageRepository implementation
async def caption_search(self, embedding: list[float], top_k: int) -> list[dict]:
    await self.session.execute("SET LOCAL hnsw.ef_search = 40")
    result = await self.session.execute(
        text("""
            SELECT image_id, file_path, caption,
                   1 - (caption_embedding <=> :embedding) AS score
            FROM image_embeddings
            WHERE caption_embedding IS NOT NULL AND status = 'INDEXED'
            ORDER BY caption_embedding <=> :embedding
            LIMIT :top_k
        """),
        {"embedding": str(embedding), "top_k": top_k},
    )
    return [dict(row._mapping) for row in result]
```

---

## 4. Configuration

```python
# In Settings class
rrf_k: int = 60  # RRF constant
```

---

## 5. Acceptance Criteria

- [ ] Implements `SearchApproach` interface
- [ ] Searching "a child playing in park" → caption-relevant images rank higher
- [ ] Latency < 200ms (two pgvector queries + fusion)
- [ ] No captions → degrades to Approach 1 behavior
- [ ] RRF scores are positive floats, sorted descending

---

## 6. Testing Strategy

### Unit Tests
- `reciprocal_rank_fusion` with known inputs → expected order
- Empty caption results → returns CLIP results only
- Mock repository

### Integration Tests
- With seed data having both embeddings and captions
- Hybrid results rank caption-relevant images higher

### Performance Tests
- Dual query latency < 200ms with 10K rows

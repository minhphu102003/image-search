import time

import structlog

from image_search.domain.embedding_service import EmbeddingService
from image_search.domain.search_approach import SearchApproach, SearchResponse
from image_search.infrastructure.observability.metrics import (
    SEARCH_LATENCY,
    SEARCH_REQUESTS,
)

logger = structlog.get_logger()


class SearchImagesUseCase:
    def __init__(self, embedding_service: EmbeddingService, approaches: dict[int, SearchApproach]) -> None:
        self.embedding_service = embedding_service
        self.approaches = approaches

    async def execute(self, query: str, top_k: int, approach: int) -> tuple[SearchResponse, float]:
        start = time.time()

        query_vector = await self.embedding_service.embed_text(query)

        search_approach = self.approaches[approach]
        result = await search_approach.search(query_vector, top_k, query)

        latency_s = time.time() - start
        latency_ms = latency_s * 1000

        SEARCH_REQUESTS.labels(approach=str(approach)).inc()
        SEARCH_LATENCY.labels(approach=str(approach)).observe(latency_s)

        logger.info("search_completed", approach=approach, results=len(result.images), latency_ms=latency_ms)

        return result, latency_ms

import structlog

from image_search.domain.ports.repositories import ImageEmbeddingRepositoryPort
from image_search.domain.search_approach import SearchApproach, SearchResponse, SearchResult

logger = structlog.get_logger()


class PureClipApproach(SearchApproach):
    def __init__(self, repository: ImageEmbeddingRepositoryPort) -> None:
        self.repository = repository

    async def search(self, query_vector: list[float], top_k: int, query_text: str) -> SearchResponse:
        rows = await self.repository.search_by_embedding_with_scores(
            query_embedding=query_vector,
            limit=top_k,
        )

        images = [
            SearchResult(
                image_id=entity.image_id,
                file_path=entity.file_path,
                score=round(score, 4),
                caption=entity.caption,
            )
            for entity, score in rows
        ]

        logger.info("pure_clip_search", query_length=len(query_text), top_k=top_k, results=len(images))
        return SearchResponse(images=images)

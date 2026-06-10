import structlog

from image_search.domain.entities import ImageEmbedding
from image_search.domain.ports.repositories import ImageEmbeddingRepositoryPort
from image_search.domain.search_approach import SearchApproach, SearchResponse, SearchResult

logger = structlog.get_logger()


def reciprocal_rank_fusion(
    result_lists: list[list[tuple[ImageEmbedding, float]]],
    k: int = 60,
) -> list[tuple[ImageEmbedding, float]]:
    """RRF_score(d) = sum(1 / (k + rank_i(d))). k=60 is the standard constant."""
    scores: dict[str, float] = {}
    data: dict[str, ImageEmbedding] = {}

    for result_list in result_lists:
        for rank, (entity, _score) in enumerate(result_list, start=1):
            rrf_score = 1.0 / (k + rank)
            scores[entity.image_id] = scores.get(entity.image_id, 0.0) + rrf_score
            if entity.image_id not in data:
                data[entity.image_id] = entity

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [(data[img_id], round(scores[img_id], 6)) for img_id in sorted_ids]


class HybridCaptionApproach(SearchApproach):
    def __init__(self, repository: ImageEmbeddingRepositoryPort, rrf_k: int = 60) -> None:
        self.repository = repository
        self.rrf_k = rrf_k

    async def search(self, query_vector: list[float], top_k: int, query_text: str) -> SearchResponse:
        clip_results = await self.repository.search_by_embedding_with_scores(
            query_embedding=query_vector,
            limit=top_k,
        )

        caption_results = await self.repository.search_caption_embedding_with_scores(
            query_embedding=query_vector,
            limit=top_k,
        )

        if not caption_results:
            merged = clip_results
            logger.info("hybrid_caption_fallback", reason="no_captions", results=len(merged))
        else:
            merged = reciprocal_rank_fusion([clip_results, caption_results], k=self.rrf_k)
            logger.info(
                "hybrid_caption_search", clip=len(clip_results), caption=len(caption_results), merged=len(merged)
            )

        images = [
            SearchResult(
                image_id=entity.image_id,
                file_path=entity.file_path,
                score=score,
                caption=entity.caption,
            )
            for entity, score in merged[:top_k]
        ]

        return SearchResponse(images=images)

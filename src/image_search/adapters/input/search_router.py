from functools import lru_cache

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from image_search.adapters.output.sqlalchemy_repo import SqlAlchemyImageEmbeddingRepository
from image_search.application.search_images import SearchImagesUseCase
from image_search.domain.embedding_service import EmbeddingService
from image_search.domain.search_approach import SearchApproach
from image_search.infrastructure.config import settings
from image_search.infrastructure.database.connection import async_session
from image_search.infrastructure.observability.metrics import SEARCH_ERRORS

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["search"])


# --- Schemas ---


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


# --- Dependencies ---


@lru_cache
def get_embedding_service() -> EmbeddingService:
    if not settings.jina_api_key:
        raise ValueError("IMAGE_SEARCH_JINA_API_KEY is required")
    from image_search.infrastructure.ai.jina_service import JinaEmbeddingService

    return JinaEmbeddingService(
        api_key=settings.jina_api_key,
        model=settings.jina_model,
        api_url=settings.jina_api_url,
        dimensions=settings.jina_dimensions,
    )


def get_approaches(
    repo: SqlAlchemyImageEmbeddingRepository,
) -> dict[int, SearchApproach]:
    approaches: dict[int, SearchApproach] = {}

    try:
        from image_search.infrastructure.approaches.pure_clip import PureClipApproach

        approaches[1] = PureClipApproach(repo)
    except ImportError:
        pass

    try:
        from image_search.infrastructure.approaches.hybrid_caption import HybridCaptionApproach

        approaches[2] = HybridCaptionApproach(repo)
    except ImportError:
        pass

    try:
        from image_search.infrastructure.approaches.multimodal_rag import MultimodalRAGApproach

        if settings.gemini_api_key:
            approaches[3] = MultimodalRAGApproach(repo, settings.gemini_api_key)
    except ImportError:
        pass

    return approaches


async def _get_search_use_case() -> SearchImagesUseCase:  # type: ignore[misc]
    embedding_service = get_embedding_service()

    async with async_session() as session:
        repository = SqlAlchemyImageEmbeddingRepository(session)
        approaches = get_approaches(repository)
        yield SearchImagesUseCase(embedding_service, approaches)


# --- Endpoint ---


@router.post("/image-search", response_model=SearchResponseSchema)
async def search_images(
    req: SearchRequest,
    use_case: SearchImagesUseCase = Depends(_get_search_use_case),
) -> SearchResponseSchema:
    approach = req.approach or settings.image_search_approach

    if approach not in use_case.approaches:
        SEARCH_ERRORS.labels(error_type="invalid_approach").inc()
        raise HTTPException(status_code=400, detail=f"Approach {approach} is not available")

    logger.info("search_started", query=req.query[:80], approach=approach, top_k=req.top_k)
    result, latency_ms = await use_case.execute(req.query, req.top_k, approach)
    logger.info("search_completed", approach=approach, results=len(result.images), latency_ms=round(latency_ms, 1))

    return SearchResponseSchema(
        images=[
            ImageResult(image_id=img.image_id, file_path=img.file_path, score=img.score, caption=img.caption)
            for img in result.images
        ],
        answer=result.answer,
        approach=approach,
        latency_ms=round(latency_ms, 2),
    )

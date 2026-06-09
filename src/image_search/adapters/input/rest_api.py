from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from image_search.adapters.output.sqlalchemy_repo import SqlAlchemyImageEmbeddingRepository
from image_search.application.use_cases import (
    DeleteImageUseCase,
    GetImageUseCase,
    IngestImageUseCase,
    SearchImagesUseCase,
)
from image_search.infrastructure.database.connection import get_session

router = APIRouter(prefix="/images", tags=["images"])


def _get_repo(session: AsyncSession = Depends(get_session)) -> SqlAlchemyImageEmbeddingRepository:
    return SqlAlchemyImageEmbeddingRepository(session)


# --- Request / Response schemas ---


class IngestRequest(BaseModel):
    image_id: str
    embedding: list[float]
    file_path: str
    user_id: str
    model_name: str = "siglip2-384"
    caption: str | None = None
    caption_embedding: list[float] | None = None


class ImageResponse(BaseModel):
    id: str
    image_id: str
    file_path: str
    user_id: str
    status: str
    model_name: str
    caption: str | None


class SearchRequest(BaseModel):
    query_embedding: list[float]
    limit: int = 10
    user_id: str | None = None


# --- Endpoints ---


@router.post("/ingest", response_model=ImageResponse)
async def ingest_image(body: IngestRequest, repo: SqlAlchemyImageEmbeddingRepository = Depends(_get_repo)):
    uc = IngestImageUseCase(repo)
    entity = await uc.execute(
        image_id=body.image_id,
        embedding=body.embedding,
        file_path=body.file_path,
        user_id=body.user_id,
        model_name=body.model_name,
        caption=body.caption,
        caption_embedding=body.caption_embedding,
    )
    return ImageResponse(
        id=entity.id,
        image_id=entity.image_id,
        file_path=entity.file_path,
        user_id=entity.user_id,
        status=entity.status.value,
        model_name=entity.model_name,
        caption=entity.caption,
    )


@router.post("/search", response_model=list[ImageResponse])
async def search_images(body: SearchRequest, repo: SqlAlchemyImageEmbeddingRepository = Depends(_get_repo)):
    uc = SearchImagesUseCase(repo)
    results = await uc.execute(query_embedding=body.query_embedding, limit=body.limit, user_id=body.user_id)
    return [
        ImageResponse(
            id=e.id,
            image_id=e.image_id,
            file_path=e.file_path,
            user_id=e.user_id,
            status=e.status.value,
            model_name=e.model_name,
            caption=e.caption,
        )
        for e in results
    ]


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(image_id: str, repo: SqlAlchemyImageEmbeddingRepository = Depends(_get_repo)):
    uc = GetImageUseCase(repo)
    entity = await uc.execute(image_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return ImageResponse(
        id=entity.id,
        image_id=entity.image_id,
        file_path=entity.file_path,
        user_id=entity.user_id,
        status=entity.status.value,
        model_name=entity.model_name,
        caption=entity.caption,
    )


@router.delete("/{image_id}")
async def delete_image(image_id: str, repo: SqlAlchemyImageEmbeddingRepository = Depends(_get_repo)):
    uc = DeleteImageUseCase(repo)
    deleted = await uc.execute(image_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"deleted": True}

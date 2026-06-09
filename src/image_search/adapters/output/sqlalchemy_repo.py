from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from image_search.domain.entities import ImageEmbedding, ImageStatus
from image_search.domain.ports.repositories import ImageEmbeddingRepositoryPort
from image_search.infrastructure.database.models import ImageEmbeddingModel


def _to_entity(model: ImageEmbeddingModel) -> ImageEmbedding:
    return ImageEmbedding(
        id=model.id,
        image_id=model.image_id,
        embedding=list(model.embedding),
        caption_embedding=list(model.caption_embedding) if model.caption_embedding is not None else None,
        model_name=model.model_name,
        caption=model.caption,
        file_path=model.file_path,
        user_id=model.user_id,
        status=ImageStatus(model.status),
        error_message=model.error_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_model(entity: ImageEmbedding) -> ImageEmbeddingModel:
    return ImageEmbeddingModel(
        id=entity.id,
        image_id=entity.image_id,
        embedding=entity.embedding,
        caption_embedding=entity.caption_embedding,
        model_name=entity.model_name,
        caption=entity.caption,
        file_path=entity.file_path,
        user_id=entity.user_id,
        status=entity.status.value,
        error_message=entity.error_message,
    )


class SqlAlchemyImageEmbeddingRepository(ImageEmbeddingRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, entity: ImageEmbedding) -> ImageEmbedding:
        existing = await self.session.execute(
            select(ImageEmbeddingModel).where(ImageEmbeddingModel.image_id == entity.image_id)
        )
        found = existing.scalar_one_or_none()

        if found is not None:
            found.embedding = entity.embedding
            found.caption_embedding = entity.caption_embedding
            found.model_name = entity.model_name
            found.caption = entity.caption
            found.file_path = entity.file_path
            found.user_id = entity.user_id
            found.status = entity.status.value
            found.error_message = entity.error_message
            await self.session.flush()
            return _to_entity(found)

        model = _to_model(entity)
        self.session.add(model)
        await self.session.flush()
        return _to_entity(model)

    async def get_by_image_id(self, image_id: str) -> ImageEmbedding | None:
        result = await self.session.execute(
            select(ImageEmbeddingModel).where(ImageEmbeddingModel.image_id == image_id)
        )
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def search_by_embedding(
        self, query_embedding: list[float], limit: int = 10, user_id: str | None = None
    ) -> list[ImageEmbedding]:
        distance = ImageEmbeddingModel.embedding.cosine_distance(query_embedding)
        stmt = (
            select(ImageEmbeddingModel)
            .where(ImageEmbeddingModel.status == "INDEXED")
            .order_by(distance)
            .limit(limit)
        )
        if user_id is not None:
            stmt = stmt.where(ImageEmbeddingModel.user_id == user_id)

        result = await self.session.execute(stmt)
        return [_to_entity(m) for m in result.scalars().all()]

    async def delete_by_image_id(self, image_id: str) -> bool:
        result = await self.session.execute(
            select(ImageEmbeddingModel).where(ImageEmbeddingModel.image_id == image_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return False
        await self.session.delete(model)
        return True

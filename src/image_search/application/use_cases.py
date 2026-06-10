import uuid
from datetime import datetime, timezone

from image_search.domain.entities import ImageEmbedding, ImageStatus
from image_search.domain.ports.repositories import ImageEmbeddingRepositoryPort


class IngestImageUseCase:
    def __init__(self, repo: ImageEmbeddingRepositoryPort) -> None:
        self.repo = repo

    async def execute(
        self,
        image_id: str,
        embedding: list[float],
        file_path: str,
        user_id: str,
        model_name: str = "jina-embeddings-v4",
        caption: str | None = None,
        caption_embedding: list[float] | None = None,
    ) -> ImageEmbedding:
        now = datetime.now(tz=timezone.utc)
        entity = ImageEmbedding(
            id=str(uuid.uuid4()),
            image_id=image_id,
            embedding=embedding,
            caption_embedding=caption_embedding,
            model_name=model_name,
            caption=caption,
            file_path=file_path,
            user_id=user_id,
            status=ImageStatus.INDEXED if caption is not None else ImageStatus.EMBEDDED,
            error_message=None,
            created_at=now,
            updated_at=now,
        )
        return await self.repo.save(entity)


class SearchImagesUseCase:
    def __init__(self, repo: ImageEmbeddingRepositoryPort) -> None:
        self.repo = repo

    async def execute(
        self,
        query_embedding: list[float],
        limit: int = 10,
        user_id: str | None = None,
    ) -> list[ImageEmbedding]:
        return await self.repo.search_by_embedding(query_embedding, limit=limit, user_id=user_id)


class GetImageUseCase:
    def __init__(self, repo: ImageEmbeddingRepositoryPort) -> None:
        self.repo = repo

    async def execute(self, image_id: str) -> ImageEmbedding | None:
        return await self.repo.get_by_image_id(image_id)


class DeleteImageUseCase:
    def __init__(self, repo: ImageEmbeddingRepositoryPort) -> None:
        self.repo = repo

    async def execute(self, image_id: str) -> bool:
        return await self.repo.delete_by_image_id(image_id)

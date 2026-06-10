from abc import ABC, abstractmethod

from image_search.domain.entities import ImageEmbedding


class ImageEmbeddingRepositoryPort(ABC):
    @abstractmethod
    async def save(self, entity: ImageEmbedding) -> ImageEmbedding:
        raise NotImplementedError

    @abstractmethod
    async def get_by_image_id(self, image_id: str) -> ImageEmbedding | None:
        raise NotImplementedError

    @abstractmethod
    async def search_by_embedding(
        self, query_embedding: list[float], limit: int = 10, user_id: str | None = None
    ) -> list[ImageEmbedding]:
        raise NotImplementedError

    @abstractmethod
    async def delete_by_image_id(self, image_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def update_status(self, image_id: str, status: str, error: str | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update_caption(self, image_id: str, caption: str, caption_embedding: list[float]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def search_by_embedding_with_scores(
        self, query_embedding: list[float], limit: int = 10, user_id: str | None = None
    ) -> list[tuple[ImageEmbedding, float]]:
        raise NotImplementedError

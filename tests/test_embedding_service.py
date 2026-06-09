from unittest.mock import AsyncMock

import pytest

from image_search.domain.embedding_service import EmbeddingService


class TestEmbeddingServiceInterface:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            EmbeddingService()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_mock_embed_image(self) -> None:
        service = AsyncMock(spec=EmbeddingService)
        service.embed_image.return_value = [0.1] * 1024

        result = await service.embed_image("/path/to/image.jpg")
        assert len(result) == 1024
        assert all(isinstance(v, float) for v in result)
        service.embed_image.assert_awaited_once_with("/path/to/image.jpg")

    @pytest.mark.asyncio
    async def test_mock_embed_text(self) -> None:
        service = AsyncMock(spec=EmbeddingService)
        service.embed_text.return_value = [0.2] * 1024

        result = await service.embed_text("a red car")
        assert len(result) == 1024
        service.embed_text.assert_awaited_once_with("a red car")

    @pytest.mark.asyncio
    async def test_mock_embed_images_batch(self) -> None:
        service = AsyncMock(spec=EmbeddingService)
        service.embed_images_batch.return_value = [[0.1] * 1024, [0.2] * 1024]

        result = await service.embed_images_batch(["/a.jpg", "/b.jpg"])
        assert len(result) == 2
        assert all(len(v) == 1024 for v in result)

    @pytest.mark.asyncio
    async def test_mock_embed_texts_batch(self) -> None:
        service = AsyncMock(spec=EmbeddingService)
        service.embed_texts_batch.return_value = [[0.1] * 1024, [0.2] * 1024]

        result = await service.embed_texts_batch(["a red car", "a blue sky"])
        assert len(result) == 2
        assert all(len(v) == 1024 for v in result)

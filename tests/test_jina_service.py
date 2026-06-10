from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from image_search.infrastructure.ai.jina_service import JinaEmbeddingService


def _fake_embedding(dim: int = 1024) -> list[float]:
    return [0.1] * dim


def _fake_api_response(embeddings: list[list[float]]) -> dict:
    return {"data": [{"embedding": emb} for emb in embeddings]}


class TestJinaEmbeddingService:
    @pytest.fixture
    def service(self) -> JinaEmbeddingService:
        return JinaEmbeddingService(
            api_key="test-key",
            model="jina-embeddings-v4",
            api_url="https://api.jina.ai/v1/embeddings",
            dimensions=1024,
        )

    @pytest.mark.asyncio
    async def test_embed_text(self, service: JinaEmbeddingService) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = _fake_api_response([_fake_embedding()])

        with patch.object(service._client, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            result = await service.embed_text("a red car")

        assert len(result) == 1024
        assert all(isinstance(v, float) for v in result)
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["task"] == "retrieval.query"
        assert payload["input"] == [{"text": "a red car"}]

    @pytest.mark.asyncio
    async def test_embed_image_url(self, service: JinaEmbeddingService) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = _fake_api_response([_fake_embedding()])

        with patch.object(service._client, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            result = await service.embed_image("https://example.com/image.jpg")

        assert len(result) == 1024
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["task"] == "retrieval.passage"
        assert payload["input"] == [{"image": "https://example.com/image.jpg"}]

    @pytest.mark.asyncio
    async def test_embed_image_local_file(self, service: JinaEmbeddingService, tmp_path) -> None:
        # Create a fake image file
        fake_image = tmp_path / "test.jpg"
        fake_image.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # Minimal JPEG header

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = _fake_api_response([_fake_embedding()])

        with patch.object(service._client, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            result = await service.embed_image(str(fake_image))

        assert len(result) == 1024
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["task"] == "retrieval.passage"
        # Should be base64 encoded
        assert payload["input"][0]["image"].startswith("data:image/jpeg;base64,")

    @pytest.mark.asyncio
    async def test_embed_texts_batch(self, service: JinaEmbeddingService) -> None:
        texts = ["a red car", "a blue sky", "a green tree"]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = _fake_api_response([_fake_embedding() for _ in texts])

        with patch.object(service._client, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            results = await service.embed_texts_batch(texts)

        assert len(results) == 3
        assert all(len(r) == 1024 for r in results)
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["task"] == "retrieval.query"
        assert len(payload["input"]) == 3

    @pytest.mark.asyncio
    async def test_embed_images_batch_urls(self, service: JinaEmbeddingService) -> None:
        urls = ["https://example.com/a.jpg", "https://example.com/b.jpg"]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = _fake_api_response([_fake_embedding() for _ in urls])

        with patch.object(service._client, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            results = await service.embed_images_batch(urls)

        assert len(results) == 2
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["task"] == "retrieval.passage"
        assert payload["input"] == [{"image": u} for u in urls]

    @pytest.mark.asyncio
    async def test_api_429_raises(self, service: JinaEmbeddingService) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=mock_resp
        )

        with patch.object(service._client, "post", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(httpx.HTTPStatusError):
                await service.embed_text("test")

    @pytest.mark.asyncio
    async def test_api_500_raises(self, service: JinaEmbeddingService) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=mock_resp
        )

        with patch.object(service._client, "post", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(httpx.HTTPStatusError):
                await service.embed_text("test")

    @pytest.mark.asyncio
    async def test_api_timeout_raises(self, service: JinaEmbeddingService) -> None:
        with patch.object(
            service._client, "post", new_callable=AsyncMock, side_effect=httpx.TimeoutException("Timeout")
        ):
            with pytest.raises(httpx.TimeoutException):
                await service.embed_text("test")

    @pytest.mark.asyncio
    async def test_close(self, service: JinaEmbeddingService) -> None:
        with patch.object(service._client, "aclose", new_callable=AsyncMock) as mock_close:
            await service.close()
            mock_close.assert_called_once()


class TestJinaConfig:
    def test_jina_requires_api_key(self) -> None:
        from image_search.infrastructure.config import Settings

        settings = Settings(jina_api_key=None)
        assert settings.jina_api_key is None

    def test_jina_with_api_key(self) -> None:
        from image_search.infrastructure.config import Settings

        settings = Settings(jina_api_key="test-key")
        assert settings.jina_api_key == "test-key"

    def test_default_jina_config(self) -> None:
        from image_search.infrastructure.config import Settings

        settings = Settings()
        assert settings.jina_model == "jina-embeddings-v4"
        assert settings.jina_dimensions == 1024
        assert settings.jina_api_url == "https://api.jina.ai/v1/embeddings"

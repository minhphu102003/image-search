from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from image_search.adapters.output.http_client import (
    ImageSearchClient,
    ImageSearchResult,
)


def _success_response(data: dict) -> httpx.Response:
    return httpx.Response(status_code=200, json=data, request=httpx.Request("POST", "http://test/api"))


def _error_response(status: int = 500) -> httpx.Response:
    return httpx.Response(status_code=status, request=httpx.Request("POST", "http://test/api"))


_SEARCH_DATA = {
    "images": [
        {"image_id": "img-1", "file_path": "/a.jpg", "score": 0.85, "caption": "a cat"},
        {"image_id": "img-2", "file_path": "/b.jpg", "score": 0.72, "caption": None},
    ],
    "answer": "The images show cats.",
    "approach": 3,
    "latency_ms": 423.5,
}


class TestImageSearchClient:
    @pytest.mark.asyncio
    async def test_returns_parsed_result_on_success(self) -> None:
        client = ImageSearchClient(base_url="http://search:8000", timeout=5.0)

        mock_response = _success_response(_SEARCH_DATA)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.search("cats playing")

        assert isinstance(result, ImageSearchResult)
        assert len(result.images) == 2
        assert result.images[0].image_id == "img-1"
        assert result.images[0].score == 0.85
        assert result.images[0].caption == "a cat"
        assert result.images[1].caption is None
        assert result.answer == "The images show cats."
        assert result.approach == 3
        assert result.latency_ms == 423.5

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self) -> None:
        client = ImageSearchClient(base_url="http://search:8000", default_approach=2, default_top_k=10)

        mock_response = _success_response(_SEARCH_DATA)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await client.search("test query")

        mock_post.assert_awaited_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"] == {"query": "test query", "top_k": 10, "approach": 2}

    @pytest.mark.asyncio
    async def test_custom_top_k_and_approach_override_defaults(self) -> None:
        client = ImageSearchClient(base_url="http://search:8000", default_approach=1, default_top_k=5)

        mock_response = _success_response(_SEARCH_DATA)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await client.search("test", top_k=20, approach=3)

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"] == {"query": "test", "top_k": 20, "approach": 3}

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_result(self) -> None:
        client = ImageSearchClient(base_url="http://search:8000")

        mock_response = _error_response(500)
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error",
                request=httpx.Request("POST", "http://test"),
                response=mock_response,
            )
        )
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.search("test")

        assert result.images == []
        assert result.answer is None

    @pytest.mark.asyncio
    async def test_timeout_returns_empty_result(self) -> None:
        client = ImageSearchClient(base_url="http://search:8000")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.TimeoutException("timed out")):
            result = await client.search("test")

        assert result.images == []
        assert result.answer is None

    @pytest.mark.asyncio
    async def test_connection_error_returns_empty_result(self) -> None:
        client = ImageSearchClient(base_url="http://search:8000")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.ConnectError("refused")):
            result = await client.search("test")

        assert result.images == []
        assert result.answer is None

    @pytest.mark.asyncio
    async def test_empty_images_in_response(self) -> None:
        client = ImageSearchClient(base_url="http://search:8000")

        data = {"images": [], "answer": None, "approach": 1, "latency_ms": 50.0}
        mock_response = _success_response(data)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.search("obscure query")

        assert result.images == []
        assert result.answer is None

    @pytest.mark.asyncio
    async def test_strips_trailing_slash_from_base_url(self) -> None:
        client = ImageSearchClient(base_url="http://search:8000/")

        mock_response = _success_response(_SEARCH_DATA)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await client.search("test")

        # Verify base_url trailing slash was stripped
        assert client.base_url == "http://search:8000"
        assert "/api/v1/image-search" in str(mock_post.call_args)

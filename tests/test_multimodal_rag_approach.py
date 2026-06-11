from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from image_search.domain.entities import ImageEmbedding, ImageStatus
from image_search.domain.search_approach import SearchApproach, SearchResponse
from image_search.infrastructure.approaches.multimodal_rag import MultimodalRAGApproach

_NOW = datetime.now(timezone.utc)

_MOCK_MODULES = {
    "google": MagicMock(),
    "google.genai": MagicMock(),
    "google.genai.types": MagicMock(),
    "PIL": MagicMock(),
    "PIL.Image": MagicMock(),
}


def _emb(image_id: str, file_path: str = "/img.jpg", caption: str | None = None) -> ImageEmbedding:
    return ImageEmbedding(
        id=f"id-{image_id}",
        image_id=image_id,
        embedding=[0.1] * 1024,
        caption_embedding=None,
        model_name="jina-embeddings-v4",
        caption=caption,
        file_path=file_path,
        user_id="user-1",
        status=ImageStatus.INDEXED,
        error_message=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_approach(repo: AsyncMock) -> MultimodalRAGApproach:
    with patch.dict("sys.modules", _MOCK_MODULES):
        return MultimodalRAGApproach(repo, gemini_api_key="test-key")


def _set_gemini_response(approach: MultimodalRAGApproach, text: str) -> None:
    mock_aio = MagicMock()
    mock_aio.models.generate_content = AsyncMock(return_value=SimpleNamespace(text=text))
    approach.client.aio = mock_aio


def _set_gemini_failure(approach: MultimodalRAGApproach, error: str = "API error") -> None:
    mock_aio = MagicMock()
    mock_aio.models.generate_content = AsyncMock(side_effect=Exception(error))
    approach.client.aio = mock_aio


class TestMultimodalRAGApproach:
    @pytest.mark.asyncio
    async def test_returns_images_and_answer(self) -> None:
        repo = AsyncMock()
        repo.search_by_embedding_with_scores = AsyncMock(
            return_value=[
                (_emb("a", "/a.jpg", "a car"), 0.9),
                (_emb("b", "/b.jpg", "a building"), 0.7),
            ]
        )
        approach = _make_approach(repo)
        _set_gemini_response(approach, "Image 1 shows a car.")

        with patch.object(approach, "_load_images", return_value=[MagicMock()]):
            result = await approach.search([0.1] * 1024, top_k=10, query_text="What is in the images?")

        assert isinstance(result, SearchResponse)
        assert len(result.images) == 2
        assert result.images[0].image_id == "a"
        assert result.images[0].score == 0.9
        assert result.answer == "Image 1 shows a car."

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty(self) -> None:
        repo = AsyncMock()
        repo.search_by_embedding_with_scores = AsyncMock(return_value=[])
        approach = _make_approach(repo)

        result = await approach.search([0.1] * 1024, top_k=10, query_text="test")

        assert result.images == []
        assert result.answer is None

    @pytest.mark.asyncio
    async def test_gemini_failure_returns_images_without_answer(self) -> None:
        repo = AsyncMock()
        repo.search_by_embedding_with_scores = AsyncMock(return_value=[(_emb("a", "/a.jpg"), 0.9)])
        approach = _make_approach(repo)
        _set_gemini_failure(approach)

        with patch.object(approach, "_load_images", return_value=[MagicMock()]):
            result = await approach.search([0.1] * 1024, top_k=10, query_text="test")

        assert len(result.images) == 1
        assert result.answer is None

    @pytest.mark.asyncio
    async def test_no_loadable_images_returns_none_answer(self) -> None:
        repo = AsyncMock()
        repo.search_by_embedding_with_scores = AsyncMock(return_value=[(_emb("a", "/bad.jpg"), 0.9)])
        approach = _make_approach(repo)

        with patch.object(approach, "_load_images", return_value=[]):
            result = await approach.search([0.1] * 1024, top_k=10, query_text="test")

        assert len(result.images) == 1
        assert result.answer is None

    @pytest.mark.asyncio
    async def test_implements_search_approach_interface(self) -> None:
        repo = AsyncMock()
        approach = _make_approach(repo)
        assert isinstance(approach, SearchApproach)

    @pytest.mark.asyncio
    async def test_passes_top_k_retrieve_to_repo(self) -> None:
        repo = AsyncMock()
        repo.search_by_embedding_with_scores = AsyncMock(return_value=[])
        approach = _make_approach(repo)
        approach.top_k_retrieve = 5

        await approach.search([0.1] * 1024, top_k=10, query_text="test")

        repo.search_by_embedding_with_scores.assert_awaited_once_with(
            query_embedding=[0.1] * 1024,
            limit=5,
        )

    @pytest.mark.asyncio
    async def test_calls_gemini_with_query_and_images(self) -> None:
        repo = AsyncMock()
        repo.search_by_embedding_with_scores = AsyncMock(return_value=[(_emb("a", "/a.jpg"), 0.9)])
        approach = _make_approach(repo)
        _set_gemini_response(approach, "test answer")

        mock_images = [MagicMock(), MagicMock()]
        with patch.object(approach, "_load_images", return_value=mock_images):
            await approach.search([0.1] * 1024, top_k=10, query_text="What is this?")

        approach.client.aio.models.generate_content.assert_awaited_once()
        call_kwargs = approach.client.aio.models.generate_content.call_args.kwargs
        contents = call_kwargs["contents"]
        assert "What is this?" in contents[0]
        assert len(contents) == 3  # prompt + 2 images

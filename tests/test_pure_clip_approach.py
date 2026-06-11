from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from image_search.domain.entities import ImageEmbedding, ImageStatus
from image_search.domain.search_approach import SearchResponse
from image_search.infrastructure.approaches.pure_clip import PureClipApproach

_NOW = datetime.now(timezone.utc)


def _make_embedding(image_id: str, file_path: str = "/img.jpg", caption: str | None = None) -> ImageEmbedding:
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


class TestPureClipApproach:
    @pytest.mark.asyncio
    async def test_returns_mapped_results(self) -> None:
        repo = AsyncMock()
        repo.search_by_embedding_with_scores = AsyncMock(
            return_value=[
                (_make_embedding("img-1", "/car.jpg", "a red car"), 0.9234),
                (_make_embedding("img-2", "/building.jpg"), 0.7456),
            ]
        )
        approach = PureClipApproach(repo)

        result = await approach.search([0.1] * 1024, top_k=10, query_text="a red car")

        assert isinstance(result, SearchResponse)
        assert len(result.images) == 2
        assert result.images[0].image_id == "img-1"
        assert result.images[0].file_path == "/car.jpg"
        assert result.images[0].score == 0.9234
        assert result.images[0].caption == "a red car"
        assert result.images[1].image_id == "img-2"
        assert result.images[1].score == 0.7456
        assert result.images[1].caption is None
        assert result.answer is None

        repo.search_by_embedding_with_scores.assert_awaited_once_with(
            query_embedding=[0.1] * 1024,
            limit=10,
        )

    @pytest.mark.asyncio
    async def test_filters_low_scores_below_threshold(self) -> None:
        repo = AsyncMock()
        repo.search_by_embedding_with_scores = AsyncMock(
            return_value=[
                (_make_embedding("img-1", "/car.jpg"), 0.9),
                (_make_embedding("img-2", "/noise.jpg"), 0.3),
            ]
        )
        approach = PureClipApproach(repo)

        with patch("image_search.infrastructure.approaches.pure_clip.settings") as mock_settings:
            mock_settings.min_score_threshold = 0.5
            result = await approach.search([0.1] * 1024, top_k=10, query_text="test")

        assert len(result.images) == 1
        assert result.images[0].image_id == "img-1"

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        repo = AsyncMock()
        repo.search_by_embedding_with_scores = AsyncMock(return_value=[])
        approach = PureClipApproach(repo)

        result = await approach.search([0.1] * 1024, top_k=10, query_text="nothing")

        assert result.images == []
        assert result.answer is None

    @pytest.mark.asyncio
    async def test_scores_are_rounded_to_4_decimals(self) -> None:
        repo = AsyncMock()
        repo.search_by_embedding_with_scores = AsyncMock(
            return_value=[
                (_make_embedding("img-1"), 0.923456789),
            ]
        )
        approach = PureClipApproach(repo)

        result = await approach.search([0.1] * 1024, top_k=1, query_text="test")

        assert result.images[0].score == 0.9235

    @pytest.mark.asyncio
    async def test_passes_top_k_to_repo(self) -> None:
        repo = AsyncMock()
        repo.search_by_embedding_with_scores = AsyncMock(return_value=[])
        approach = PureClipApproach(repo)

        await approach.search([0.1] * 1024, top_k=5, query_text="test")

        repo.search_by_embedding_with_scores.assert_awaited_once_with(
            query_embedding=[0.1] * 1024,
            limit=5,
        )

    @pytest.mark.asyncio
    async def test_implements_search_approach_interface(self) -> None:
        from image_search.domain.search_approach import SearchApproach

        repo = AsyncMock()
        approach = PureClipApproach(repo)
        assert isinstance(approach, SearchApproach)

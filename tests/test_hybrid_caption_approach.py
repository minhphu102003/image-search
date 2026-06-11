from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from image_search.domain.entities import ImageEmbedding, ImageStatus
from image_search.domain.search_approach import SearchApproach, SearchResponse
from image_search.infrastructure.approaches.hybrid_caption import (
    HybridCaptionApproach,
    reciprocal_rank_fusion,
)

_NOW = datetime.now(timezone.utc)


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


# --- RRF algorithm tests ---


class TestReciprocalRankFusion:
    def test_single_list_identity(self) -> None:
        items = [(_emb("a"), 0.9), (_emb("b"), 0.8)]
        result = reciprocal_rank_fusion([items], k=60)
        assert len(result) == 2
        assert result[0][0].image_id == "a"
        assert result[1][0].image_id == "b"
        # RRF: rank 1 -> 1/(60+1) ≈ 0.01639, rank 2 -> 1/(60+2) ≈ 0.01613
        assert result[0][1] > result[1][1]

    def test_two_lists_merge(self) -> None:
        list1 = [(_emb("a"), 0.9), (_emb("b"), 0.8)]
        list2 = [(_emb("b"), 0.7), (_emb("c"), 0.6)]
        result = reciprocal_rank_fusion([list1, list2], k=60)
        ids = [r[0].image_id for r in result]
        # b appears in both lists -> highest RRF score
        assert ids[0] == "b"

    def test_empty_lists(self) -> None:
        result = reciprocal_rank_fusion([], k=60)
        assert result == []

    def test_one_empty_one_populated(self) -> None:
        items = [(_emb("a"), 0.9)]
        result = reciprocal_rank_fusion([[], items], k=60)
        assert len(result) == 1
        assert result[0][0].image_id == "a"

    def test_scores_are_positive_and_sorted_desc(self) -> None:
        list1 = [(_emb("a"), 0.9), (_emb("b"), 0.8), (_emb("c"), 0.7)]
        list2 = [(_emb("c"), 0.95), (_emb("a"), 0.85)]
        result = reciprocal_rank_fusion([list1, list2], k=60)
        scores = [r[1] for r in result]
        assert all(s > 0 for s in scores)
        assert scores == sorted(scores, reverse=True)


# --- HybridCaptionApproach tests ---


def _make_session_factory(clip_return, caption_return):
    """Create a mock session factory that returns repos with configured search results."""
    mock_repo = AsyncMock()
    mock_repo.search_by_embedding_with_scores = AsyncMock(return_value=clip_return)
    mock_repo.search_caption_embedding_with_scores = AsyncMock(return_value=caption_return)

    @asynccontextmanager
    async def _session_ctx():
        yield AsyncMock()

    # MagicMock because async_sessionmaker.__call__ is sync (returns async ctx mgr)
    factory = MagicMock(side_effect=_session_ctx)

    patcher = patch(
        "image_search.infrastructure.approaches.hybrid_caption.SqlAlchemyImageEmbeddingRepository",
        return_value=mock_repo,
    )
    patcher.start()
    return factory, patcher


class TestHybridCaptionApproach:
    @pytest.mark.asyncio
    async def test_fuses_clip_and_caption_results(self) -> None:
        clip = [(_emb("a", "/a.jpg", "car"), 0.9), (_emb("b", "/b.jpg"), 0.7)]
        caption = [(_emb("b", "/b.jpg"), 0.95), (_emb("c", "/c.jpg", "vehicle"), 0.6)]
        factory, patcher = _make_session_factory(clip, caption)
        try:
            approach = HybridCaptionApproach(factory, rrf_k=60)
            result = await approach.search([0.1] * 1024, top_k=10, query_text="a red car")

            assert isinstance(result, SearchResponse)
            ids = [img.image_id for img in result.images]
            assert ids[0] == "b"
            assert len(result.images) == 3
            assert result.answer is None
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_fallback_to_clip_when_no_captions(self) -> None:
        clip = [(_emb("a", "/a.jpg"), 0.9), (_emb("b", "/b.jpg"), 0.7)]
        factory, patcher = _make_session_factory(clip, [])
        try:
            approach = HybridCaptionApproach(factory, rrf_k=60)
            result = await approach.search([0.1] * 1024, top_k=10, query_text="test")

            assert len(result.images) == 2
            assert result.images[0].image_id == "a"
            assert result.images[0].score == 0.9
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_respects_top_k_limit(self) -> None:
        clip = [(_emb(f"clip-{i}"), 0.9 - i * 0.01) for i in range(20)]
        caption = [(_emb(f"cap-{i}"), 0.8 - i * 0.01) for i in range(20)]
        factory, patcher = _make_session_factory(clip, caption)
        try:
            approach = HybridCaptionApproach(factory, rrf_k=60)
            result = await approach.search([0.1] * 1024, top_k=5, query_text="test")

            assert len(result.images) == 5
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_implements_search_approach_interface(self) -> None:
        factory, patcher = _make_session_factory([], [])
        try:
            approach = HybridCaptionApproach(factory)
            assert isinstance(approach, SearchApproach)
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_empty_database_returns_empty(self) -> None:
        factory, patcher = _make_session_factory([], [])
        try:
            approach = HybridCaptionApproach(factory)
            result = await approach.search([0.1] * 1024, top_k=10, query_text="test")

            assert result.images == []
        finally:
            patcher.stop()

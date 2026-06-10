from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from image_search.application.search_images import SearchImagesUseCase
from image_search.domain.search_approach import SearchApproach, SearchResponse, SearchResult


# --- Domain interface tests ---


class TestSearchApproachInterface:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            SearchApproach()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_mock_search(self) -> None:
        approach = AsyncMock(spec=SearchApproach)
        approach.search.return_value = SearchResponse(
            images=[SearchResult(image_id="img-1", file_path="/a.jpg", score=0.95)],
            answer=None,
        )

        result = await approach.search([0.1] * 1024, 10, "a red car")
        assert len(result.images) == 1
        assert result.images[0].score == 0.95
        approach.search.assert_awaited_once()


# --- Use case tests ---


class TestSearchImagesUseCase:
    @pytest.mark.asyncio
    async def test_execute_embeds_and_delegates(self) -> None:
        embedding_service = AsyncMock()
        embedding_service.embed_text = AsyncMock(return_value=[0.1] * 1024)

        approach = AsyncMock(spec=SearchApproach)
        approach.search.return_value = SearchResponse(
            images=[SearchResult(image_id="img-1", file_path="/a.jpg", score=0.9)],
        )

        use_case = SearchImagesUseCase(embedding_service=embedding_service, approaches={1: approach})
        result, latency_ms = await use_case.execute("a red car", top_k=5, approach=1)

        embedding_service.embed_text.assert_awaited_once_with("a red car")
        approach.search.assert_awaited_once_with([0.1] * 1024, 5, "a red car")
        assert len(result.images) == 1
        assert latency_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_invalid_approach_raises(self) -> None:
        embedding_service = AsyncMock()
        embedding_service.embed_text = AsyncMock(return_value=[0.1] * 1024)

        use_case = SearchImagesUseCase(embedding_service=embedding_service, approaches={1: AsyncMock()})

        with pytest.raises(KeyError):
            await use_case.execute("a red car", top_k=5, approach=99)


# --- API tests ---


@pytest.fixture
def mock_use_case() -> AsyncMock:
    use_case = AsyncMock(spec=SearchImagesUseCase)
    use_case.approaches = {1: AsyncMock()}
    use_case.execute = AsyncMock(
        return_value=(SearchResponse(images=[]), 1.5),
    )
    return use_case


@pytest.mark.asyncio
async def test_api_empty_query_returns_422(mock_use_case: AsyncMock) -> None:
    from image_search.adapters.input.app import app
    from image_search.adapters.input.search_router import _get_search_use_case

    async def _override() -> AsyncMock:
        return mock_use_case

    app.dependency_overrides[_get_search_use_case] = _override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/image-search", json={"query": ""})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_top_k_zero_returns_422(mock_use_case: AsyncMock) -> None:
    from image_search.adapters.input.app import app
    from image_search.adapters.input.search_router import _get_search_use_case

    async def _override() -> AsyncMock:
        return mock_use_case

    app.dependency_overrides[_get_search_use_case] = _override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/image-search", json={"query": "car", "top_k": 0})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_top_k_over_100_returns_422(mock_use_case: AsyncMock) -> None:
    from image_search.adapters.input.app import app
    from image_search.adapters.input.search_router import _get_search_use_case

    async def _override() -> AsyncMock:
        return mock_use_case

    app.dependency_overrides[_get_search_use_case] = _override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/image-search", json={"query": "car", "top_k": 101})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_search_returns_200(mock_use_case: AsyncMock) -> None:
    from image_search.adapters.input.app import app
    from image_search.adapters.input.search_router import _get_search_use_case

    async def _override() -> AsyncMock:
        return mock_use_case

    app.dependency_overrides[_get_search_use_case] = _override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/image-search", json={"query": "a red car", "top_k": 5})
        assert resp.status_code == 200
        body = resp.json()
        assert body["approach"] == 1
        assert body["latency_ms"] >= 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_health_endpoint() -> None:
    from unittest.mock import AsyncMock, patch

    from image_search.adapters.input.app import app

    with (
        patch("image_search.adapters.input.health._check_redis", new_callable=AsyncMock, return_value="ok"),
        patch("image_search.adapters.input.health._check_postgresql", new_callable=AsyncMock, return_value="ok"),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["redis"] == "ok"
    assert body["checks"]["postgresql"] == "ok"

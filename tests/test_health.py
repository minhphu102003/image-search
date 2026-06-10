from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from image_search.infrastructure.observability.metrics import SEARCH_LATENCY, SEARCH_REQUESTS


def _make_client() -> TestClient:
    from image_search.adapters.input.app import app

    return TestClient(app)


class TestHealthEndpoint:
    def test_returns_ok_when_all_healthy(self) -> None:
        with (
            patch("image_search.adapters.input.health._check_redis", new_callable=AsyncMock, return_value="ok"),
            patch("image_search.adapters.input.health._check_postgresql", new_callable=AsyncMock, return_value="ok"),
        ):
            client = _make_client()
            response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["checks"]["redis"] == "ok"
        assert data["checks"]["postgresql"] == "ok"

    def test_returns_degraded_when_redis_down(self) -> None:
        with (
            patch("image_search.adapters.input.health._check_redis", new_callable=AsyncMock, return_value="error"),
            patch("image_search.adapters.input.health._check_postgresql", new_callable=AsyncMock, return_value="ok"),
        ):
            client = _make_client()
            response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["redis"] == "error"
        assert data["checks"]["postgresql"] == "ok"

    def test_returns_degraded_when_pg_down(self) -> None:
        with (
            patch("image_search.adapters.input.health._check_redis", new_callable=AsyncMock, return_value="ok"),
            patch("image_search.adapters.input.health._check_postgresql", new_callable=AsyncMock, return_value="error"),
        ):
            client = _make_client()
            response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["redis"] == "ok"
        assert data["checks"]["postgresql"] == "error"

    def test_returns_degraded_when_all_down(self) -> None:
        with (
            patch("image_search.adapters.input.health._check_redis", new_callable=AsyncMock, return_value="error"),
            patch("image_search.adapters.input.health._check_postgresql", new_callable=AsyncMock, return_value="error"),
        ):
            client = _make_client()
            response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["redis"] == "error"
        assert data["checks"]["postgresql"] == "error"


class TestSearchMetricsIntegration:
    def test_search_metrics_exist(self) -> None:
        assert hasattr(SEARCH_REQUESTS, "inc")
        assert hasattr(SEARCH_LATENCY, "observe")

"""Tests for POST /api/v1/upload endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from image_search.adapters.input.app import app

client = TestClient(app)


@pytest.fixture()
def _mock_minio():
    with patch("image_search.adapters.input.upload_router.MinioStorage") as cls:
        instance = cls.return_value
        instance.upload = AsyncMock(return_value="http://minio:9000/images/abc.jpg")
        yield instance


@pytest.fixture()
def _mock_event_bus():
    with patch("image_search.adapters.input.upload_router.RedisEventBus") as cls:
        instance = cls.return_value
        instance.emit = AsyncMock(return_value="1-0")
        instance.close = AsyncMock()
        yield instance


def test_upload_success(_mock_minio, _mock_event_bus):
    resp = client.post(
        "/api/v1/upload",
        files={"file": ("test.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
        data={"user_id": "user-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "image_id" in body
    assert body["status"] == "uploaded"


def test_upload_publishes_event(_mock_minio, _mock_event_bus):
    client.post(
        "/api/v1/upload",
        files={"file": ("test.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
        data={"user_id": "user-1"},
    )
    _mock_event_bus.emit.assert_called_once()
    args = _mock_event_bus.emit.call_args
    assert args[0][0] == "image:uploaded"


def test_upload_saves_to_minio(_mock_minio, _mock_event_bus):
    client.post(
        "/api/v1/upload",
        files={"file": ("photo.png", b"\x89PNG", "image/png")},
        data={"user_id": "user-2"},
    )
    _mock_minio.upload.assert_called_once()
    call_args = _mock_minio.upload.call_args
    assert call_args[0][1].endswith(".png")  # object_name preserves extension
    assert call_args[0][2] == "image/png"  # content_type


def test_upload_empty_file(_mock_minio, _mock_event_bus):
    resp = client.post(
        "/api/v1/upload",
        files={"file": ("empty.jpg", b"", "image/jpeg")},
        data={"user_id": "user-1"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Empty file"

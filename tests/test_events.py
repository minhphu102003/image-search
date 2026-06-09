from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from image_search.domain.events import (
    EventBus,
    ImageIndexedEvent,
    ImageSearchEvent,
    ImageUploadedEvent,
)


class TestImageUploadedEvent:
    def test_required_fields(self) -> None:
        event = ImageUploadedEvent(
            image_id="img-001",
            file_path="/storage/uploads/img-001.jpg",
            user_id="user-123",
        )
        assert event.image_id == "img-001"
        assert event.file_path == "/storage/uploads/img-001.jpg"
        assert event.user_id == "user-123"
        assert isinstance(event.timestamp, datetime)

    def test_custom_timestamp(self) -> None:
        ts = datetime(2026, 6, 8, 10, 30, 0, tzinfo=timezone.utc)
        event = ImageUploadedEvent(
            image_id="img-001",
            file_path="/storage/uploads/img-001.jpg",
            user_id="user-123",
            timestamp=ts,
        )
        assert event.timestamp == ts

    def test_json_round_trip(self) -> None:
        event = ImageUploadedEvent(
            image_id="img-001",
            file_path="/storage/uploads/img-001.jpg",
            user_id="user-123",
        )
        json_str = event.model_dump_json()
        restored = ImageUploadedEvent.model_validate_json(json_str)
        assert restored == event

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(Exception):
            ImageUploadedEvent(image_id="img-001", file_path="/path")


class TestImageIndexedEvent:
    def test_indexed_status(self) -> None:
        event = ImageIndexedEvent(image_id="img-001", status="indexed")
        assert event.status == "indexed"
        assert event.error is None

    def test_failed_status_with_error(self) -> None:
        event = ImageIndexedEvent(image_id="img-001", status="failed", error="embedding timeout")
        assert event.status == "failed"
        assert event.error == "embedding timeout"

    def test_json_round_trip(self) -> None:
        event = ImageIndexedEvent(image_id="img-001", status="indexed")
        json_str = event.model_dump_json()
        restored = ImageIndexedEvent.model_validate_json(json_str)
        assert restored == event


class TestImageSearchEvent:
    def test_defaults(self) -> None:
        event = ImageSearchEvent(query="a red car", request_id="req-001")
        assert event.top_k == 10
        assert isinstance(event.timestamp, datetime)

    def test_custom_top_k(self) -> None:
        event = ImageSearchEvent(query="a red car", top_k=5, request_id="req-001")
        assert event.top_k == 5


class TestEventBusInterface:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            EventBus()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_mock_event_bus(self) -> None:
        bus = AsyncMock(spec=EventBus)
        bus.emit.return_value = "1234567890-0"

        event = ImageUploadedEvent(
            image_id="img-001",
            file_path="/path",
            user_id="user-123",
        )
        msg_id = await bus.emit("image:uploaded", event)

        assert msg_id == "1234567890-0"
        bus.emit.assert_awaited_once_with("image:uploaded", event)

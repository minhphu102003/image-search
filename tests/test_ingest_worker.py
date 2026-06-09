from unittest.mock import AsyncMock

import pytest

from image_search.application.ingest_worker import IngestWorkerUseCase
from image_search.domain.events import ImageUploadedEvent


def _make_event(**overrides: object) -> ImageUploadedEvent:
    defaults = {
        "image_id": "img-001",
        "file_path": "/data/test.jpg",
        "user_id": "user-1",
    }
    defaults.update(overrides)
    return ImageUploadedEvent(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def mock_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.save = AsyncMock(return_value=None)
    repo.update_status = AsyncMock()
    repo.update_caption = AsyncMock()
    return repo


@pytest.fixture
def mock_embedding_service() -> AsyncMock:
    svc = AsyncMock()
    svc.embed_image = AsyncMock(return_value=[0.1] * 1024)
    svc.embed_text = AsyncMock(return_value=[0.2] * 1024)
    return svc


@pytest.fixture
def mock_event_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.emit = AsyncMock(return_value="msg-1")
    return bus


@pytest.fixture
def mock_caption_service() -> AsyncMock:
    svc = AsyncMock()
    svc.generate_caption = AsyncMock(return_value="a red car on the beach")
    return svc


@pytest.mark.asyncio
async def test_happy_path_embeds_and_emits(
    mock_repo: AsyncMock,
    mock_embedding_service: AsyncMock,
    mock_event_bus: AsyncMock,
) -> None:
    use_case = IngestWorkerUseCase(
        repository=mock_repo,
        embedding_service=mock_embedding_service,
        event_bus=mock_event_bus,
    )
    event = _make_event()

    await use_case.execute(event)

    mock_embedding_service.embed_image.assert_awaited_once_with("/data/test.jpg")
    mock_repo.save.assert_awaited_once()
    mock_repo.update_status.assert_awaited_once_with("img-001", "INDEXED")
    mock_event_bus.emit.assert_awaited_once()
    emitted_event = mock_event_bus.emit.call_args[0][1]
    assert emitted_event.image_id == "img-001"
    assert emitted_event.status == "indexed"


@pytest.mark.asyncio
async def test_embed_failure_sets_failed_status(
    mock_repo: AsyncMock,
    mock_embedding_service: AsyncMock,
    mock_event_bus: AsyncMock,
) -> None:
    mock_embedding_service.embed_image.side_effect = RuntimeError("model crashed")
    use_case = IngestWorkerUseCase(
        repository=mock_repo,
        embedding_service=mock_embedding_service,
        event_bus=mock_event_bus,
    )

    await use_case.execute(_make_event())

    mock_repo.save.assert_not_awaited()
    mock_repo.update_status.assert_awaited_once_with("img-001", "FAILED", "model crashed")
    emitted_event = mock_event_bus.emit.call_args[0][1]
    assert emitted_event.status == "failed"
    assert emitted_event.error == "model crashed"


@pytest.mark.asyncio
async def test_caption_service_generates_caption(
    mock_repo: AsyncMock,
    mock_embedding_service: AsyncMock,
    mock_event_bus: AsyncMock,
    mock_caption_service: AsyncMock,
) -> None:
    use_case = IngestWorkerUseCase(
        repository=mock_repo,
        embedding_service=mock_embedding_service,
        event_bus=mock_event_bus,
        caption_service=mock_caption_service,
    )

    await use_case.execute(_make_event())

    mock_caption_service.generate_caption.assert_awaited_once_with("/data/test.jpg")
    mock_embedding_service.embed_text.assert_awaited_once_with("a red car on the beach")
    mock_repo.update_caption.assert_awaited_once_with("img-001", "a red car on the beach", [0.2] * 1024)
    mock_repo.update_status.assert_awaited_once_with("img-001", "INDEXED")


@pytest.mark.asyncio
async def test_caption_failure_does_not_fail_ingest(
    mock_repo: AsyncMock,
    mock_embedding_service: AsyncMock,
    mock_event_bus: AsyncMock,
    mock_caption_service: AsyncMock,
) -> None:
    mock_caption_service.generate_caption.side_effect = RuntimeError("API timeout")
    use_case = IngestWorkerUseCase(
        repository=mock_repo,
        embedding_service=mock_embedding_service,
        event_bus=mock_event_bus,
        caption_service=mock_caption_service,
    )

    await use_case.execute(_make_event())

    # Should still mark as indexed even if caption fails
    mock_repo.update_status.assert_awaited_once_with("img-001", "INDEXED")
    mock_repo.update_caption.assert_not_awaited()
    emitted_event = mock_event_bus.emit.call_args[0][1]
    assert emitted_event.status == "indexed"


@pytest.mark.asyncio
async def test_no_caption_service_skips_caption(
    mock_repo: AsyncMock,
    mock_embedding_service: AsyncMock,
    mock_event_bus: AsyncMock,
) -> None:
    use_case = IngestWorkerUseCase(
        repository=mock_repo,
        embedding_service=mock_embedding_service,
        event_bus=mock_event_bus,
        caption_service=None,
    )

    await use_case.execute(_make_event())

    mock_repo.update_status.assert_awaited_once_with("img-001", "INDEXED")
    mock_embedding_service.embed_text.assert_not_awaited()
    mock_repo.update_caption.assert_not_awaited()

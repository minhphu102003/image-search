import asyncio

import structlog

from image_search.adapters.output.sqlalchemy_repo import SqlAlchemyImageEmbeddingRepository
from image_search.application.ingest_worker import IngestWorkerUseCase
from image_search.domain.events import ImageUploadedEvent
from image_search.infrastructure.ai.siglip_service import SigLIPEmbeddingService
from image_search.infrastructure.config import settings
from image_search.infrastructure.database.connection import async_session
from image_search.infrastructure.redis.event_bus import RedisEventBus

logger = structlog.get_logger()


async def main() -> None:
    event_bus = RedisEventBus(settings.redis_url)
    embedding_service = SigLIPEmbeddingService(
        model_name=settings.siglip_model,
        device=settings.siglip_device,
    )

    caption_service = None
    if settings.caption_enabled and settings.gemini_api_key:
        from image_search.infrastructure.ai.caption_service import GeminiCaptionService

        caption_service = GeminiCaptionService(api_key=settings.gemini_api_key)

    logger.info("ingest_worker_started", caption_enabled=caption_service is not None)

    async def handle_event(payload: dict[str, object]) -> None:
        event = ImageUploadedEvent(**payload)  # type: ignore[arg-type]
        async with async_session() as session:
            repository = SqlAlchemyImageEmbeddingRepository(session)
            use_case = IngestWorkerUseCase(
                repository=repository,
                embedding_service=embedding_service,
                event_bus=event_bus,
                caption_service=caption_service,
            )
            await use_case.execute(event)

    await event_bus.consume(
        stream="image:uploaded",
        group="img-ingest",
        consumer=f"ingest-worker-{settings.worker_id}",
        handler=handle_event,
    )


if __name__ == "__main__":
    asyncio.run(main())

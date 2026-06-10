import uuid
from datetime import datetime, timezone

import structlog

from image_search.domain.caption_service import CaptionService
from image_search.domain.embedding_service import EmbeddingService
from image_search.domain.entities import ImageEmbedding, ImageStatus
from image_search.domain.events import EventBus, ImageIndexedEvent, ImageUploadedEvent
from image_search.domain.ports.repositories import ImageEmbeddingRepositoryPort
from image_search.infrastructure.observability.metrics import (
    INGEST_DURATION,
    INGEST_FAILED,
    INGEST_PROCESSED,
)

logger = structlog.get_logger()


class IngestWorkerUseCase:
    def __init__(
        self,
        repository: ImageEmbeddingRepositoryPort,
        embedding_service: EmbeddingService,
        event_bus: EventBus,
        caption_service: CaptionService | None = None,
    ) -> None:
        self.repository = repository
        self.embedding_service = embedding_service
        self.event_bus = event_bus
        self.caption_service = caption_service

    async def execute(self, event: ImageUploadedEvent) -> None:
        import time

        image_id = event.image_id
        logger.info("ingest_started", image_id=image_id)
        start = time.time()

        try:
            # Step 1: Generate image embedding
            t0 = time.time()
            embedding = await self.embedding_service.embed_image(event.file_path)
            logger.info(
                "step1_embed_image", image_id=image_id, dim=len(embedding), elapsed_s=round(time.time() - t0, 2)
            )

            # Step 2: Save to database
            t0 = time.time()
            now = datetime.now(tz=timezone.utc)
            entity = ImageEmbedding(
                id=str(uuid.uuid4()),
                image_id=image_id,
                embedding=embedding,
                caption_embedding=None,
                model_name="siglip2-384",
                caption=None,
                file_path=event.file_path,
                user_id=event.user_id,
                status=ImageStatus.EMBEDDED,
                error_message=None,
                created_at=now,
                updated_at=now,
            )
            await self.repository.save(entity)
            logger.info("step2_saved_to_db", image_id=image_id, elapsed_s=round(time.time() - t0, 2))

            # Step 3: Optional caption generation
            if self.caption_service is not None:
                try:
                    t0 = time.time()
                    caption = await self.caption_service.generate_caption(event.file_path)
                    caption_embedding = await self.embedding_service.embed_text(caption)
                    await self.repository.update_caption(image_id, caption, caption_embedding)
                    logger.info(
                        "step3_caption_done",
                        image_id=image_id,
                        caption=caption,
                        caption_embedding_dim=len(caption_embedding),
                        elapsed_s=round(time.time() - t0, 2),
                    )
                except Exception as e:
                    logger.warning("caption_failed", image_id=image_id, error=str(e))

            # Step 4: Mark as indexed
            await self.repository.update_status(image_id, ImageStatus.INDEXED.value)

            # Step 5: Emit success event
            await self.event_bus.emit(
                "image:indexed",
                ImageIndexedEvent(image_id=image_id, status="indexed"),
            )

            INGEST_DURATION.observe(time.time() - start)
            INGEST_PROCESSED.inc()
            logger.info("ingest_completed", image_id=image_id)

        except Exception as e:
            INGEST_DURATION.observe(time.time() - start)
            INGEST_FAILED.labels(error_type=type(e).__name__).inc()
            logger.error("ingest_failed", image_id=image_id, error=str(e))
            await self.repository.update_status(image_id, ImageStatus.FAILED.value, str(e))
            await self.event_bus.emit(
                "image:indexed",
                ImageIndexedEvent(image_id=image_id, status="failed", error=str(e)),
            )

# Spec: Image Ingest Worker

> Specification for the event-driven worker using Clean Architecture with application use cases.

---

## Metadata

| Field        | Value                |
|-------------|----------------------|
| **ID**      | IS-004               |
| **Title**   | Image Ingest Worker  |
| **Phase**   | 2 — Core Worker      |
| **Status**  | Draft                |
| **Depends** | IS-001, IS-002, IS-003 |

---

## 1. Objective

Build an event-driven worker that subscribes to `image:uploaded`, processes images through an application use case, and emits `image:indexed`. Follows Clean Architecture: domain entities, application use cases, infrastructure implementations.

---

## 2. Architecture

```
src/image_search/
├── domain/
│   ├── entities.py              # ImageEmbedding, ImageStatus
│   ├── repositories.py          # Abstract ImageRepository
│   └── events.py                # Event schemas
├── application/
│   └── ingest_image.py          # IngestImageUseCase
├── infrastructure/
│   ├── database/
│   │   └── repositories.py      # PostgreSQL ImageRepository
│   ├── ai/
│   │   ├── siglip_service.py    # EmbeddingService impl
│   │   └── gemini_service.py    # CaptionService impl
│   ├── redis/
│   │   └── event_bus.py         # EventBus impl
│   └── config.py                # Settings
└── presentation/
    └── worker/
        └── ingest_worker.py     # Worker entry point
```

---

## 3. Detailed Design

### 3.1 Domain — Repository Interface

```python
# src/image_search/domain/repositories.py
from abc import ABC, abstractmethod
from .entities import ImageEmbedding

class ImageRepository(ABC):
    @abstractmethod
    async def upsert(self, image: ImageEmbedding) -> None:
        """Insert or update image embedding."""
        ...

    @abstractmethod
    async def get_by_image_id(self, image_id: str) -> ImageEmbedding | None:
        """Get image by business ID."""
        ...

    @abstractmethod
    async def update_status(self, image_id: str, status: str, error: str | None = None) -> None:
        """Update image status."""
        ...

    @abstractmethod
    async def update_caption(self, image_id: str, caption: str, caption_embedding: list[float]) -> None:
        """Update caption and its embedding."""
        ...
```

### 3.2 Application — Use Case

```python
# src/image_search/application/ingest_image.py
import uuid
import structlog

from image_search.domain.entities import ImageEmbedding, ImageStatus
from image_search.domain.repositories import ImageRepository
from image_search.domain.embedding_service import EmbeddingService
from image_search.domain.events import EventBus, ImageUploadedEvent, ImageIndexedEvent

logger = structlog.get_logger()

class IngestImageUseCase:
    def __init__(
        self,
        repository: ImageRepository,
        embedding_service: EmbeddingService,
        event_bus: EventBus,
        caption_service=None,  # Optional GeminiCaptionService
    ):
        self.repository = repository
        self.embedding_service = embedding_service
        self.event_bus = event_bus
        self.caption_service = caption_service

    async def execute(self, event: ImageUploadedEvent) -> None:
        image_id = event.image_id
        logger.info("ingest_started", image_id=image_id)

        try:
            # Step 1: Embed image
            embedding = await self.embedding_service.embed_image(event.file_path)

            # Step 2: Upsert to database
            image = ImageEmbedding(
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
            )
            await self.repository.upsert(image)

            # Step 3: Optional caption
            if self.caption_service:
                try:
                    caption = await self.caption_service.generate_caption(event.file_path)
                    caption_embedding = await self.embedding_service.embed_text(caption)
                    await self.repository.update_caption(image_id, caption, caption_embedding)
                except Exception as e:
                    logger.warning("caption_failed", image_id=image_id, error=str(e))

            # Step 4: Mark indexed
            await self.repository.update_status(image_id, ImageStatus.INDEXED)

            # Step 5: Emit event
            await self.event_bus.emit("image:indexed", ImageIndexedEvent(
                image_id=image_id, status="indexed"
            ))

            logger.info("ingest_completed", image_id=image_id)

        except Exception as e:
            logger.error("ingest_failed", image_id=image_id, error=str(e))
            await self.repository.update_status(image_id, ImageStatus.FAILED, str(e))
            await self.event_bus.emit("image:indexed", ImageIndexedEvent(
                image_id=image_id, status="failed", error=str(e)
            ))
```

### 3.3 Infrastructure — Database Repository

```python
# src/image_search/infrastructure/database/repositories.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select, update

from image_search.domain.entities import ImageEmbedding, ImageStatus
from image_search.domain.repositories import ImageRepository
from .models import ImageEmbeddingModel

class PostgresImageRepository(ImageRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, image: ImageEmbedding) -> None:
        stmt = pg_insert(ImageEmbeddingModel).values(
            id=image.id,
            image_id=image.image_id,
            embedding=image.embedding,
            model_name=image.model_name,
            file_path=image.file_path,
            user_id=image.user_id,
            status=image.status.value,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["image_id"],
            set_={
                "embedding": stmt.excluded.embedding,
                "model_name": stmt.excluded.model_name,
                "status": stmt.excluded.status,
                "updated_at": "NOW()",
            },
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def update_status(self, image_id: str, status: str, error: str | None = None) -> None:
        stmt = (
            update(ImageEmbeddingModel)
            .where(ImageEmbeddingModel.image_id == image_id)
            .values(status=status, error_message=error)
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def update_caption(self, image_id: str, caption: str, caption_embedding: list[float]) -> None:
        stmt = (
            update(ImageEmbeddingModel)
            .where(ImageEmbeddingModel.image_id == image_id)
            .values(caption=caption, caption_embedding=caption_embedding)
        )
        await self.session.execute(stmt)
        await self.session.commit()
```

### 3.4 Presentation — Worker Entry Point

```python
# src/image_search/presentation/worker/ingest_worker.py
import asyncio
import structlog

from image_search.infrastructure.config import settings
from image_search.infrastructure.redis.event_bus import RedisEventBus
from image_search.infrastructure.database.connection import async_session
from image_search.infrastructure.database.repositories import PostgresImageRepository
from image_search.infrastructure.ai.siglip_service import SigLIPEmbeddingService
from image_search.domain.events import ImageUploadedEvent
from image_search.application.ingest_image import IngestImageUseCase

logger = structlog.get_logger()

async def main():
    # Initialize infrastructure
    event_bus = RedisEventBus(settings.redis_url)
    embedding_service = SigLIPEmbeddingService(settings.siglip_model)

    logger.info("ingest_worker_started")

    async def handle_event(payload: dict):
        event = ImageUploadedEvent(**payload)
        async with async_session() as session:
            repository = PostgresImageRepository(session)
            use_case = IngestImageUseCase(
                repository=repository,
                embedding_service=embedding_service,
                event_bus=event_bus,
                caption_service=None,  # Enable if CAPTION_ENABLED
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
```

---

## 4. Configuration

```python
# In Settings class
worker_id: str = "1"
caption_enabled: bool = False
gemini_api_key: str | None = None
```

---

## 5. Error Handling

| Error                          | Action                              |
|-------------------------------|-------------------------------------|
| Image file not found           | Status → FAILED, emit failed event  |
| SigLIP embedding fails         | Retry 3x, then FAILED               |
| Database write fails           | Retry 3x, then FAILED               |
| Gemini caption fails           | Skip caption, continue to INDEXED   |

---

## 6. Acceptance Criteria

- [ ] Publish `image:uploaded` → `image_embeddings` has new row within 5 seconds
- [ ] Row has status `INDEXED` and 1024-dim embedding
- [ ] `image:indexed` event emitted
- [ ] Idempotent: same `image_id` twice → one row
- [ ] File not found → status `FAILED`
- [ ] Domain interfaces can be mocked for unit tests

---

## 7. Testing Strategy

### Unit Tests
- Mock `ImageRepository`, `EmbeddingService`, `EventBus`
- `IngestImageUseCase.execute()` calls all dependencies correctly
- Error handling: embed fails → status FAILED

### Integration Tests
- Full pipeline with real Redis and PostgreSQL
- Publish event → verify database row → verify emitted event

# Spec: Redis Stream Event Bus — Image Events

> Specification for Redis Stream events using Clean Architecture with domain interfaces and infrastructure implementations.

---

## Metadata

| Field        | Value                           |
|-------------|----------------------------------|
| **ID**      | IS-002                           |
| **Title**   | Redis Stream Event Bus — Image Events |
| **Phase**   | 1 — Foundation                   |
| **Status**  | Draft                            |
| **Depends** | None                             |

---

## 1. Objective

Establish reliable event communication between BE Nest (NestJS) and AI workers (Python) via Redis Streams. Define event schemas, consumer groups, and Clean Architecture components (domain interface + infrastructure implementation).

---

## 2. Tech Stack

| Tool          | Purpose                    |
|--------------|----------------------------|
| redis-py     | Redis async client         |
| pydantic     | Event payload validation   |
| structlog    | Structured logging         |

---

## 3. Event Catalog

### 3.1 `image:uploaded`

```json
{
  "image_id": "img-001",
  "file_path": "/storage/uploads/img-001.jpg",
  "user_id": "user-123",
  "timestamp": "2026-06-08T10:30:00Z"
}
```

### 3.2 `image:indexed`

```json
{
  "image_id": "img-001",
  "status": "indexed",
  "error": null,
  "timestamp": "2026-06-08T10:30:05Z"
}
```

### 3.3 `image:search`

```json
{
  "query": "a red car on the beach",
  "top_k": 5,
  "request_id": "req-abc-123",
  "timestamp": "2026-06-08T10:31:00Z"
}
```

---

## 4. Detailed Design

### 4.1 Clean Architecture — Event Layer

```
src/image_search/
├── domain/
│   └── events.py                # Event schemas (Pydantic) + abstract EventBus
├── infrastructure/
│   └── redis/
│       ├── connection.py        # Redis connection factory
│       └── event_bus.py         # Redis EventBus implementation
└── presentation/
    └── worker/
        └── ingest_worker.py     # Worker entry point
```

### 4.2 Domain — Event Schemas

```python
# src/image_search/domain/events.py
from pydantic import BaseModel, Field
from datetime import datetime, timezone

class ImageUploadedEvent(BaseModel):
    image_id: str
    file_path: str
    user_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ImageIndexedEvent(BaseModel):
    image_id: str
    status: str  # "indexed" or "failed"
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ImageSearchEvent(BaseModel):
    query: str
    top_k: int = 10
    request_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### 4.3 Domain — Abstract EventBus

```python
# src/image_search/domain/events.py (continued)
from abc import ABC, abstractmethod
from typing import Callable, Awaitable

class EventBus(ABC):
    @abstractmethod
    async def emit(self, stream: str, event: BaseModel) -> str:
        """Emit event to stream. Returns message ID."""
        ...

    @abstractmethod
    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        handler: Callable[[dict], Awaitable[None]],
    ) -> None:
        """Consume events from stream with consumer group."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close connection."""
        ...
```

### 4.4 Infrastructure — Redis EventBus

```python
# src/image_search/infrastructure/redis/event_bus.py
import json
import redis.asyncio as redis
from datetime import datetime, timezone
import structlog

from image_search.domain.events import EventBus

logger = structlog.get_logger()

class RedisEventBus(EventBus):
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url, decode_responses=True)

    async def emit(self, stream: str, event) -> str:
        payload = event.model_dump_json()
        msg_id = await self.redis.xadd(stream, {"data": payload})
        logger.info("event_emitted", stream=stream, msg_id=msg_id)
        return msg_id

    async def consume(self, stream, group, consumer, handler):
        # Create consumer group if not exists
        try:
            await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

        while True:
            results = await self.redis.xreadgroup(
                group, consumer, {stream: ">"}, count=1, block=5000
            )
            if not results:
                continue

            for stream_name, messages in results:
                for msg_id, fields in messages:
                    try:
                        payload = json.loads(fields["data"])
                        await handler(payload)
                        await self.redis.xack(stream, group, msg_id)
                        logger.info("event_processed", stream=stream, msg_id=msg_id)
                    except Exception as e:
                        logger.error("event_processing_failed",
                                   stream=stream, msg_id=msg_id, error=str(e))
                        await self._handle_dead_letter(stream, group, msg_id, fields, e)

    async def _handle_dead_letter(self, stream, group, msg_id, fields, error):
        pending = await self.redis.xpending_range(stream, group, msg_id, msg_id, 1)
        if pending and pending[0]["times_delivered"] >= 3:
            dead_stream = f"{stream}:dead-letter"
            await self.redis.xadd(dead_stream, {
                "original_stream": stream,
                "original_msg_id": msg_id,
                "data": fields["data"],
                "error": str(error),
            })
            await self.redis.xack(stream, group, msg_id)
            logger.warning("message_dead_lettered", stream=stream, msg_id=msg_id)

    async def close(self):
        await self.redis.close()
```

### 4.5 Infrastructure — Redis Connection

```python
# src/image_search/infrastructure/redis/connection.py
import redis.asyncio as redis
from image_search.infrastructure.config import settings

async def create_redis() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)

def create_event_bus() -> RedisEventBus:
    return RedisEventBus(settings.redis_url)
```

---

## 5. Configuration

```python
# In Settings class (IS-001)
redis_url: str = "redis://localhost:6379"
```

| Env Var       | Default                  | Description              |
|--------------|--------------------------|--------------------------|
| `IMAGE_SEARCH_REDIS_URL` | `redis://localhost:6379` | Redis connection string |

---

## 6. Error Handling

| Scenario                    | Action                                          |
|----------------------------|-------------------------------------------------|
| Malformed JSON payload      | Log error, ACK message (don't retry poison pills)|
| Handler exception           | Don't ACK, message stays pending for retry      |
| 3 delivery failures         | Move to `{stream}:dead-letter` stream           |
| Redis connection lost       | Reconnect with exponential backoff              |
| Consumer group doesn't exist| Auto-create with `mkstream=True`                |

---

## 7. Consumer Groups

| Stream             | Group Name   | Consumer Name        |
|-------------------|--------------|----------------------|
| `image:uploaded`   | `img-ingest` | `ingest-worker-{id}` |
| `image:search`     | `img-search` | `search-service-{id}`|

---

## 8. Acceptance Criteria

- [ ] `emit("image:uploaded", ImageUploadedEvent(...))` adds to Redis stream
- [ ] Consumer in group `img-ingest` reads message via `XREADGROUP`
- [ ] After handler success, message is `XACK`ed and not re-delivered
- [ ] After 3 failures, message moved to `image:uploaded:dead-letter`
- [ ] Domain `EventBus` interface can be mocked for unit tests
- [ ] Cross-language: NestJS `XADD` → Python consumer reads correctly

---

## 9. Testing Strategy

### Unit Tests
- Mock `EventBus` for use case tests
- `ImageUploadedEvent` validation (required fields)

### Integration Tests
- Full round-trip: emit → consume → verify XACK
- Dead-letter after 3 failures
- Multiple consumers in same group

### Contract Tests
- NestJS payload format → Python Pydantic parsing

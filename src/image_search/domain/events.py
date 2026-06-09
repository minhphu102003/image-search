from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field


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
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Consume events from stream with consumer group."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close connection."""
        ...

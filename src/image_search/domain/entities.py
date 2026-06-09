from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ImageStatus(str, Enum):
    PENDING = "PENDING"
    EMBEDDED = "EMBEDDED"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


@dataclass
class ImageEmbedding:
    id: str
    image_id: str
    embedding: list[float]
    caption_embedding: list[float] | None
    model_name: str
    caption: str | None
    file_path: str
    user_id: str
    status: ImageStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime

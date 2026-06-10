"""Upload endpoint — stores image in MinIO, publishes event to Redis."""

import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from image_search.adapters.output.minio_storage import MinioStorage
from image_search.domain.events import ImageUploadedEvent
from image_search.infrastructure.config import settings
from image_search.infrastructure.redis.event_bus import RedisEventBus

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["upload"])


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    user_id: str = Form(...),
) -> dict[str, str]:
    image_id = str(uuid.uuid4())
    suffix = Path(file.filename).suffix if file.filename else ".jpg"
    object_name = f"{image_id}{suffix}"

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    storage = MinioStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
        secure=settings.minio_secure,
    )
    url = await storage.upload(file_bytes, object_name, file.content_type or "image/jpeg")

    event_bus = RedisEventBus(settings.redis_url)
    try:
        event = ImageUploadedEvent(image_id=image_id, file_path=url, user_id=user_id)
        await event_bus.emit("image:uploaded", event)
    finally:
        await event_bus.close()

    logger.info("image_uploaded", image_id=image_id, user_id=user_id, object=object_name)
    return {"image_id": image_id, "status": "uploaded"}

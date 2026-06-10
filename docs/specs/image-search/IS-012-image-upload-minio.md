# Spec: Image Upload via MinIO + Auto-Ingest

> Specification for uploading images to MinIO (S3-compatible storage) and triggering automatic ingest via Redis events.

---

## Metadata

| Field        | Value                        |
|-------------|------------------------------|
| **ID**      | IS-012                       |
| **Title**   | Image Upload via MinIO       |
| **Phase**   | 2 — Core Features            |
| **Status**  | Draft                        |
| **Depends** | IS-002, IS-003, IS-004, IS-011|

---

## 1. Objective

Add a `POST /api/v1/upload` endpoint that accepts an image file, stores it in MinIO (S3-compatible object storage), and publishes an `ImageUploadedEvent` with the object URL to Redis. The ingest worker fetches the image from the URL, generates SigLIP 2 embeddings, and persists to PostgreSQL — completing the full upload-to-search pipeline.

---

## 2. Architecture

```
┌──────────┐     POST /api/v1/upload      ┌─────────────┐
│  Client  │ ────────────────────────────► │   API       │
│          │   (file + user_id)            │  (FastAPI)  │
└──────────┘                               └──────┬──────┘
                                                  │
                                    ┌─────────────┼─────────────┐
                                    │             │             │
                                    ▼             ▼             ▼
                              ┌──────────┐  ┌──────────┐  ┌──────────┐
                              │  MinIO   │  │  Redis   │  │ Response │
                              │ (store)  │  │ (event)  │  │ 200 OK   │
                              └──────────┘  └────┬─────┘  └──────────┘
                                                  │
                                                  │ ImageUploadedEvent
                                                  │ {file_path: "http://minio:9000/..."}
                                                  ▼
                                           ┌─────────────┐
                                           │   Worker    │
                                           │ (consume)   │
                                           └──────┬──────┘
                                                  │
                                    ┌─────────────┼─────────────┐
                                    │             │             │
                                    ▼             ▼             ▼
                              ┌──────────┐  ┌──────────┐  ┌──────────┐
                              │ Fetch    │  │ SigLIP 2 │  │ Postgres │
                              │ from URL │  │ embed    │  │ +pgvector│
                              └──────────┘  └──────────┘  └──────────┘
```

---

## 3. Detailed Design

### 3.1 MinIO Storage Adapter

**File:** `src/image_search/adapters/output/minio_storage.py`

```python
from minio import Minio
from minio.error import S3Error

class MinioStorage:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False):
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    async def upload(self, file_bytes: bytes, object_name: str, content_type: str = "application/octet-stream") -> str:
        import io
        self.client.put_object(
            self.bucket, object_name, io.BytesIO(file_bytes), len(file_bytes), content_type=content_type
        )
        return self.get_url(object_name)

    def get_url(self, object_name: str) -> str:
        return self.client.presigned_get_object(self.bucket, object_name)
```

### 3.2 Upload Router

**File:** `src/image_search/adapters/input/upload_router.py`

```python
import uuid
from fastapi import APIRouter, UploadFile, File, Form, Depends
from image_search.adapters.output.minio_storage import MinioStorage
from image_search.domain.events import ImageUploadedEvent, EventBus
from image_search.infrastructure.redis.event_bus import RedisEventBus
from image_search.infrastructure.config import settings

router = APIRouter(prefix="/api/v1", tags=["upload"])

@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    user_id: str = Form(...),
):
    # 1. Generate image_id
    image_id = str(uuid.uuid4())
    suffix = Path(file.filename).suffix if file.filename else ".jpg"
    object_name = f"{image_id}{suffix}"

    # 2. Upload to MinIO
    file_bytes = await file.read()
    storage = MinioStorage(...)
    url = await storage.upload(file_bytes, object_name, file.content_type or "image/jpeg")

    # 3. Publish event to Redis
    event_bus = RedisEventBus(settings.redis_url)
    event = ImageUploadedEvent(image_id=image_id, file_path=url, user_id=user_id)
    await event_bus.emit("image:uploaded", event)
    await event_bus.close()

    return {"image_id": image_id, "status": "uploaded"}
```

### 3.3 SigLIP Service — URL Support

**File:** `src/image_search/infrastructure/ai/siglip_service.py`

Modify `embed_image()` to handle both local paths and HTTP URLs:

```python
async def embed_image(self, image_path: str) -> list[float]:
    if image_path.startswith("http://") or image_path.startswith("https://"):
        # Download to temp file
        import httpx, tempfile
        async with httpx.AsyncClient() as client:
            resp = await client.get(image_path)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                f.write(resp.content)
                tmp_path = f.name
        image = Image.open(tmp_path).convert("RGB")
        os.unlink(tmp_path)
    else:
        image = Image.open(image_path).convert("RGB")
    # ... rest unchanged
```

Same change for `embed_images_batch()`.

### 3.4 Config — MinIO Settings

**File:** `src/image_search/infrastructure/config.py`

```python
# MinIO / S3 storage
minio_endpoint: str = "minio:9000"
minio_access_key: str = "minioadmin"
minio_secret_key: str = "minioadmin"
minio_bucket: str = "images"
minio_secure: bool = False
```

### 3.5 docker-compose.yml — MinIO Services

```yaml
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - miniodata:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 3s
      retries: 10

  minio-init:
    image: minio/mc:latest
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set myminio http://minio:9000 minioadmin minioadmin;
      mc mb --ignore-existing myminio/images;
      exit 0;
      "

  api:
    # ... existing config ...
    environment:
      # ... existing vars ...
      IMAGE_SEARCH_MINIO_ENDPOINT: minio:9000
      IMAGE_SEARCH_MINIO_ACCESS_KEY: minioadmin
      IMAGE_SEARCH_MINIO_SECRET_KEY: minioadmin
      IMAGE_SEARCH_MINIO_BUCKET: images
    depends_on:
      migrate:
        condition: service_completed_successfully
      minio-init:
        condition: service_completed_successfully

volumes:
  pgdata:
  redisdata:
  miniodata:
```

### 3.6 .env.example

```bash
# ── MinIO / S3 Storage ──
IMAGE_SEARCH_MINIO_ENDPOINT=minio:9000
IMAGE_SEARCH_MINIO_ACCESS_KEY=minioadmin
IMAGE_SEARCH_MINIO_SECRET_KEY=minioadmin
IMAGE_SEARCH_MINIO_BUCKET=images
IMAGE_SEARCH_MINIO_SECURE=false
```

---

## 4. Data Flow

```
1. Client uploads file → POST /api/v1/upload
2. API reads file bytes, generates UUID image_id
3. API uploads to MinIO bucket "images" as {image_id}.{ext}
4. API gets presigned URL from MinIO
5. API publishes ImageUploadedEvent to Redis stream "image:uploaded"
   - image_id: UUID
   - file_path: presigned MinIO URL
   - user_id: from form field
6. Worker consumes event from Redis
7. Worker downloads image from URL (httpx)
8. Worker generates SigLIP 2 embedding (1024-dim)
9. Worker saves to PostgreSQL with status EMBEDDED
10. Worker (optional) generates caption via Gemini
11. Worker updates status to INDEXED
12. Worker publishes ImageIndexedEvent to Redis stream "image:indexed"
```

---

## 5. Dependencies

Add to `pyproject.toml`:
```toml
dependencies = [
    # ... existing ...
    "minio>=7.2.0",
]
```

---

## 6. Acceptance Criteria

- [ ] `POST /api/v1/upload` accepts multipart file upload with `user_id`
- [ ] Image is stored in MinIO bucket `images`
- [ ] `ImageUploadedEvent` with MinIO URL is published to Redis stream `image:uploaded`
- [ ] Worker consumes event and downloads image from URL
- [ ] Worker generates SigLIP 2 embedding and saves to PostgreSQL
- [ ] `docker compose up -d` starts MinIO alongside existing services
- [ ] MinIO console accessible at `http://localhost:9001`
- [ ] `.env.example` documents all MinIO env vars

---

## 7. Testing Strategy

### Unit Tests
- Upload endpoint returns 200 with `image_id` and `status: uploaded`
- Upload endpoint calls MinIO storage with correct object name
- Upload endpoint publishes event to Redis with URL
- SigLIP service downloads from URL when given HTTP path
- SigLIP service opens local file when given file path

### Integration Test (Docker)
```bash
docker compose up -d
curl -X POST http://localhost:8000/api/v1/upload \
  -F "file=@test.jpg" \
  -F "user_id=test-user"
# expect {"image_id": "uuid", "status": "uploaded"}

docker compose logs -f worker
# expect: event_processed, embedding saved

curl -X POST http://localhost:8000/api/v1/image-search \
  -H "Content-Type: application/json" \
  -d '{"query": "test image", "top_k": 5}'
# expect: results containing the uploaded image
```

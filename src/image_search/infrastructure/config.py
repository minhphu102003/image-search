from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/beekid_ai"
    redis_url: str = "redis://localhost:6379"

    # Jina AI cloud embedding
    jina_api_key: str | None = None
    jina_model: str = "jina-embeddings-v4"
    jina_api_url: str = "https://api.jina.ai/v1/embeddings"
    jina_dimensions: int = 1024

    # pgvector HNSW parameters
    hnsw_m: int = 16
    hnsw_ef_construction: int = 64
    hnsw_ef_search: int = 40

    # Search
    image_search_approach: int = 1
    min_score_threshold: float = 0.5
    image_search_host: str = "0.0.0.0"
    image_search_port: int = 8000

    # Worker
    worker_id: str = "1"
    caption_enabled: bool = False
    gemini_api_key: str | None = None
    caption_prompt: str = ""

    # MinIO / S3 storage
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "images"
    minio_secure: bool = False

    # Observability
    metrics_enabled: bool = True
    log_level: str = "INFO"
    log_format: str = "json"

    model_config = {"env_prefix": "IMAGE_SEARCH_", "env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/beekid_ai"
    redis_url: str = "redis://localhost:6379"

    # SigLIP 2 embedding
    siglip_model: str = "google/siglip2-so400m-patch16-384"
    siglip_device: str | None = None
    embed_batch_size: int = 8

    # pgvector HNSW parameters
    hnsw_m: int = 16
    hnsw_ef_construction: int = 64
    hnsw_ef_search: int = 40

    # Search
    image_search_approach: int = 1
    image_search_host: str = "0.0.0.0"
    image_search_port: int = 8000

    # Worker
    worker_id: str = "1"
    caption_enabled: bool = False
    gemini_api_key: str | None = None

    # Observability
    metrics_enabled: bool = True
    log_level: str = "INFO"
    log_format: str = "json"

    model_config = {"env_prefix": "IMAGE_SEARCH_"}


settings = Settings()

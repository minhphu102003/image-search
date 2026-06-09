from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/beekid_ai"
    redis_url: str = "redis://localhost:6379"

    # pgvector HNSW parameters
    hnsw_m: int = 16
    hnsw_ef_construction: int = 64
    hnsw_ef_search: int = 40

    model_config = {"env_prefix": "IMAGE_SEARCH_"}


settings = Settings()

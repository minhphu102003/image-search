# Spec: Database Schema — `image_embeddings` Table

> Specification for PostgreSQL + pgvector schema using Alembic migrations and SQLAlchemy models.

---

## Metadata

| Field        | Value                                |
|-------------|--------------------------------------|
| **ID**      | IS-001                               |
| **Title**   | Database Schema — `image_embeddings` |
| **Phase**   | 1 — Foundation                       |
| **Status**  | Draft                                |
| **Depends** | None                                 |

---

## 1. Objective

Provide a PostgreSQL schema with pgvector extension to store image embeddings (1024-dim from SigLIP 2) and optional caption text embeddings. Use **Alembic** for migrations and **SQLAlchemy 2.0** for ORM models, following Clean Architecture principles.

---

## 2. Tech Stack

| Tool               | Purpose                          |
|-------------------|----------------------------------|
| Python 3.12+       | Language                         |
| uv                 | Package manager                  |
| SQLAlchemy 2.0     | ORM + async driver               |
| Alembic            | Database migrations              |
| pgvector           | Vector similarity search         |
| asyncpg            | Async PostgreSQL driver          |
| pydantic-settings  | Configuration                    |

---

## 3. Project Setup

### 3.1 pyproject.toml

```toml
[project]
name = "image-search"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "pgvector>=0.3",
    "pydantic-settings>=2.0",
    "redis>=5.0",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "structlog>=24.0",
    "prometheus-client>=0.21",
    "httpx>=0.27",
]

[project.optional-dependencies]
ai = [
    "torch>=2.4",
    "transformers>=4.45",
    "pillow>=10.0",
    "google-generativeai>=0.8",
]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "ruff>=0.6",
    "mypy>=1.11",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 3.2 Install

```bash
uv init image-search
cd image-search
uv add sqlalchemy[asyncio] asyncpg alembic pgvector pydantic-settings redis fastapi uvicorn structlog prometheus-client httpx
uv add --optional ai torch transformers pillow google-generativeai
uv add --dev pytest pytest-asyncio pytest-cov ruff mypy
```

---

## 4. Detailed Design

### 4.1 Clean Architecture — Database Layer

```
src/image_search/
├── domain/
│   └── entities.py              # Domain entity (dataclass)
├── infrastructure/
│   └── database/
│       ├── connection.py        # Async engine + session factory
│       ├── models.py            # SQLAlchemy ORM model
│       └── repositories.py      # Concrete repository
└── ...
```

### 4.2 Domain Entity

```python
# src/image_search/domain/entities.py
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
```

### 4.3 SQLAlchemy Model

```python
# src/image_search/infrastructure/database/models.py
from datetime import datetime
from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector

class Base(DeclarativeBase):
    pass

class ImageEmbeddingModel(Base):
    __tablename__ = "image_embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    embedding = mapped_column(Vector(1024), nullable=False)
    caption_embedding = mapped_column(Vector(768), nullable=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, default="siglip2-384", index=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

### 4.4 Database Connection

```python
# src/image_search/infrastructure/database/connection.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from .models import Base

engine = create_async_engine(
    "postgresql+asyncpg://user:pass@localhost:5432/beekid_ai",
    echo=False,
    pool_size=5,
    max_overflow=10,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.run_sync(Base.metadata.create_all)
```

### 4.5 Alembic Setup

```bash
alembic init alembic
```

**alembic.ini:**
```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+asyncpg://user:pass@localhost:5432/beekid_ai
```

**alembic/env.py (key sections):**
```python
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context
from image_search.infrastructure.database.models import Base

target_metadata = Base.metadata

def run_migrations_online():
    connectable = create_async_engine(config.get_main_option("sqlalchemy.url"))

    async def do_run():
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)

    import asyncio
    asyncio.run(do_run())

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
```

### 4.6 Migration Script

```python
# alembic/versions/001_create_image_embeddings.py
"""create image_embeddings table

Revision ID: 001
Revises:
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "001"
down_revision = None

def upgrade():
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create table
    op.create_table(
        "image_embeddings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("image_id", sa.String(64), unique=True, nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("caption_embedding", Vector(768), nullable=True),
        sa.Column("model_name", sa.String(64), nullable=False, server_default="siglip2-384"),
        sa.Column("caption", sa.Text, nullable=True),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # HNSW index for embedding (cosine distance)
    op.execute("""
        CREATE INDEX idx_image_embeddings_hnsw
        ON image_embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # Partial HNSW index for caption_embedding (non-null only)
    op.execute("""
        CREATE INDEX idx_image_embeddings_caption_hnsw
        ON image_embeddings
        USING hnsw (caption_embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE caption_embedding IS NOT NULL
    """)

    # B-tree indexes for filtering
    op.create_index("idx_image_embeddings_model_name", "image_embeddings", ["model_name"])
    op.create_index("idx_image_embeddings_status", "image_embeddings", ["status"])

def downgrade():
    op.drop_table("image_embeddings")
    op.execute("DROP EXTENSION IF EXISTS vector")
```

### 4.7 Run Migrations

```bash
# Create migration
alembic revision --autogenerate -m "create image_embeddings"

# Apply
alembic upgrade head

# Rollback
alembic downgrade -1
```

---

## 5. Configuration

```python
# src/image_search/infrastructure/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/beekid_ai"
    redis_url: str = "redis://localhost:6379"

    # pgvector
    hnsw_m: int = 16
    hnsw_ef_construction: int = 64
    hnsw_ef_search: int = 40

    model_config = {"env_prefix": "IMAGE_SEARCH_"}

settings = Settings()
```

---

## 6. Error Handling

| Scenario                    | Action                                    |
|----------------------------|-------------------------------------------|
| pgvector not installed      | Migration fails with clear error          |
| Migration fails             | `alembic downgrade -1` to rollback        |
| Duplicate `image_id`       | `ON CONFLICT DO UPDATE` in repository     |
| VECTOR dimension mismatch   | pgvector raises error at INSERT           |
| Connection pool exhausted   | AsyncSession raises timeout               |

---

## 7. Acceptance Criteria

- [ ] `uv sync` installs all dependencies
- [ ] `alembic upgrade head` creates `image_embeddings` table
- [ ] HNSW index on `embedding` visible in `pg_indexes`
- [ ] Partial HNSW index on `caption_embedding` visible
- [ ] `ImageEmbeddingModel` can be queried via SQLAlchemy async
- [ ] `alembic downgrade -1` drops table cleanly
- [ ] `INSERT` with 1024-dim vector succeeds
- [ ] Cosine search `ORDER BY embedding <=> $1` returns correct results

---

## 8. Testing Strategy

### Unit Tests
- Domain entity creation and validation
- SQLAlchemy model mapping correctness

### Integration Tests
- Alembic migration up/down on test database
- CRUD operations via repository
- Cosine similarity search with seed data

### Seed Data

```python
# tests/conftest.py or seed script
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.fixture
async def seed_images(session: AsyncSession):
    """Insert 5 test images with embeddings."""
    images = [
        ImageEmbeddingModel(
            id="uuid-1", image_id="img-001",
            embedding=[0.1, 0.02, ...],  # 1024 floats
            model_name="siglip2-384", file_path="/images/car_red.jpg",
            user_id="user-1", status="INDEXED",
            caption="A red car on the beach"
        ),
        # ... 4 more
    ]
    session.add_all(images)
    await session.commit()
```

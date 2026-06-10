import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from image_search.adapters.output.sqlalchemy_repo import SqlAlchemyImageEmbeddingRepository
from image_search.domain.entities import ImageEmbedding, ImageStatus
from image_search.infrastructure.database.models import Base

TEST_DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/beekid_ai_test"


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncSession:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()


@pytest_asyncio.fixture
def repo(session: AsyncSession) -> SqlAlchemyImageEmbeddingRepository:
    return SqlAlchemyImageEmbeddingRepository(session)


def _make_entity(**overrides) -> ImageEmbedding:
    now = datetime.now(tz=timezone.utc)
    defaults = {
        "id": str(uuid.uuid4()),
        "image_id": f"img-{uuid.uuid4().hex[:8]}",
        "embedding": [0.1] * 1024,
        "caption_embedding": None,
        "model_name": "jina-embeddings-v4",
        "caption": None,
        "file_path": "/images/test.jpg",
        "user_id": "user-1",
        "status": ImageStatus.PENDING,
        "error_message": None,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return ImageEmbedding(**defaults)


@pytest.mark.asyncio
async def test_save_new(repo: SqlAlchemyImageEmbeddingRepository):
    entity = _make_entity(image_id="img-save-new")
    result = await repo.save(entity)
    assert result.image_id == "img-save-new"
    assert result.id == entity.id


@pytest.mark.asyncio
async def test_save_upsert(repo: SqlAlchemyImageEmbeddingRepository):
    entity = _make_entity(image_id="img-upsert", status=ImageStatus.PENDING)
    await repo.save(entity)

    updated = _make_entity(
        id=entity.id,
        image_id="img-upsert",
        status=ImageStatus.INDEXED,
        caption="updated",
    )
    result = await repo.save(updated)
    assert result.status == ImageStatus.INDEXED
    assert result.caption == "updated"


@pytest.mark.asyncio
async def test_get_by_image_id_found(repo: SqlAlchemyImageEmbeddingRepository):
    entity = _make_entity(image_id="img-get")
    await repo.save(entity)
    found = await repo.get_by_image_id("img-get")
    assert found is not None
    assert found.image_id == "img-get"


@pytest.mark.asyncio
async def test_get_by_image_id_not_found(repo: SqlAlchemyImageEmbeddingRepository):
    result = await repo.get_by_image_id("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_delete_by_image_id(repo: SqlAlchemyImageEmbeddingRepository):
    entity = _make_entity(image_id="img-delete")
    await repo.save(entity)

    deleted = await repo.delete_by_image_id("img-delete")
    assert deleted is True

    found = await repo.get_by_image_id("img-delete")
    assert found is None


@pytest.mark.asyncio
async def test_delete_nonexistent(repo: SqlAlchemyImageEmbeddingRepository):
    deleted = await repo.delete_by_image_id("nonexistent")
    assert deleted is False


@pytest.mark.asyncio
async def test_search_by_embedding(repo: SqlAlchemyImageEmbeddingRepository):
    import random

    random.seed(42)
    for i in range(3):
        emb = [random.random() for _ in range(1024)]
        entity = _make_entity(
            image_id=f"img-search-{i}",
            embedding=emb,
            status=ImageStatus.INDEXED,
        )
        await repo.save(entity)

    query = [random.random() for _ in range(1024)]
    results = await repo.search_by_embedding(query, limit=2)
    assert len(results) == 2
    assert all(isinstance(r, ImageEmbedding) for r in results)

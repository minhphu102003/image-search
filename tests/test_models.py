import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from image_search.infrastructure.database.models import Base, ImageEmbeddingModel

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


def _make_embedding_model(**overrides) -> ImageEmbeddingModel:
    defaults = {
        "id": str(uuid.uuid4()),
        "image_id": f"img-{uuid.uuid4().hex[:8]}",
        "embedding": [0.1] * 1024,
        "model_name": "jina-embeddings-v4",
        "file_path": "/images/test.jpg",
        "user_id": "user-1",
        "status": "PENDING",
    }
    defaults.update(overrides)
    return ImageEmbeddingModel(**defaults)


@pytest.mark.asyncio
async def test_insert_and_query(session: AsyncSession):
    model = _make_embedding_model(image_id="img-query-test")
    session.add(model)
    await session.flush()

    result = await session.execute(select(ImageEmbeddingModel).where(ImageEmbeddingModel.image_id == "img-query-test"))
    found = result.scalar_one()
    assert found.id == model.id
    assert len(found.embedding) == 1024
    assert found.status == "PENDING"


@pytest.mark.asyncio
async def test_unique_image_id_constraint(session: AsyncSession):
    model1 = _make_embedding_model(image_id="img-dup")
    model2 = _make_embedding_model(image_id="img-dup")
    session.add(model1)
    await session.flush()

    session.add(model2)
    with pytest.raises(Exception):
        await session.flush()


@pytest.mark.asyncio
async def test_nullable_caption_embedding(session: AsyncSession):
    model = _make_embedding_model(image_id="img-no-caption", caption_embedding=None)
    session.add(model)
    await session.flush()

    result = await session.execute(select(ImageEmbeddingModel).where(ImageEmbeddingModel.image_id == "img-no-caption"))
    found = result.scalar_one()
    assert found.caption_embedding is None


@pytest.mark.asyncio
async def test_cosine_similarity_search(session: AsyncSession):
    import random

    random.seed(42)
    embeddings = []
    for i in range(5):
        emb = [random.random() for _ in range(1024)]
        model = _make_embedding_model(
            image_id=f"img-sim-{i}",
            embedding=emb,
            status="INDEXED",
        )
        embeddings.append((model, emb))
        session.add(model)
    await session.flush()

    query_vec = embeddings[0][1]
    distance_col = ImageEmbeddingModel.embedding.cosine_distance(query_vec)
    result = await session.execute(
        select(ImageEmbeddingModel).where(ImageEmbeddingModel.status == "INDEXED").order_by(distance_col).limit(3)
    )
    found = result.scalars().all()
    assert len(found) == 3
    assert found[0].image_id == "img-sim-0"

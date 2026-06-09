from datetime import datetime, timezone

from image_search.domain.entities import ImageEmbedding, ImageStatus


def test_image_status_enum_values():
    assert ImageStatus.PENDING == "PENDING"
    assert ImageStatus.EMBEDDED == "EMBEDDED"
    assert ImageStatus.INDEXED == "INDEXED"
    assert ImageStatus.FAILED == "FAILED"


def test_image_embedding_creation():
    now = datetime.now(tz=timezone.utc)
    entity = ImageEmbedding(
        id="uuid-1",
        image_id="img-001",
        embedding=[0.1] * 1024,
        caption_embedding=[0.2] * 768,
        model_name="siglip2-384",
        caption="A red car",
        file_path="/images/car.jpg",
        user_id="user-1",
        status=ImageStatus.INDEXED,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    assert entity.id == "uuid-1"
    assert len(entity.embedding) == 1024
    assert len(entity.caption_embedding) == 768
    assert entity.status == ImageStatus.INDEXED


def test_image_embedding_nullable_caption():
    now = datetime.now(tz=timezone.utc)
    entity = ImageEmbedding(
        id="uuid-2",
        image_id="img-002",
        embedding=[0.0] * 1024,
        caption_embedding=None,
        model_name="siglip2-384",
        caption=None,
        file_path="/images/dog.jpg",
        user_id="user-1",
        status=ImageStatus.PENDING,
        error_message="timeout",
        created_at=now,
        updated_at=now,
    )
    assert entity.caption is None
    assert entity.caption_embedding is None
    assert entity.error_message == "timeout"

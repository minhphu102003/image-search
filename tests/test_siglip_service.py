import math

import pytest

from image_search.infrastructure.ai.siglip_service import SigLIPEmbeddingService

# Skip all tests if torch/transformers not installed or model not available
pytest.importorskip("torch")
pytest.importorskip("transformers")


@pytest.fixture(scope="module")
def siglip():
    """Load SigLIP model once for all tests in this module."""
    try:
        return SigLIPEmbeddingService(device="cpu")
    except Exception as e:
        pytest.skip(f"Cannot load SigLIP model: {e}")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b)


@pytest.mark.asyncio
async def test_embed_image_returns_1024(siglip: SigLIPEmbeddingService) -> None:
    """Requires a test image file. Skip if not available."""
    import os

    test_image = os.path.join(os.path.dirname(__file__), "fixtures", "test_car.jpg")
    if not os.path.exists(test_image):
        pytest.skip("Test image not found at tests/fixtures/test_car.jpg")

    result = await siglip.embed_image(test_image)
    assert isinstance(result, list)
    assert len(result) == 1024
    assert all(isinstance(v, float) for v in result)


@pytest.mark.asyncio
async def test_embed_text_returns_1024(siglip: SigLIPEmbeddingService) -> None:
    result = await siglip.embed_text("a red car on the beach")
    assert isinstance(result, list)
    assert len(result) == 1024
    assert all(isinstance(v, float) for v in result)


@pytest.mark.asyncio
async def test_embed_texts_batch(siglip: SigLIPEmbeddingService) -> None:
    texts = ["a red car", "a blue sky", "a green tree"]
    results = await siglip.embed_texts_batch(texts)
    assert len(results) == 3
    assert all(len(v) == 1024 for v in results)


@pytest.mark.asyncio
async def test_semantic_similarity_texts(siglip: SigLIPEmbeddingService) -> None:
    """Related concepts should have higher similarity than unrelated ones."""
    car_emb = await siglip.embed_text("a red car")
    car_desc = await siglip.embed_text("a red car on the beach")
    cat_emb = await siglip.embed_text("a cat")

    sim_related = _cosine_similarity(car_emb, car_desc)
    sim_unrelated = _cosine_similarity(car_emb, cat_emb)

    assert sim_related > sim_unrelated, f"Expected related ({sim_related:.4f}) > unrelated ({sim_unrelated:.4f})"

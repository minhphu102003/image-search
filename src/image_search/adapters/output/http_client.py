"""HTTP client for external services (e.g. QGen Worker) to call Image Search API."""

import httpx
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()


class ImageResult(BaseModel):
    image_id: str
    file_path: str
    score: float
    caption: str | None = None


class ImageSearchResult(BaseModel):
    images: list[ImageResult]
    answer: str | None = None
    approach: int
    latency_ms: float


class ImageSearchClient:
    """Async HTTP client for the Image Search Service REST API."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 10.0,
        default_approach: int = 3,
        default_top_k: int = 5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.default_approach = default_approach
        self.default_top_k = default_top_k

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        approach: int | None = None,
    ) -> ImageSearchResult:
        """Search for images matching a text query.

        Returns an empty result on HTTP errors or timeouts so callers
        can always proceed without images.
        """
        resolved_approach = approach or self.default_approach
        payload = {
            "query": query,
            "top_k": top_k or self.default_top_k,
            "approach": resolved_approach,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/image-search",
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return ImageSearchResult.model_validate(response.json())
        except Exception as e:
            logger.warning("image_search_failed", error=str(e))
            return ImageSearchResult(images=[], approach=resolved_approach, latency_ms=0.0)

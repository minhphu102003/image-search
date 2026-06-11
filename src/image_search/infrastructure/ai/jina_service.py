import asyncio
import base64
from urllib.parse import urlparse

import httpx
import structlog

from image_search.domain.embedding_service import EmbeddingService

logger = structlog.get_logger()

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_DELAY = 1.0

_PRIVATE_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}


def _is_private_url(url: str) -> bool:
    """Check if a URL points to a private/localhost address unreachable by cloud APIs."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    if host in _PRIVATE_HOSTS:
        return True
    # Docker service names (e.g. "minio") have no dots — not publicly resolvable
    if "." not in host:
        return True
    if host.startswith("10.") or host.startswith("192.168."):
        return True
    if host.startswith("172."):
        try:
            second_octet = int(host.split(".")[1])
            return 16 <= second_octet <= 31
        except (IndexError, ValueError):
            return False
    return False


class JinaEmbeddingService(EmbeddingService):
    """Cloud embedding service using Jina AI API."""

    def __init__(
        self,
        api_key: str,
        model: str = "jina-embeddings-v4",
        api_url: str = "https://api.jina.ai/v1/embeddings",
        dimensions: int = 1024,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.api_url = api_url
        self.dimensions = dimensions
        self._client = httpx.AsyncClient(timeout=30.0)
        logger.info("jina_service_initialized", model=model, dimensions=dimensions)

    async def _call_api(self, inputs: list[dict[str, str]], task: str) -> list[list[float]]:
        """Call Jina embeddings API with retry on transient errors."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": self.model,
            "input": inputs,
            "task": task,
            "dimensions": self.dimensions,
        }

        logger.debug("jina_api_request", model=self.model, task=task, input_count=len(inputs))

        last_exc: Exception | None = None
        last_resp: httpx.Response | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await self._client.post(self.api_url, json=payload, headers=headers)
                last_resp = resp
                if resp.status_code in _RETRYABLE_STATUS:
                    delay = _BASE_DELAY * (2**attempt)
                    logger.warning(
                        "jina_api_retryable_error", status=resp.status_code, attempt=attempt + 1, delay_s=delay
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                data = resp.json()
                embeddings = [item["embedding"] for item in data["data"]]
                logger.debug(
                    "jina_api_response", embeddings_count=len(embeddings), dim=len(embeddings[0]) if embeddings else 0
                )
                return embeddings
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_exc = e
                delay = _BASE_DELAY * (2**attempt)
                logger.warning("jina_api_network_error", error=str(e), attempt=attempt + 1, delay_s=delay)
                await asyncio.sleep(delay)

        if last_exc:
            raise last_exc
        assert last_resp is not None
        last_resp.raise_for_status()
        return []  # unreachable, satisfies type checker

    @staticmethod
    def _file_to_base64(file_path: str) -> str:
        """Read local file and return base64-encoded data URI."""
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:image/jpeg;base64,{b64}"

    async def _resolve_image_input(self, image_path: str) -> dict[str, str]:
        """Resolve an image path/URL into an input dict for the Jina API.

        Public URLs are passed directly (Jina fetches them).
        Localhost/private URLs are downloaded and base64-encoded.
        Local file paths are base64-encoded.
        """
        if image_path.startswith("http://") or image_path.startswith("https://"):
            if _is_private_url(image_path):
                logger.debug("downloading_private_url", url=image_path[:120])
                resp = await self._client.get(image_path, follow_redirects=True)
                resp.raise_for_status()
                b64 = base64.b64encode(resp.content).decode()
                return {"image": f"data:image/jpeg;base64,{b64}"}
            logger.debug("embedding_image_from_url", url=image_path[:120])
            return {"image": image_path}
        logger.debug("embedding_image_from_path", path=image_path)
        return {"image": self._file_to_base64(image_path)}

    async def embed_image(self, image_path: str) -> list[float]:
        """Embed a single image via Jina API. Supports HTTP URLs and local file paths."""
        input_item = await self._resolve_image_input(image_path)

        results = await self._call_api([input_item], task="retrieval.passage")
        result = results[0]
        logger.debug("image_embedded", path=image_path, dim=len(result))
        return result

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string via Jina API."""
        logger.debug("embedding_text", text_preview=text[:80])
        results = await self._call_api([{"text": text}], task="retrieval.query")
        result = results[0]
        logger.debug("text_embedded", text_preview=text[:80], dim=len(result))
        return result

    async def embed_images_batch(self, image_paths: list[str]) -> list[list[float]]:
        """Embed multiple images in a single API call."""
        inputs = [await self._resolve_image_input(p) for p in image_paths]

        logger.debug("embedding_images_batch", count=len(inputs))
        results = await self._call_api(inputs, task="retrieval.passage")
        logger.debug("images_batch_embedded", count=len(results))
        return results

    async def embed_texts_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple text strings in a single API call."""
        inputs = [{"text": t} for t in texts]
        logger.debug("embedding_texts_batch", count=len(inputs))
        results = await self._call_api(inputs, task="retrieval.query")
        logger.debug("texts_batch_embedded", count=len(results))
        return results

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

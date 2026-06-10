import base64

import httpx
import structlog

from image_search.domain.embedding_service import EmbeddingService

logger = structlog.get_logger()


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
        """Call Jina embeddings API and return list of embedding vectors."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": self.model,
            "input": inputs,
            "task": task,
        }

        logger.debug("jina_api_request", model=self.model, task=task, input_count=len(inputs))

        resp = await self._client.post(self.api_url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        embeddings = [item["embedding"] for item in data["data"]]
        logger.debug("jina_api_response", embeddings_count=len(embeddings), dim=len(embeddings[0]) if embeddings else 0)
        return embeddings

    @staticmethod
    def _file_to_base64(file_path: str) -> str:
        """Read local file and return base64-encoded data URI."""
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:image/jpeg;base64,{b64}"

    async def embed_image(self, image_path: str) -> list[float]:
        """Embed a single image via Jina API. Supports HTTP URLs and local file paths."""
        if image_path.startswith("http://") or image_path.startswith("https://"):
            input_item: dict[str, str] = {"image": image_path}
            logger.debug("embedding_image_from_url", url=image_path[:120])
        else:
            input_item = {"image": self._file_to_base64(image_path)}
            logger.debug("embedding_image_from_path", path=image_path)

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
        inputs: list[dict[str, str]] = []
        for p in image_paths:
            if p.startswith("http://") or p.startswith("https://"):
                inputs.append({"image": p})
            else:
                inputs.append({"image": self._file_to_base64(p)})

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

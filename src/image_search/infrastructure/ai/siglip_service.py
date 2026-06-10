import os
import tempfile

import httpx
import structlog
import torch  # type: ignore[import-not-found]
from PIL import Image  # type: ignore[import-not-found]
from transformers import AutoModel, AutoProcessor  # type: ignore[import-not-found]

from image_search.domain.embedding_service import EmbeddingService

logger = structlog.get_logger()


class SigLIPEmbeddingService(EmbeddingService):
    """SigLIP 2 embedding service — loads model once, reuses for all requests."""

    def __init__(
        self,
        model_name: str = "google/siglip2-so400m-patch16-384",
        device: str | None = None,
    ) -> None:
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = model_name

        logger.info("loading_siglip_model", model=model_name, device=self.device)
        self.model = AutoModel.from_pretrained(model_name).to(self.device).eval()
        self.processor = AutoProcessor.from_pretrained(model_name)
        logger.info("siglip_model_loaded", model=model_name)

    @staticmethod
    async def _load_image(image_path: str) -> "Image.Image":
        if image_path.startswith("http://") or image_path.startswith("https://"):
            async with httpx.AsyncClient() as client:
                resp = await client.get(image_path, follow_redirects=True)
                resp.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.write(resp.content)
            tmp.close()
            image = Image.open(tmp.name).convert("RGB")
            os.unlink(tmp.name)
            return image
        return Image.open(image_path).convert("RGB")

    async def embed_image(self, image_path: str) -> list[float]:
        image = await self._load_image(image_path)
        inputs = self.processor(images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model.get_image_features(**inputs)
        result: list[float] = outputs[0].cpu().tolist()
        return result

    async def embed_text(self, text: str) -> list[float]:
        inputs = self.processor(text=[text], return_tensors="pt", padding=True).to(self.device)
        with torch.no_grad():
            outputs = self.model.get_text_features(**inputs)
        result: list[float] = outputs[0].cpu().tolist()
        return result

    async def embed_images_batch(self, image_paths: list[str]) -> list[list[float]]:
        images = [await self._load_image(p) for p in image_paths]
        inputs = self.processor(images=images, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model.get_image_features(**inputs)
        result: list[list[float]] = outputs.cpu().tolist()
        return result

    async def embed_texts_batch(self, texts: list[str]) -> list[list[float]]:
        inputs = self.processor(text=texts, return_tensors="pt", padding=True).to(self.device)
        with torch.no_grad():
            outputs = self.model.get_text_features(**inputs)
        result: list[list[float]] = outputs.cpu().tolist()
        return result

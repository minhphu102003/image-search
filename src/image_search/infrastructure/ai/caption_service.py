import os
import tempfile
from typing import Any

import httpx
import structlog

from image_search.domain.caption_service import CaptionService
from image_search.domain.prompts import CAPTION_PROMPT

logger = structlog.get_logger()


class GeminiCaptionService(CaptionService):
    """Caption service using Google Gemini API. Requires google-generativeai package."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        prompt: str = CAPTION_PROMPT,
    ) -> None:
        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(model)
        except ImportError:
            raise ImportError("google-generativeai is required. Install with: uv sync --extra ai")
        self.prompt = prompt

    @staticmethod
    async def _load_image(image_path: str) -> Any:
        """Load image from local path or HTTP URL."""
        from PIL import Image

        if image_path.startswith("http://") or image_path.startswith("https://"):
            logger.debug("caption_loading_image_from_url", url=image_path[:120])
            async with httpx.AsyncClient() as client:
                resp = await client.get(image_path, follow_redirects=True)
                resp.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.write(resp.content)
            tmp.close()
            image = Image.open(tmp.name).convert("RGB")
            os.unlink(tmp.name)
            logger.debug("caption_image_loaded", source="url", size=f"{image.width}x{image.height}")
            return image

        logger.debug("caption_loading_image_from_path", path=image_path)
        image = Image.open(image_path).convert("RGB")
        logger.debug("caption_image_loaded", source="local", size=f"{image.width}x{image.height}")
        return image

    async def generate_caption(self, image_path: str) -> str:
        import asyncio
        import time

        image = await self._load_image(image_path)
        logger.info(
            "caption_started",
            image_path=image_path,
            image_size=f"{image.width}x{image.height}",
            prompt=self.prompt[:100],
        )

        start = time.time()
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: self.model.generate_content([self.prompt, image]))
        elapsed = time.time() - start
        caption: str = response.text.strip()

        logger.info(
            "caption_completed",
            image_path=image_path,
            caption=caption,
            caption_length=len(caption),
            elapsed_s=round(elapsed, 2),
            model=self.model._model_name if hasattr(self.model, "_model_name") else "unknown",
        )
        return caption

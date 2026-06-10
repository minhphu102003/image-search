import structlog

from image_search.domain.caption_service import CaptionService

logger = structlog.get_logger()


class GeminiCaptionService(CaptionService):
    """Caption service using Google Gemini API. Requires google-generativeai package."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        try:
            import google.generativeai as genai  # type: ignore[import-not-found]

            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(model)
        except ImportError:
            raise ImportError("google-generativeai is required. Install with: uv sync --extra ai")

    async def generate_caption(self, image_path: str) -> str:
        import asyncio
        import time

        from PIL import Image  # type: ignore[import-not-found]

        image = Image.open(image_path)
        prompt = "Describe this image in one sentence."
        logger.info(
            "caption_started",
            image_path=image_path,
            image_size=f"{image.width}x{image.height}",
            image_format=image.format,
            prompt=prompt,
        )

        start = time.time()
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: self.model.generate_content([prompt, image]))
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

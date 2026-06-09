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

        from PIL import Image  # type: ignore[import-not-found]

        logger.info("generating_caption", image_path=image_path)
        image = Image.open(image_path)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: self.model.generate_content(["Describe this image in one sentence.", image])
        )
        caption: str = response.text.strip()
        logger.info("caption_generated", image_path=image_path, caption=caption)
        return caption

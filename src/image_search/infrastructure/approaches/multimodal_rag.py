import structlog

from image_search.domain.ports.repositories import ImageEmbeddingRepositoryPort
from image_search.domain.search_approach import SearchApproach, SearchResponse, SearchResult

logger = structlog.get_logger()

SYSTEM_PROMPT = """You are an image analysis assistant for an education platform.
Given a set of images and a user question:
1. Identify which images are relevant to the question
2. Describe what you see in the relevant images
3. Provide a concise, informative answer grounded in the images
4. Reference specific images by their position (Image 1, Image 2, etc.)"""


class MultimodalRAGApproach(SearchApproach):
    def __init__(
        self,
        repository: ImageEmbeddingRepositoryPort,
        gemini_api_key: str,
        top_k_retrieve: int = 5,
        gemini_model: str = "gemini-2.0-flash",
    ) -> None:
        import google.generativeai as genai  # type: ignore[import-not-found]

        self.repository = repository
        self.top_k_retrieve = top_k_retrieve
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel(gemini_model, system_instruction=SYSTEM_PROMPT)

    async def search(self, query_vector: list[float], top_k: int, query_text: str) -> SearchResponse:
        rows = await self.repository.search_by_embedding_with_scores(
            query_embedding=query_vector,
            limit=self.top_k_retrieve,
        )

        if not rows:
            return SearchResponse(images=[], answer=None)

        images = [
            SearchResult(
                image_id=entity.image_id,
                file_path=entity.file_path,
                score=round(score, 4),
                caption=entity.caption,
            )
            for entity, score in rows
        ]

        image_parts = self._load_images(images)
        answer = await self._generate_answer(query_text, image_parts)

        return SearchResponse(images=images, answer=answer)

    def _load_images(self, images: list[SearchResult]) -> list[object]:
        from PIL import Image  # type: ignore[import-not-found]

        parts: list[object] = []
        for img in images:
            try:
                parts.append(Image.open(img.file_path))
            except Exception as e:
                logger.warning("image_load_failed", path=img.file_path, error=str(e))
        return parts

    async def _generate_answer(self, query_text: str, image_parts: list[object]) -> str | None:
        if not image_parts:
            return None

        try:
            user_message = (
                f"User question: {query_text}\n\n"
                f"Analyze the following {len(image_parts)} images and answer the question."
            )
            prompt_parts = [user_message] + image_parts
            response = await self.model.generate_content_async(prompt_parts)
            return str(response.text.strip())
        except Exception as e:
            logger.error("gemini_failed", error=str(e))
            return None

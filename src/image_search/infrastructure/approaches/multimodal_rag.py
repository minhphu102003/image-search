import structlog

from image_search.domain.prompts import RAG_SYSTEM_PROMPT
from image_search.domain.ports.repositories import ImageEmbeddingRepositoryPort
from image_search.domain.search_approach import SearchApproach, SearchResponse, SearchResult
from image_search.infrastructure.config import settings

logger = structlog.get_logger()


class MultimodalRAGApproach(SearchApproach):
    def __init__(
        self,
        repository: ImageEmbeddingRepositoryPort,
        gemini_api_key: str,
        top_k_retrieve: int = 5,
        gemini_model: str = "gemini-2.5-flash",
    ) -> None:
        from google import genai
        from google.genai import types

        self.repository = repository
        self.top_k_retrieve = top_k_retrieve
        self.client = genai.Client(api_key=gemini_api_key)
        self.model_name = gemini_model
        self.gen_config = types.GenerateContentConfig(system_instruction=RAG_SYSTEM_PROMPT)

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
            if score >= settings.min_score_threshold
        ]

        image_parts = self._load_images(images)
        answer = await self._generate_answer(query_text, image_parts)

        return SearchResponse(images=images, answer=answer)

    def _load_images(self, images: list[SearchResult]) -> list[object]:
        from PIL import Image

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
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt_parts,
                config=self.gen_config,
            )
            return str(response.text.strip())
        except Exception as e:
            logger.error("gemini_failed", error=str(e))
            return None

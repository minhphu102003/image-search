from abc import ABC, abstractmethod


class EmbeddingService(ABC):
    @abstractmethod
    async def embed_image(self, image_path: str) -> list[float]:
        """Embed a single image file -> 1024-dim vector."""
        ...

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string -> 1024-dim vector."""
        ...

    @abstractmethod
    async def embed_images_batch(self, image_paths: list[str]) -> list[list[float]]:
        """Embed multiple images in one forward pass."""
        ...

    @abstractmethod
    async def embed_texts_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in one forward pass."""
        ...

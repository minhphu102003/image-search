from abc import ABC, abstractmethod


class CaptionService(ABC):
    @abstractmethod
    async def generate_caption(self, image_path: str) -> str:
        raise NotImplementedError

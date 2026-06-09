from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SearchResult:
    image_id: str
    file_path: str
    score: float
    caption: str | None = None


@dataclass
class SearchResponse:
    images: list[SearchResult]
    answer: str | None = None


class SearchApproach(ABC):
    @abstractmethod
    async def search(self, query_vector: list[float], top_k: int, query_text: str) -> SearchResponse:
        raise NotImplementedError

"""Base retrieval interfaces."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class RetrievalResult:
    chunk_id: UUID
    document_id: UUID
    content: str
    score: float
    metadata: dict = field(default_factory=dict)
    source: str = ""  # "vector", "fulltext", "hybrid"


class BaseRetriever(ABC):
    """Abstract base for retrieval strategies."""

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        workspace_id: UUID,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        ...

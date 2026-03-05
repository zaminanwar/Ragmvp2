"""Base embedding interface with provider abstraction (AnythingLLM pattern)."""

from abc import ABC, abstractmethod


class BaseEmbedding(ABC):
    """Abstract base for all embedding providers."""

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text."""
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return embedding dimensions."""
        ...

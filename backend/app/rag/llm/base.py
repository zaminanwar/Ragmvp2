"""Base LLM interface with provider abstraction (AnythingLLM pattern)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    metadata: dict = field(default_factory=dict)


class BaseLLM(ABC):
    """Abstract base for all LLM providers."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a complete response."""
        ...

    @abstractmethod
    async def generate_stream(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream response tokens."""
        ...

    @abstractmethod
    async def generate_with_messages(
        self,
        messages: list[dict],
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate from a list of messages."""
        ...

    @abstractmethod
    async def stream_with_messages(
        self,
        messages: list[dict],
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream from a list of messages."""
        ...

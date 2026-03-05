"""Anthropic Claude LLM provider."""

from typing import AsyncIterator

import anthropic

from app.config import get_settings
from app.rag.llm.base import BaseLLM, LLMResponse


class AnthropicProvider(BaseLLM):
    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str | None = None):
        settings = get_settings()
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        """Extract system message and convert to Anthropic format."""
        system = None
        converted = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                converted.append({"role": msg["role"], "content": msg["content"]})
        return system, converted

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        messages = [{"role": "user", "content": prompt}]
        return await self.generate_with_messages(
            messages, system=system, temperature=temperature, max_tokens=max_tokens
        )

    async def generate_stream(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        messages = [{"role": "user", "content": prompt}]
        async for token in self.stream_with_messages(
            messages, system=system, temperature=temperature, max_tokens=max_tokens
        ):
            yield token

    async def generate_with_messages(
        self,
        messages: list[dict],
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        extracted_system, converted = self._convert_messages(messages)
        system = system or extracted_system

        kwargs = {
            "model": self.model,
            "messages": converted,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system:
            kwargs["system"] = system

        response = await self._client.messages.create(**kwargs)

        return LLMResponse(
            content=response.content[0].text,
            model=self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    async def stream_with_messages(
        self,
        messages: list[dict],
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        extracted_system, converted = self._convert_messages(messages)
        system = system or extracted_system

        kwargs = {
            "model": self.model,
            "messages": converted,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system:
            kwargs["system"] = system

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

"""OpenAI LLM provider."""

from typing import AsyncIterator

import openai

from app.config import get_settings
from app.rag.llm.base import BaseLLM, LLMResponse


class OpenAIProvider(BaseLLM):
    def __init__(self, model: str | None = None, api_key: str | None = None):
        settings = get_settings()
        self.model = model or settings.default_llm_model
        self._client = openai.AsyncOpenAI(api_key=api_key or settings.openai_api_key)

    def _build_messages(
        self, prompt: str, system: str | None = None
    ) -> list[dict]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        messages = self._build_messages(prompt, system)
        return await self.generate_with_messages(messages, temperature=temperature, max_tokens=max_tokens)

    async def generate_stream(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        messages = self._build_messages(prompt, system)
        async for token in self.stream_with_messages(messages, temperature=temperature, max_tokens=max_tokens):
            yield token

    async def generate_with_messages(
        self,
        messages: list[dict],
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        if system:
            messages = [{"role": "system", "content": system}] + [
                m for m in messages if m["role"] != "system"
            ]

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        choice = response.choices[0]
        usage = response.usage

        return LLMResponse(
            content=choice.message.content or "",
            model=self.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    async def stream_with_messages(
        self,
        messages: list[dict],
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        if system:
            messages = [{"role": "system", "content": system}] + [
                m for m in messages if m["role"] != "system"
            ]

        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

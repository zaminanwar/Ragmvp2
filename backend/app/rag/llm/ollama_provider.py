"""Ollama local LLM provider."""

from typing import AsyncIterator

import httpx

from app.config import get_settings
from app.rag.llm.base import BaseLLM, LLMResponse


class OllamaProvider(BaseLLM):
    def __init__(self, model: str = "llama3.1", base_url: str | None = None):
        settings = get_settings()
        self.model = model
        self.base_url = base_url or settings.ollama_base_url

    def _build_messages(self, prompt: str, system: str | None = None) -> list[dict]:
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

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()

        return LLMResponse(
            content=data["message"]["content"],
            model=self.model,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
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

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
                timeout=120,
            ) as response:
                import json
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        if not data.get("done", False):
                            yield data["message"]["content"]

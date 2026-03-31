"""Google Gemini LLM provider via Vertex AI."""

import json
import os
import tempfile
from typing import AsyncIterator

from google import genai
from google.genai import types
from google.oauth2 import service_account

from app.config import get_settings
from app.rag.llm.base import BaseLLM, LLMResponse


def _build_gemini_client() -> genai.Client:
    """Build a Gemini client using service account credentials or ADC."""
    settings = get_settings()

    credentials = None
    if settings.google_service_account_json:
        info = json.loads(settings.google_service_account_json)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    elif settings.google_application_credentials:
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_application_credentials,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )

    return genai.Client(
        vertexai=True,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        credentials=credentials,
    )


class GeminiProvider(BaseLLM):
    def __init__(self, model: str = "gemini-2.0-flash", api_key: str | None = None):
        settings = get_settings()
        self.model = model

        if api_key:
            # Direct API key usage (AI Studio, not Vertex)
            self._client = genai.Client(api_key=api_key)
        else:
            self._client = _build_gemini_client()

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[types.Content]]:
        """Extract system instruction and convert messages to Gemini format."""
        system = None
        contents = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                role = "model" if msg["role"] == "assistant" else "user"
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg["content"])],
                ))
        return system, contents

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        return await self.generate_with_messages(
            messages, temperature=temperature, max_tokens=max_tokens
        )

    async def generate_stream(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        async for token in self.stream_with_messages(
            messages, temperature=temperature, max_tokens=max_tokens
        ):
            yield token

    async def generate_with_messages(
        self,
        messages: list[dict],
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        extracted_system, contents = self._convert_messages(messages)
        system = system or extracted_system

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system:
            config.system_instruction = system

        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )

        input_tokens = 0
        output_tokens = 0
        if response.usage_metadata:
            input_tokens = response.usage_metadata.prompt_token_count or 0
            output_tokens = response.usage_metadata.candidates_token_count or 0

        return LLMResponse(
            content=response.text or "",
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def stream_with_messages(
        self,
        messages: list[dict],
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        extracted_system, contents = self._convert_messages(messages)
        system = system or extracted_system

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system:
            config.system_instruction = system

        async for chunk in await self._client.aio.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=config,
        ):
            if chunk.text:
                yield chunk.text

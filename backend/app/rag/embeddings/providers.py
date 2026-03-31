"""Embedding providers - OpenAI, Gemini, Ollama, and sentence-transformers."""

import json

import httpx
import openai
from google import genai
from google.oauth2 import service_account

from app.config import get_settings
from app.rag.embeddings.base import BaseEmbedding


class OpenAIEmbedding(BaseEmbedding):
    """OpenAI embeddings (text-embedding-3-small/large, ada-002)."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        settings = get_settings()
        self.model = model or settings.default_embedding_model
        self._client = openai.AsyncOpenAI(api_key=api_key or settings.openai_api_key)
        self._dims = settings.embedding_dimensions

    async def embed_text(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(input=[text], model=self.model)
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # OpenAI supports batches up to 2048
        all_embeddings = []
        batch_size = 512
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = await self._client.embeddings.create(input=batch, model=self.model)
            all_embeddings.extend([d.embedding for d in response.data])
        return all_embeddings

    @property
    def dimensions(self) -> int:
        return self._dims


class OllamaEmbedding(BaseEmbedding):
    """Ollama local embeddings."""

    def __init__(self, model: str = "nomic-embed-text", base_url: str | None = None):
        settings = get_settings()
        self.model = model
        self.base_url = base_url or settings.ollama_base_url
        self._dims = 768  # Default for nomic-embed-text

    async def embed_text(self, text: str) -> list[float]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=60,
            )
            response.raise_for_status()
            return response.json()["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            emb = await self.embed_text(text)
            embeddings.append(emb)
        return embeddings

    @property
    def dimensions(self) -> int:
        return self._dims


class GeminiEmbedding(BaseEmbedding):
    """Google Gemini embeddings via Vertex AI."""

    def __init__(self, model: str = "text-embedding-004", **kwargs):
        settings = get_settings()
        self.model = model
        self._dims = 768

        credentials = None
        if settings.google_service_account_json:
            info = json.loads(settings.google_service_account_json)
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        elif settings.google_application_credentials:
            credentials = service_account.Credentials.from_service_account_file(
                settings.google_application_credentials,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )

        self._client = genai.Client(
            vertexai=True,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            credentials=credentials,
        )

    async def embed_text(self, text: str) -> list[float]:
        response = await self._client.aio.models.embed_content(
            model=self.model,
            contents=text,
        )
        return response.embeddings[0].values

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        all_embeddings = []
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = await self._client.aio.models.embed_content(
                model=self.model,
                contents=batch,
            )
            all_embeddings.extend([e.values for e in response.embeddings])
        return all_embeddings

    @property
    def dimensions(self) -> int:
        return self._dims


def get_embedding_provider(provider: str | None = None, **kwargs) -> BaseEmbedding:
    """Factory for embedding providers."""
    settings = get_settings()
    provider = provider or settings.default_embedding_provider

    providers = {
        "openai": OpenAIEmbedding,
        "gemini": GeminiEmbedding,
        "ollama": OllamaEmbedding,
    }
    cls = providers.get(provider, OpenAIEmbedding)
    return cls(**kwargs)

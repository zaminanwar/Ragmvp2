"""Embedding providers - OpenAI, Ollama, and sentence-transformers."""

import httpx
import openai

from app.config import get_settings
from app.rag.embeddings.base import BaseEmbedding


class OpenAIEmbedding(BaseEmbedding):
    """OpenAI embeddings (text-embedding-3-small/large, ada-002)."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        settings = get_settings()
        self.model = model or settings.default_embedding_model
        self._client = openai.AsyncOpenAI(
            api_key=api_key or settings.openai_api_key,
            http_client=httpx.AsyncClient(verify=False),
        )
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


class AzureOpenAIEmbedding(BaseEmbedding):
    """Azure OpenAI embeddings."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        settings = get_settings()
        self.model = model or settings.azure_openai_embedding_deployment or settings.default_embedding_model
        self._client = openai.AsyncAzureOpenAI(
            api_key=api_key or settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
            http_client=httpx.AsyncClient(verify=False),
        )
        self._dims = settings.embedding_dimensions

    async def embed_text(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(input=[text], model=self.model)
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
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


def get_embedding_provider(provider: str | None = None, **kwargs) -> BaseEmbedding:
    """Factory for embedding providers."""
    settings = get_settings()
    provider = provider or settings.default_embedding_provider

    providers = {
        "openai": OpenAIEmbedding,
        "azure_openai": AzureOpenAIEmbedding,
        "ollama": OllamaEmbedding,
    }
    cls = providers.get(provider, OpenAIEmbedding)
    return cls(**kwargs)

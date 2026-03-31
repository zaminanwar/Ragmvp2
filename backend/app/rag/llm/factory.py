"""LLM provider factory (AnythingLLM's provider abstraction pattern)."""

from app.config import get_settings
from app.rag.llm.base import BaseLLM
from app.rag.llm.openai_provider import OpenAIProvider
from app.rag.llm.anthropic_provider import AnthropicProvider
from app.rag.llm.ollama_provider import OllamaProvider
from app.rag.llm.azure_openai_provider import AzureOpenAIProvider
from app.rag.llm.gemini_provider import GeminiProvider


def get_llm_provider(
    provider: str | None = None,
    model: str | None = None,
    **kwargs,
) -> BaseLLM:
    """Factory for LLM providers."""
    settings = get_settings()
    provider = provider or settings.default_llm_provider

    providers = {
        "openai": lambda: OpenAIProvider(model=model or settings.default_llm_model, **kwargs),
        "azure_openai": lambda: AzureOpenAIProvider(model=model or settings.azure_openai_deployment, **kwargs),
        "anthropic": lambda: AnthropicProvider(model=model or "claude-sonnet-4-20250514", **kwargs),
        "ollama": lambda: OllamaProvider(model=model or "llama3.1", **kwargs),
        "gemini": lambda: GeminiProvider(model=model or settings.default_llm_model, **kwargs),
    }

    factory = providers.get(provider)
    if factory is None:
        raise ValueError(f"Unknown LLM provider: {provider}. Available: {list(providers.keys())}")

    return factory()

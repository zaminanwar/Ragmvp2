"""Model management routes - list available LLM and embedding providers."""

import httpx
from fastapi import APIRouter

from app.api.deps import CurrentUser, SettingsDep

router = APIRouter()


@router.get("/providers")
async def list_providers(user: CurrentUser, settings: SettingsDep):
    """List available LLM providers and their models."""
    providers = []

    # OpenAI
    if settings.openai_api_key:
        providers.append({
            "id": "openai",
            "name": "OpenAI",
            "models": [
                "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo",
                "o1-preview", "o1-mini",
            ],
            "embedding_models": [
                "text-embedding-3-small", "text-embedding-3-large", "text-embedding-ada-002",
            ],
        })

    # Anthropic
    if settings.anthropic_api_key:
        providers.append({
            "id": "anthropic",
            "name": "Anthropic",
            "models": [
                "claude-opus-4-20250514", "claude-sonnet-4-20250514",
                "claude-3-5-haiku-20241022",
            ],
            "embedding_models": [],
        })

    # Ollama (local)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                ollama_models = [m["name"] for m in resp.json().get("models", [])]
                providers.append({
                    "id": "ollama",
                    "name": "Ollama (Local)",
                    "models": ollama_models,
                    "embedding_models": ["nomic-embed-text", "mxbai-embed-large"],
                })
    except Exception:
        providers.append({
            "id": "ollama",
            "name": "Ollama (Local)",
            "models": [],
            "embedding_models": [],
            "status": "offline",
        })

    return {"providers": providers}


@router.get("/default")
async def get_defaults(user: CurrentUser, settings: SettingsDep):
    """Get current default model configuration."""
    return {
        "llm_provider": settings.default_llm_provider,
        "llm_model": settings.default_llm_model,
        "embedding_provider": settings.default_embedding_provider,
        "embedding_model": settings.default_embedding_model,
        "temperature": settings.default_temperature,
    }

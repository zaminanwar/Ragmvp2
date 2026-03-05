"""Enterprise RAG System - Main FastAPI Application."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from app.api.routes import auth, chat, documents, workspaces, admin, models as models_route, evaluation

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    settings = get_settings()
    logger.info("Starting Enterprise RAG System", env=settings.app_env)

    # Initialize services on startup
    from app.services.storage_service import StorageService
    storage = StorageService()
    await storage.ensure_bucket()
    logger.info("Storage initialized")

    yield

    logger.info("Shutting down Enterprise RAG System")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Enterprise RAG System",
        description=(
            "State-of-the-art Retrieval-Augmented Generation platform with agentic RAG "
            "(adaptive routing, corrective retrieval, self-reflective generation), "
            "hybrid search with RRF, HyDE, query decomposition, knowledge graph, "
            "contextual embeddings, multi-provider LLM support, workspace isolation, and RBAC."
        ),
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Custom middleware
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware, requests_per_minute=120)

    # Register routers
    app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
    app.include_router(workspaces.router, prefix="/api/workspaces", tags=["Workspaces"])
    app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
    app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
    app.include_router(models_route.router, prefix="/api/models", tags=["Models"])
    app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
    app.include_router(evaluation.router, prefix="/api/eval", tags=["Evaluation"])

    @app.get("/api/health")
    async def health_check():
        return {"status": "healthy", "service": settings.app_name, "version": "1.0.0"}

    return app


app = create_app()

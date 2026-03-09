"""Enterprise RAG System - Main FastAPI Application."""

import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.core.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from app.api.routes import auth, chat, documents, workspaces, admin, models as models_route, evaluation, workflows

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

    # Register workflow tools
    from app.workflows.tools.registry import register_all_tools
    register_all_tools()

    # Register Polarion ALM tools if configured
    if settings.polarion_base_url:
        from app.adapters.polarion.tools import (
            AlmGetSchemaTool, AlmCreateWorkitemsTool, AlmGetWorkitemsTool,
            AlmUpdateWorkitemsTool, AlmCreateLinksTool,
        )
        from app.workflows.tools.registry import ToolRegistry
        for tool_cls in [AlmGetSchemaTool, AlmCreateWorkitemsTool, AlmGetWorkitemsTool,
                         AlmUpdateWorkitemsTool, AlmCreateLinksTool]:
            ToolRegistry.register(tool_cls())

    # Start workflow scheduler if enabled
    scheduler = None
    if settings.enable_workflow_worker:
        import asyncio
        import redis.asyncio as aioredis
        from app.models.base import get_session_factory
        from app.workflows.engine.scheduler import WorkflowScheduler

        redis_client = aioredis.from_url(settings.redis_url)
        session_factory = get_session_factory()
        scheduler = WorkflowScheduler(redis_client, session_factory)
        asyncio.create_task(scheduler.start_worker())
        logger.info("Workflow scheduler started")

    yield

    # Shutdown
    if scheduler:
        await scheduler.stop()
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
    app.include_router(workflows.router, prefix="/api/workflows", tags=["Workflows"])

    # Serve exported files (compliance reports, etc.)
    exports_dir = os.path.join(os.path.dirname(__file__), "..", "exports")
    os.makedirs(exports_dir, exist_ok=True)
    app.mount("/api/exports", StaticFiles(directory=exports_dir), name="exports")

    @app.get("/api/health")
    async def health_check():
        return {"status": "healthy", "service": settings.app_name, "version": "1.0.0"}

    return app


app = create_app()

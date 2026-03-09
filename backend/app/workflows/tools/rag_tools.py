"""RAG workflow tools — wraps existing RAGEngine for use in workflows."""

from __future__ import annotations

import uuid

import structlog

from app.config import get_settings
from app.models.base import get_session_factory
from app.models.workspace import Workspace
from app.rag.embeddings.providers import get_embedding_provider
from app.rag.engine import RAGEngine
from app.rag.llm.factory import get_llm_provider
from app.rag.retrieval.hybrid_search import HybridRetriever
from app.rag.retrieval.reranker import CohereReranker, LLMReranker
from app.workflows.tools.base import BaseTool, ToolInput, ToolOutput

logger = structlog.get_logger(__name__)


async def _build_engine_for_workspace(workspace_id: str) -> tuple[RAGEngine, "AsyncSession"]:
    """Build a RAGEngine from a workspace's config, similar to ChatService._build_engine."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    session_factory = get_session_factory()
    db = session_factory()

    result = await db.execute(
        select(Workspace).where(Workspace.id == uuid.UUID(workspace_id))
    )
    workspace = result.scalar_one()

    llm = get_llm_provider(provider=workspace.llm_provider, model=workspace.llm_model)
    embedding = get_embedding_provider(provider=workspace.embedding_provider)
    retriever = HybridRetriever(db, embedding, enable_graph=getattr(workspace, "enable_knowledge_graph", False))

    reranker = None
    if workspace.enable_reranking:
        settings = get_settings()
        cohere_key = getattr(settings, "cohere_api_key", None)
        if cohere_key:
            reranker = CohereReranker(api_key=cohere_key)
        else:
            reranker = LLMReranker(llm)

    engine = RAGEngine(
        llm=llm,
        retriever=retriever,
        reranker=reranker,
        embedding_provider=embedding,
        enable_reranking=workspace.enable_reranking,
        enable_hyde=getattr(workspace, "enable_hyde", False),
        enable_query_decomposition=getattr(workspace, "enable_query_decomposition", False),
        enable_adaptive_routing=getattr(workspace, "enable_adaptive_routing", True),
        enable_self_reflection=getattr(workspace, "enable_self_reflection", True),
    )
    return engine, db


class RagQueryTool(BaseTool):
    name = "rag.query"
    description = "Query the RAG engine against a workspace's document corpus."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The query text"},
            "workspace_id": {"type": "string", "description": "Workspace to query against"},
            "system_prompt": {"type": "string"},
            "top_k": {"type": "integer", "default": 5},
        },
        "required": ["query", "workspace_id"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "citations": {"type": "array"},
            "model": {"type": "string"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        workspace_id = params.get("workspace_id") or tool_input.context.get("workspace_id")

        try:
            engine, db = await _build_engine_for_workspace(workspace_id)
            try:
                response = await engine.query(
                    query=params["query"],
                    workspace_id=uuid.UUID(workspace_id),
                    system_prompt=params.get("system_prompt"),
                    top_k=params.get("top_k", 5),
                )
                return ToolOutput(
                    success=True,
                    data={
                        "content": response.content,
                        "citations": [
                            {
                                "excerpt": c.get("excerpt", "") if isinstance(c, dict) else getattr(c, "excerpt", ""),
                                "relevance_score": c.get("relevance_score", 0) if isinstance(c, dict) else getattr(c, "relevance_score", 0),
                            }
                            for c in (response.citations or [])
                        ],
                        "model": response.model,
                    },
                    metadata={
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                    },
                )
            finally:
                await db.close()
        except Exception as e:
            logger.exception("rag_query_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))


class RagBatchQueryTool(BaseTool):
    name = "rag.batch_query"
    description = "Run multiple RAG queries against a workspace (used in compliance checks)."
    input_schema = {
        "type": "object",
        "properties": {
            "queries": {"type": "array", "items": {"type": "string"}},
            "workspace_id": {"type": "string"},
            "system_prompt": {"type": "string"},
        },
        "required": ["queries", "workspace_id"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "results": {"type": "array"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        workspace_id = params.get("workspace_id") or tool_input.context.get("workspace_id")
        queries = params["queries"]

        try:
            engine, db = await _build_engine_for_workspace(workspace_id)
            try:
                results = []
                for q in queries:
                    query_text = q if isinstance(q, str) else q.get("title", q.get("description", str(q)))
                    response = await engine.query(
                        query=query_text,
                        workspace_id=uuid.UUID(workspace_id),
                        system_prompt=params.get("system_prompt"),
                    )
                    results.append({
                        "query": query_text,
                        "content": response.content,
                        "citations": [
                            {
                                "excerpt": c.get("excerpt", "") if isinstance(c, dict) else getattr(c, "excerpt", ""),
                                "relevance_score": c.get("relevance_score", 0) if isinstance(c, dict) else getattr(c, "relevance_score", 0),
                            }
                            for c in (response.citations or [])
                        ],
                    })
                return ToolOutput(success=True, data={"results": results})
            finally:
                await db.close()
        except Exception as e:
            logger.exception("rag_batch_query_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))


class RagIngestTool(BaseTool):
    name = "rag.ingest"
    description = "Ingest a document into a workspace's RAG corpus."
    input_schema = {
        "type": "object",
        "properties": {
            "file_content": {"type": "string", "description": "Base64-encoded file content"},
            "filename": {"type": "string"},
            "workspace_id": {"type": "string"},
        },
        "required": ["file_content", "filename", "workspace_id"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "document_id": {"type": "string"},
            "chunk_count": {"type": "integer"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        import base64

        params = tool_input.params
        workspace_id = params.get("workspace_id") or tool_input.context.get("workspace_id")

        try:
            from app.services.document_service import DocumentService

            session_factory = get_session_factory()
            async with session_factory() as db:
                service = DocumentService(db)
                file_bytes = base64.b64decode(params["file_content"])
                doc = await service.upload_and_process(
                    file_content=file_bytes,
                    filename=params["filename"],
                    workspace_id=uuid.UUID(workspace_id),
                )
                await db.commit()
                return ToolOutput(
                    success=True,
                    data={
                        "document_id": str(doc.id),
                        "filename": doc.filename,
                        "chunk_count": getattr(doc, "chunk_count", 0),
                    },
                )
        except Exception as e:
            logger.exception("rag_ingest_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))

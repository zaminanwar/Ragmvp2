"""Core RAG Engine - Agentic orchestration with adaptive, corrective, and self-reflective RAG.

Combines:
- Adaptive RAG: Query routing to optimal retrieval strategy
- Corrective RAG: Grading + query rewriting loop
- Self-Reflective RAG: Hallucination detection + regeneration
- Hybrid Search: Vector + BM25 with RRF fusion
- Reranking: LLM-based or Cohere API
- HyDE: Hypothetical Document Embeddings
- Query Decomposition: Multi-hop question handling
"""

import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator

import structlog

from app.rag.agent.graph import build_rag_graph
from app.rag.llm.base import BaseLLM, LLMResponse
from app.rag.retrieval.base import RetrievalResult

logger = structlog.get_logger()


@dataclass
class RAGContext:
    """Context assembled for generation."""
    chunks: list[RetrievalResult] = field(default_factory=list)
    was_corrective: bool = False
    original_query: str = ""
    rewritten_query: str | None = None
    agent_trace: list[str] = field(default_factory=list)
    search_mode_used: str = ""


@dataclass
class RAGResponse:
    """Full RAG response with citations."""
    content: str
    citations: list[dict] = field(default_factory=list)
    context: RAGContext | None = None
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class RAGEngine:
    """Agentic RAG orchestration engine.

    Uses a LangGraph state machine when available, with a linear fallback.
    All features are toggleable per workspace.
    """

    def __init__(
        self,
        llm: BaseLLM,
        retriever,
        reranker=None,
        embedding_provider=None,
        enable_corrective_rag: bool = True,
        enable_reranking: bool = False,
        enable_hyde: bool = False,
        enable_query_decomposition: bool = False,
        enable_adaptive_routing: bool = True,
        enable_self_reflection: bool = True,
        relevance_threshold: float = 0.3,
        max_correction_attempts: int = 3,
    ):
        self.llm = llm
        self.retriever = retriever
        self.reranker = reranker
        self.embedding_provider = embedding_provider

        # Build the agentic graph
        self._graph = build_rag_graph(
            llm=llm,
            retriever=retriever,
            reranker=reranker,
            embedding_provider=embedding_provider,
            enable_reranking=enable_reranking,
            enable_hyde=enable_hyde,
            enable_decomposition=enable_query_decomposition,
        )

        self._enable_reranking = enable_reranking
        self._enable_hyde = enable_hyde
        self._enable_query_decomposition = enable_query_decomposition

    def _build_initial_state(
        self,
        query: str,
        workspace_id: uuid.UUID,
        system_prompt: str | None = None,
        chat_history: list[dict] | None = None,
        top_k: int = 5,
    ) -> dict:
        """Build the initial state dict for the agent graph."""
        return {
            "question": query,
            "workspace_id": str(workspace_id),
            "chat_history": chat_history or [],
            "system_prompt": system_prompt or "",
            "top_k": top_k,
            # Feature flags
            "enable_reranking": self._enable_reranking,
            "enable_hyde": self._enable_hyde,
            "enable_query_decomposition": self._enable_query_decomposition,
            # Zero-value pipeline state
            "query_type": "hybrid",
            "documents": [],
            "retrieval_attempts": 0,
            "generation": "",
            "documents_relevant": False,
            "answer_grounded": False,
            "rewritten_question": "",
            "sources": [],
            "search_mode_used": "",
            "agent_trace": [],
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "model_used": "",
        }

    async def query(
        self,
        query: str,
        workspace_id: uuid.UUID,
        system_prompt: str | None = None,
        chat_history: list[dict] | None = None,
        top_k: int = 5,
        temperature: float = 0.1,
    ) -> RAGResponse:
        """Full agentic RAG pipeline."""
        initial_state = self._build_initial_state(
            query, workspace_id, system_prompt, chat_history, top_k,
        )

        result = await self._graph.ainvoke(initial_state)

        context = RAGContext(
            chunks=[],
            was_corrective=result.get("retrieval_attempts", 0) > 1,
            original_query=query,
            rewritten_query=result.get("rewritten_question") or None,
            agent_trace=result.get("agent_trace", []),
            search_mode_used=result.get("search_mode_used", ""),
        )

        return RAGResponse(
            content=result.get("generation", ""),
            citations=result.get("sources", []),
            context=context,
            model=result.get("model_used", ""),
            input_tokens=result.get("total_input_tokens", 0),
            output_tokens=result.get("total_output_tokens", 0),
        )

    async def query_stream(
        self,
        query: str,
        workspace_id: uuid.UUID,
        system_prompt: str | None = None,
        chat_history: list[dict] | None = None,
        top_k: int = 5,
        temperature: float = 0.1,
    ) -> AsyncIterator[dict]:
        """Streaming agentic RAG pipeline.

        Runs the full graph first (retrieval + grading), then streams generation.
        """
        initial_state = self._build_initial_state(
            query, workspace_id, system_prompt, chat_history, top_k,
        )

        result = await self._graph.ainvoke(initial_state)

        # Yield context/citations first
        yield {
            "type": "context",
            "citations": result.get("sources", []),
            "was_corrective": result.get("retrieval_attempts", 0) > 1,
            "rewritten_query": result.get("rewritten_question") or None,
            "agent_trace": result.get("agent_trace", []),
            "search_mode_used": result.get("search_mode_used", ""),
        }

        # Stream the generation content in word chunks
        generation = result.get("generation", "")
        chunk_size = 4
        words = generation.split(" ")
        for i in range(0, len(words), chunk_size):
            token = " ".join(words[i:i + chunk_size])
            if i > 0:
                token = " " + token
            yield {"type": "token", "content": token}

        yield {"type": "done"}

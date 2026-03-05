"""LangGraph-based agentic RAG pipeline.

Compiles the state machine that implements:
- Adaptive RAG (query routing)
- Corrective RAG (grading + rewriting loop)
- Self-Reflective RAG (hallucination check + regeneration loop)

Falls back to a simple linear pipeline if langgraph is not installed.
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

import structlog

from app.rag.agent.state import RAGAgentState

logger = structlog.get_logger()

# Sentinel for graph end
_END = "__end__"


def build_rag_graph(
    llm,
    retriever,
    reranker=None,
    embedding_provider=None,
    enable_reranking: bool = False,
    enable_hyde: bool = False,
    enable_decomposition: bool = False,
):
    """Build and compile the agentic RAG graph.

    Returns a compiled graph with an `ainvoke(state)` method,
    or a fallback wrapper if langgraph is unavailable.
    """
    try:
        return _build_langgraph(
            llm, retriever, reranker, embedding_provider,
            enable_reranking, enable_hyde, enable_decomposition,
        )
    except ImportError:
        logger.warning("langgraph not installed, using fallback linear pipeline")
        return _FallbackPipeline(
            llm, retriever, reranker, embedding_provider,
            enable_reranking, enable_hyde, enable_decomposition,
        )


def _build_langgraph(
    llm, retriever, reranker, embedding_provider,
    enable_reranking, enable_hyde, enable_decomposition,
):
    """Build the full LangGraph state machine."""
    from langgraph.graph import StateGraph, END

    from app.rag.agent.edges import (
        route_after_rewrite,
        select_retrieval_strategy,
        should_generate_or_rewrite,
        should_rerank,
        should_return_or_regenerate,
    )
    from app.rag.agent.nodes import (
        check_hallucination,
        decompose_query,
        generate,
        grade_documents,
        hyde_retrieve,
        rerank as rerank_node,
        retrieve,
        rewrite_question,
        route_query,
    )

    graph = StateGraph(RAGAgentState)

    # --- Bind dependencies to nodes ---
    graph.add_node("route_query", partial(route_query, llm=llm))
    graph.add_node("retrieve", partial(retrieve, retriever=retriever))
    graph.add_node("hyde_retrieve", partial(
        hyde_retrieve, llm=llm, retriever=retriever, embedding_provider=embedding_provider,
    ))
    graph.add_node("decompose_query", partial(
        decompose_query, llm=llm, retriever=retriever,
    ))
    graph.add_node("rerank", partial(rerank_node, reranker=reranker))
    graph.add_node("grade_documents", partial(grade_documents, llm=llm))
    graph.add_node("rewrite_question", partial(rewrite_question, llm=llm))
    graph.add_node("generate", partial(generate, llm=llm))
    graph.add_node("check_hallucination", partial(check_hallucination, llm=llm))

    # --- Entry point ---
    graph.set_entry_point("route_query")

    # --- Edges ---

    # After routing, select retrieval strategy
    graph.add_conditional_edges("route_query", select_retrieval_strategy, {
        "retrieve": "retrieve",
        "hyde_retrieve": "hyde_retrieve",
        "decompose_query": "decompose_query",
    })

    # All retrieval paths converge on reranking decision
    graph.add_conditional_edges("retrieve", should_rerank, {
        "rerank": "rerank",
        "grade_documents": "grade_documents",
    })
    graph.add_conditional_edges("hyde_retrieve", should_rerank, {
        "rerank": "rerank",
        "grade_documents": "grade_documents",
    })
    graph.add_conditional_edges("decompose_query", should_rerank, {
        "rerank": "rerank",
        "grade_documents": "grade_documents",
    })

    # After reranking, always grade
    graph.add_edge("rerank", "grade_documents")

    # After grading: generate or rewrite
    graph.add_conditional_edges("grade_documents", should_generate_or_rewrite, {
        "generate": "generate",
        "rewrite_question": "rewrite_question",
    })

    # After rewrite, re-retrieve (always standard retrieve on rewrite)
    graph.add_conditional_edges("rewrite_question", route_after_rewrite, {
        "retrieve": "retrieve",
    })

    # After generation, check hallucination
    graph.add_edge("generate", "check_hallucination")

    # After hallucination check: end or regenerate
    graph.add_conditional_edges("check_hallucination", should_return_or_regenerate, {
        "end": END,
        "regenerate": "generate",
    })

    return graph.compile()


class _FallbackPipeline:
    """Simple linear fallback when langgraph is not installed.

    Executes: retrieve -> grade -> generate (no routing, correction, or reflection).
    """

    def __init__(self, llm, retriever, reranker, embedding_provider,
                 enable_reranking, enable_hyde, enable_decomposition):
        self._llm = llm
        self._retriever = retriever
        self._reranker = reranker
        self._embedding_provider = embedding_provider
        self._enable_reranking = enable_reranking

    async def ainvoke(self, state: dict) -> dict:
        from app.rag.agent.nodes import (
            check_hallucination,
            generate,
            grade_documents,
            rerank as rerank_node,
            retrieve,
        )

        # Retrieve
        update = await retrieve(state, retriever=self._retriever)
        state = {**state, **update}

        # Rerank
        if self._enable_reranking and self._reranker:
            update = await rerank_node(state, reranker=self._reranker)
            state = {**state, **update}

        # Grade
        update = await grade_documents(state, llm=self._llm)
        state = {**state, **update}

        # Generate
        update = await generate(state, llm=self._llm)
        state = {**state, **update}

        # Hallucination check
        update = await check_hallucination(state, llm=self._llm)
        state = {**state, **update}

        return state

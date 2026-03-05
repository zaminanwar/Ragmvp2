"""Core RAG Engine - Orchestrates retrieval, reranking, corrective RAG, and generation.

Combines best patterns from:
- RAGFlow: Hybrid search + fused re-ranking + grounded citations
- awesome-llm-apps: Corrective RAG (CRAG) self-healing retrieval
- Pathway: Adaptive RAG for cost optimization
- AnythingLLM: Provider abstraction and workspace isolation
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator

import structlog

from app.rag.llm.base import BaseLLM, LLMResponse
from app.rag.retrieval.base import RetrievalResult

logger = structlog.get_logger()

# Default system prompts
DEFAULT_RAG_SYSTEM_PROMPT = """You are a helpful AI assistant with access to a knowledge base.
Answer questions based on the provided context. Follow these rules:
1. Base your answers on the provided context chunks
2. If the context doesn't contain enough information, say so clearly
3. Cite your sources by referencing [Source N] where N is the chunk number
4. Be precise and factual - do not hallucinate information
5. If asked about topics not in the context, clarify that you're answering from general knowledge"""

CORRECTIVE_RAG_EVAL_PROMPT = """Evaluate whether the following retrieved passages are relevant to answering the query.
For each passage, respond with "relevant" or "irrelevant".

Query: {query}

{passages}

Respond with a JSON array of objects: [{{"index": 0, "verdict": "relevant"}}, ...]"""

QUERY_REWRITE_PROMPT = """The original query did not retrieve relevant results. Rewrite it to be more specific and likely to find relevant information.

Original query: {query}

Provide a single rewritten query that is more specific and search-friendly. Return ONLY the rewritten query, nothing else."""


@dataclass
class RAGContext:
    """Context assembled for generation."""
    chunks: list[RetrievalResult] = field(default_factory=list)
    was_corrective: bool = False
    original_query: str = ""
    rewritten_query: str | None = None


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
    """Main RAG orchestration engine."""

    def __init__(
        self,
        llm: BaseLLM,
        retriever,
        reranker=None,
        enable_corrective_rag: bool = True,
        relevance_threshold: float = 0.3,
        max_correction_attempts: int = 1,
    ):
        self.llm = llm
        self.retriever = retriever
        self.reranker = reranker
        self.enable_corrective_rag = enable_corrective_rag
        self.relevance_threshold = relevance_threshold
        self.max_correction_attempts = max_correction_attempts

    async def query(
        self,
        query: str,
        workspace_id: uuid.UUID,
        system_prompt: str | None = None,
        chat_history: list[dict] | None = None,
        top_k: int = 5,
        temperature: float = 0.1,
    ) -> RAGResponse:
        """Full RAG pipeline: retrieve -> [correct] -> [rerank] -> generate."""
        context = await self._retrieve_with_correction(query, workspace_id, top_k)

        # Build generation prompt
        prompt = self._build_prompt(query, context.chunks, chat_history)
        system = system_prompt or DEFAULT_RAG_SYSTEM_PROMPT

        response = await self.llm.generate(prompt, system=system, temperature=temperature)

        citations = self._extract_citations(context.chunks)

        return RAGResponse(
            content=response.content,
            citations=citations,
            context=context,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
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
        """Streaming RAG pipeline - yields tokens and metadata."""
        context = await self._retrieve_with_correction(query, workspace_id, top_k)

        # First yield: context/citations metadata
        citations = self._extract_citations(context.chunks)
        yield {
            "type": "context",
            "citations": citations,
            "was_corrective": context.was_corrective,
            "rewritten_query": context.rewritten_query,
        }

        # Stream the generation
        prompt = self._build_prompt(query, context.chunks, chat_history)
        system = system_prompt or DEFAULT_RAG_SYSTEM_PROMPT

        async for token in self.llm.generate_stream(prompt, system=system, temperature=temperature):
            yield {"type": "token", "content": token}

        yield {"type": "done"}

    async def _retrieve_with_correction(
        self,
        query: str,
        workspace_id: uuid.UUID,
        top_k: int,
    ) -> RAGContext:
        """Retrieve and optionally apply Corrective RAG (CRAG) pattern."""
        results = await self.retriever.retrieve(query, workspace_id, top_k=top_k)

        context = RAGContext(chunks=results, original_query=query)

        if not self.enable_corrective_rag or not results:
            if self.reranker and results:
                context.chunks = await self.reranker.rerank(query, results, top_k)
            return context

        # CRAG: Evaluate relevance of retrieved chunks
        relevant_chunks = await self._evaluate_relevance(query, results)

        if len(relevant_chunks) < max(1, top_k // 3):
            # Too few relevant chunks - attempt query rewrite
            for attempt in range(self.max_correction_attempts):
                rewritten = await self._rewrite_query(query)
                context.rewritten_query = rewritten
                context.was_corrective = True

                logger.info(
                    "corrective_rag_rewrite",
                    original=query,
                    rewritten=rewritten,
                    attempt=attempt + 1,
                )

                new_results = await self.retriever.retrieve(rewritten, workspace_id, top_k=top_k)
                new_relevant = await self._evaluate_relevance(rewritten, new_results)

                if len(new_relevant) >= len(relevant_chunks):
                    relevant_chunks = new_relevant
                    break

        # Apply reranking if available
        if self.reranker and relevant_chunks:
            relevant_chunks = await self.reranker.rerank(query, relevant_chunks, top_k)

        context.chunks = relevant_chunks or results[:top_k]
        return context

    async def _evaluate_relevance(
        self,
        query: str,
        results: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        """Use LLM to evaluate chunk relevance (CRAG pattern)."""
        if not results:
            return []

        passages = "\n\n".join(
            f"Passage {i}: {r.content[:600]}" for i, r in enumerate(results)
        )
        prompt = CORRECTIVE_RAG_EVAL_PROMPT.format(query=query, passages=passages)

        try:
            response = await self.llm.generate(prompt, temperature=0.0, max_tokens=500)
            evaluations = json.loads(response.content)

            relevant = []
            for eval_item in evaluations:
                idx = eval_item.get("index", -1)
                verdict = eval_item.get("verdict", "irrelevant")
                if 0 <= idx < len(results) and verdict == "relevant":
                    results[idx].metadata["relevance_verified"] = True
                    relevant.append(results[idx])

            return relevant
        except Exception as e:
            logger.warning("relevance_evaluation_failed", error=str(e))
            # Fallback: use score threshold
            return [r for r in results if r.score >= self.relevance_threshold]

    async def _rewrite_query(self, query: str) -> str:
        """Rewrite a query for better retrieval (CRAG pattern)."""
        prompt = QUERY_REWRITE_PROMPT.format(query=query)
        response = await self.llm.generate(prompt, temperature=0.3, max_tokens=200)
        return response.content.strip()

    def _build_prompt(
        self,
        query: str,
        chunks: list[RetrievalResult],
        chat_history: list[dict] | None = None,
    ) -> str:
        """Build the final prompt with context and chat history."""
        parts = []

        if chunks:
            parts.append("## Retrieved Context\n")
            for i, chunk in enumerate(chunks):
                source_info = chunk.metadata.get("filename", "Unknown source")
                parts.append(f"[Source {i+1}] ({source_info}):\n{chunk.content}\n")

        if chat_history:
            parts.append("\n## Conversation History\n")
            for msg in chat_history[-10:]:  # Last 10 messages
                role = msg.get("role", "user")
                content = msg.get("content", "")
                parts.append(f"{role.capitalize()}: {content}")

        parts.append(f"\n## Question\n{query}")

        return "\n".join(parts)

    def _extract_citations(self, chunks: list[RetrievalResult]) -> list[dict]:
        """Build citation objects for the response."""
        return [
            {
                "index": i + 1,
                "chunk_id": str(chunk.chunk_id),
                "document_id": str(chunk.document_id),
                "content": chunk.content[:300],
                "score": chunk.score,
                "source": chunk.metadata.get("filename", "Unknown"),
                "metadata": {
                    k: v for k, v in chunk.metadata.items()
                    if k in ("page_number", "chunk_strategy", "reranked", "relevance_verified")
                },
            }
            for i, chunk in enumerate(chunks)
        ]

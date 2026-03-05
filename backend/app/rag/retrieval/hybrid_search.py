"""Hybrid search with Reciprocal Rank Fusion and source diversity.

Combines vector similarity + BM25 full-text search + optional knowledge graph
retrieval with RRF fusion.
Includes source diversity logic to ensure results span multiple documents.
"""

import asyncio
from uuid import UUID

import structlog

from app.rag.embeddings.base import BaseEmbedding
from app.rag.retrieval.base import BaseRetriever, RetrievalResult
from app.rag.retrieval.fulltext_search import FullTextRetriever
from app.rag.retrieval.vector_search import VectorRetriever

logger = structlog.get_logger()


class HybridRetriever(BaseRetriever):
    """Combines vector, full-text, and optionally graph search using RRF with source diversity.

    Two-pass fusion algorithm:
    1. Best result per source document (ensures diversity)
    2. Fill remaining slots by RRF score
    """

    def __init__(
        self,
        db,
        embedding_provider: BaseEmbedding,
        vector_weight: float = 0.6,
        fulltext_weight: float = 0.4,
        graph_weight: float = 0.3,
        rrf_k: int = 60,
        enable_graph: bool = False,
    ):
        self.db = db
        self.embedding_provider = embedding_provider
        self.vector_retriever = VectorRetriever(db, embedding_provider)
        self.fulltext_retriever = FullTextRetriever()
        self.graph_retriever = None
        self.vector_weight = vector_weight
        self.fulltext_weight = fulltext_weight
        self.graph_weight = graph_weight
        self.rrf_k = rrf_k

        if enable_graph:
            from app.rag.knowledge_graph.retriever import GraphRetriever
            self.graph_retriever = GraphRetriever(db, embedding_provider)

    async def retrieve(
        self,
        query: str,
        workspace_id: UUID,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        # Run all searches in parallel
        tasks = [
            self.vector_retriever.retrieve(query, workspace_id, top_k=top_k * 2),
            self.fulltext_retriever.retrieve(query, workspace_id, top_k=top_k * 2),
        ]
        if self.graph_retriever:
            tasks.append(self.graph_retriever.retrieve(query, workspace_id, top_k=top_k * 2))

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        vector_results = raw_results[0] if not isinstance(raw_results[0], Exception) else []
        fulltext_results = raw_results[1] if not isinstance(raw_results[1], Exception) else []
        graph_results = []

        if isinstance(vector_results, Exception):
            logger.warning("vector_search_failed", error=str(raw_results[0]))
            vector_results = []
        if isinstance(fulltext_results, Exception):
            logger.warning("fulltext_search_failed", error=str(raw_results[1]))
            fulltext_results = []
        if len(raw_results) > 2:
            if isinstance(raw_results[2], Exception):
                logger.warning("graph_search_failed", error=str(raw_results[2]))
            else:
                graph_results = raw_results[2]

        if not vector_results and not fulltext_results and not graph_results:
            return []

        # Compute RRF scores
        rrf_scores: dict[UUID, float] = {}
        chunk_map: dict[UUID, RetrievalResult] = {}

        for rank, result in enumerate(vector_results):
            rrf_score = self.vector_weight / (self.rrf_k + rank + 1)
            rrf_scores[result.chunk_id] = rrf_scores.get(result.chunk_id, 0) + rrf_score
            chunk_map[result.chunk_id] = result

        for rank, result in enumerate(fulltext_results):
            rrf_score = self.fulltext_weight / (self.rrf_k + rank + 1)
            rrf_scores[result.chunk_id] = rrf_scores.get(result.chunk_id, 0) + rrf_score
            if result.chunk_id not in chunk_map:
                chunk_map[result.chunk_id] = result

        for rank, result in enumerate(graph_results):
            rrf_score = self.graph_weight / (self.rrf_k + rank + 1)
            rrf_scores[result.chunk_id] = rrf_scores.get(result.chunk_id, 0) + rrf_score
            if result.chunk_id not in chunk_map:
                chunk_map[result.chunk_id] = result

        # Sort all chunks by fused score
        sorted_chunks = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        # Two-pass source diversity algorithm
        results: list[RetrievalResult] = []
        used_ids: set[UUID] = set()

        # Pass 1: Best result per source document
        seen_sources: set[str] = set()
        for chunk_id, score in sorted_chunks:
            result = chunk_map[chunk_id]
            source_file = result.metadata.get("filename", result.metadata.get("original_filename", "unknown"))
            if source_file not in seen_sources:
                seen_sources.add(source_file)
                result.score = score
                result.source = "hybrid"
                results.append(result)
                used_ids.add(chunk_id)
                if len(results) >= top_k:
                    break

        # Pass 2: Fill remaining slots by score
        if len(results) < top_k:
            for chunk_id, score in sorted_chunks:
                if chunk_id not in used_ids:
                    result = chunk_map[chunk_id]
                    result.score = score
                    result.source = "hybrid"
                    results.append(result)
                    used_ids.add(chunk_id)
                    if len(results) >= top_k:
                        break

        logger.info(
            "hybrid_retrieval",
            vector_count=len(vector_results),
            fulltext_count=len(fulltext_results),
            graph_count=len(graph_results),
            fused_count=len(results),
            unique_sources=len(seen_sources),
        )

        return results

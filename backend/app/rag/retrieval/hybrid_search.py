"""Hybrid search with Reciprocal Rank Fusion (inspired by RAGFlow's fused re-ranking)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.embeddings.base import BaseEmbedding
from app.rag.retrieval.base import BaseRetriever, RetrievalResult
from app.rag.retrieval.fulltext_search import FullTextRetriever
from app.rag.retrieval.vector_search import VectorRetriever


class HybridRetriever(BaseRetriever):
    """Combines vector and full-text search using Reciprocal Rank Fusion (RRF).

    This implements the hybrid search pattern used by RAGFlow and recommended
    across all surveyed enterprise RAG systems.
    """

    def __init__(
        self,
        db: AsyncSession,
        embedding_provider: BaseEmbedding,
        vector_weight: float = 0.6,
        fulltext_weight: float = 0.4,
        rrf_k: int = 60,
    ):
        self.vector_retriever = VectorRetriever(db, embedding_provider)
        self.fulltext_retriever = FullTextRetriever()
        self.vector_weight = vector_weight
        self.fulltext_weight = fulltext_weight
        self.rrf_k = rrf_k

    async def retrieve(
        self,
        query: str,
        workspace_id: UUID,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        # Run both searches in parallel-style
        vector_results = await self.vector_retriever.retrieve(query, workspace_id, top_k=top_k * 2)
        fulltext_results = await self.fulltext_retriever.retrieve(query, workspace_id, top_k=top_k * 2)

        # Reciprocal Rank Fusion
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

        # Sort by fused score
        sorted_chunks = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        results = []
        for chunk_id, score in sorted_chunks[:top_k]:
            result = chunk_map[chunk_id]
            result.score = score
            result.source = "hybrid"
            results.append(result)

        return results

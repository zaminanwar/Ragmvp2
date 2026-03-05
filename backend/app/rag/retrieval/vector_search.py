"""Vector similarity search using pgvector."""

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentChunk
from app.rag.embeddings.base import BaseEmbedding
from app.rag.retrieval.base import BaseRetriever, RetrievalResult


class VectorRetriever(BaseRetriever):
    """Semantic vector search using pgvector cosine similarity."""

    def __init__(self, db: AsyncSession, embedding_provider: BaseEmbedding):
        self.db = db
        self.embedding = embedding_provider

    async def retrieve(
        self,
        query: str,
        workspace_id: UUID,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        query_embedding = await self.embedding.embed_text(query)

        # pgvector cosine distance: <=> operator
        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                DocumentChunk.content,
                DocumentChunk.metadata_json,
                DocumentChunk.embedding.cosine_distance(query_embedding).label("distance"),
            )
            .where(
                DocumentChunk.workspace_id == workspace_id,
                DocumentChunk.embedding.isnot(None),
            )
            .order_by(text("distance"))
            .limit(top_k)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            RetrievalResult(
                chunk_id=row.id,
                document_id=row.document_id,
                content=row.content,
                score=1.0 - row.distance,  # Convert distance to similarity
                metadata=row.metadata_json or {},
                source="vector",
            )
            for row in rows
        ]

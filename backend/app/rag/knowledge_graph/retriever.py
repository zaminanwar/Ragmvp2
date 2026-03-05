"""Graph-enhanced retrieval using the knowledge graph.

Finds relevant entities via embedding similarity, expands to
neighbors, then retrieves the source chunks for those entities.
Acts as a third retrieval signal alongside vector and BM25.
"""

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentChunk
from app.rag.embeddings.base import BaseEmbedding
from app.rag.knowledge_graph.store import KnowledgeGraphStore
from app.rag.retrieval.base import BaseRetriever, RetrievalResult

logger = structlog.get_logger()


class GraphRetriever(BaseRetriever):
    """Retrieve documents via knowledge graph entity similarity + neighbor expansion."""

    def __init__(self, db: AsyncSession, embedding: BaseEmbedding):
        self.db = db
        self.embedding = embedding
        self.store = KnowledgeGraphStore(db, embedding)

    async def retrieve(
        self,
        query: str,
        workspace_id: UUID,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Graph-enhanced retrieval pipeline:
        1. Embed query
        2. Find similar entities
        3. Expand to 1-hop neighbors
        4. Collect source chunk IDs from all entities
        5. Fetch and return those chunks
        """
        try:
            # 1. Embed query
            query_embedding = await self.embedding.embed_text(query)

            # 2. Find similar entities
            similar_entities = await self.store.find_similar_entities(
                query_embedding, workspace_id, top_k=10,
            )

            if not similar_entities:
                return []

            # 3. Expand to neighbors
            entity_ids = [UUID(e["id"]) for e in similar_entities]
            neighbors = await self.store.get_entity_neighbors(entity_ids, workspace_id)

            # 4. Collect all source chunk IDs
            all_chunk_ids: set[str] = set()
            for entity in similar_entities + neighbors:
                for chunk_id in entity.get("source_chunks", []):
                    all_chunk_ids.add(chunk_id)

            if not all_chunk_ids:
                return []

            # 5. Fetch chunks from DB
            chunk_uuids = []
            for cid in all_chunk_ids:
                try:
                    chunk_uuids.append(UUID(cid))
                except ValueError:
                    continue

            stmt = (
                select(DocumentChunk)
                .where(
                    DocumentChunk.id.in_(chunk_uuids),
                    DocumentChunk.workspace_id == workspace_id,
                )
            )
            result = await self.db.execute(stmt)
            chunks = result.scalars().all()

            # Score by how many entities reference each chunk
            chunk_scores: dict[UUID, int] = {}
            for entity in similar_entities + neighbors:
                for cid_str in entity.get("source_chunks", []):
                    try:
                        cid = UUID(cid_str)
                        chunk_scores[cid] = chunk_scores.get(cid, 0) + 1
                    except ValueError:
                        continue

            results = []
            for chunk in chunks:
                results.append(RetrievalResult(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    content=chunk.content,
                    score=chunk_scores.get(chunk.id, 1) / max(len(similar_entities), 1),
                    metadata={**(chunk.metadata_json or {}), "graph_retrieved": True},
                    source="graph",
                ))

            # Sort by score descending
            results.sort(key=lambda r: r.score, reverse=True)

            logger.info(
                "graph_retrieval",
                entities_found=len(similar_entities),
                neighbors=len(neighbors),
                chunks_returned=len(results[:top_k]),
            )

            return results[:top_k]

        except Exception as e:
            logger.warning("graph_retrieval_failed", error=str(e))
            return []

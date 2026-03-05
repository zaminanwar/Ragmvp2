"""Knowledge graph persistence in PostgreSQL.

Stores entities, relationships, and community summaries
alongside the existing document/chunk tables.
"""

from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.embeddings.base import BaseEmbedding
from app.rag.knowledge_graph.extractor import EntityData, RelationshipData

logger = structlog.get_logger()


class KnowledgeGraphStore:
    """Store and query knowledge graph data in PostgreSQL."""

    def __init__(self, db: AsyncSession, embedding: BaseEmbedding):
        self.db = db
        self.embedding = embedding

    async def store_entities(
        self,
        entities: list[EntityData],
        workspace_id: UUID,
    ) -> dict[str, UUID]:
        """Store extracted entities with embeddings. Returns name -> entity_id mapping."""
        from app.models.knowledge_graph import Entity

        name_to_id: dict[str, UUID] = {}

        for entity in entities:
            # Check if entity already exists in workspace
            result = await self.db.execute(
                select(Entity).where(
                    Entity.workspace_id == workspace_id,
                    Entity.name == entity.name,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Merge source chunks
                current_chunks = existing.source_chunks or []
                new_chunks = list(set(current_chunks + entity.source_chunk_ids))
                existing.source_chunks = new_chunks
                if len(entity.description) > len(existing.description or ""):
                    existing.description = entity.description
                name_to_id[entity.name] = existing.id
                await self.db.flush()
            else:
                # Create new entity with embedding
                try:
                    embedding_text = f"{entity.display_name}: {entity.description}"
                    embedding_vec = await self.embedding.embed_text(embedding_text)
                except Exception:
                    embedding_vec = None

                db_entity = Entity(
                    workspace_id=workspace_id,
                    name=entity.name,
                    display_name=entity.display_name,
                    entity_type=entity.entity_type,
                    description=entity.description,
                    embedding=embedding_vec,
                    source_chunks=entity.source_chunk_ids,
                    metadata_json={},
                )
                self.db.add(db_entity)
                await self.db.flush()
                name_to_id[entity.name] = db_entity.id

        logger.info("kg_entities_stored", count=len(entities), workspace_id=str(workspace_id))
        return name_to_id

    async def store_relationships(
        self,
        relationships: list[RelationshipData],
        name_to_id: dict[str, UUID],
        workspace_id: UUID,
    ):
        """Store extracted relationships between entities."""
        from app.models.knowledge_graph import Relationship

        stored = 0
        for rel in relationships:
            source_id = name_to_id.get(rel.source_name)
            target_id = name_to_id.get(rel.target_name)
            if not source_id or not target_id:
                continue

            db_rel = Relationship(
                workspace_id=workspace_id,
                source_entity_id=source_id,
                target_entity_id=target_id,
                relationship_type=rel.relationship_type,
                description=rel.description,
                weight=1.0,
                source_chunks=rel.source_chunk_ids,
            )
            self.db.add(db_rel)
            stored += 1

        await self.db.flush()
        logger.info("kg_relationships_stored", count=stored, workspace_id=str(workspace_id))

    async def find_similar_entities(
        self,
        query_embedding: list[float],
        workspace_id: UUID,
        top_k: int = 10,
    ) -> list[dict]:
        """Find entities most similar to query via embedding similarity."""
        from app.models.knowledge_graph import Entity

        stmt = (
            select(
                Entity.id,
                Entity.name,
                Entity.display_name,
                Entity.entity_type,
                Entity.description,
                Entity.source_chunks,
                Entity.embedding.cosine_distance(query_embedding).label("distance"),
            )
            .where(
                Entity.workspace_id == workspace_id,
                Entity.embedding.isnot(None),
            )
            .order_by(text("distance"))
            .limit(top_k)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "id": str(row.id),
                "name": row.display_name,
                "type": row.entity_type,
                "description": row.description,
                "source_chunks": row.source_chunks or [],
                "score": 1.0 - row.distance,
            }
            for row in rows
        ]

    async def get_entity_neighbors(
        self,
        entity_ids: list[UUID],
        workspace_id: UUID,
    ) -> list[dict]:
        """Get 1-hop neighbors of given entities via relationships."""
        from app.models.knowledge_graph import Entity, Relationship

        if not entity_ids:
            return []

        # Find relationships where source or target is in our entity set
        stmt = (
            select(Relationship)
            .where(
                Relationship.workspace_id == workspace_id,
                (Relationship.source_entity_id.in_(entity_ids)) |
                (Relationship.target_entity_id.in_(entity_ids)),
            )
        )
        result = await self.db.execute(stmt)
        relationships = result.scalars().all()

        # Collect neighbor entity IDs
        neighbor_ids = set()
        for rel in relationships:
            neighbor_ids.add(rel.source_entity_id)
            neighbor_ids.add(rel.target_entity_id)
        neighbor_ids -= set(entity_ids)

        # Fetch neighbor entities
        if not neighbor_ids:
            return []

        stmt = select(Entity).where(Entity.id.in_(neighbor_ids))
        result = await self.db.execute(stmt)
        neighbors = result.scalars().all()

        return [
            {
                "id": str(n.id),
                "name": n.display_name,
                "type": n.entity_type,
                "description": n.description,
                "source_chunks": n.source_chunks or [],
            }
            for n in neighbors
        ]

"""Entity and relationship extraction from document chunks.

Uses LLM-as-extractor to build a lightweight knowledge graph
stored in PostgreSQL (no external graph DB dependency).
"""

import asyncio
from uuid import UUID

import structlog

from app.rag.agent.output_parser import parse_json_response
from app.rag.agent.prompts import ENTITY_EXTRACTION_PROMPT
from app.rag.llm.base import BaseLLM

logger = structlog.get_logger()


class EntityData:
    """Extracted entity before DB persistence."""
    def __init__(self, name: str, entity_type: str, description: str = "",
                 source_chunk_ids: list[str] | None = None):
        self.name = name.strip().lower()
        self.display_name = name.strip()
        self.entity_type = entity_type.upper()
        self.description = description
        self.source_chunk_ids = source_chunk_ids or []


class RelationshipData:
    """Extracted relationship before DB persistence."""
    def __init__(self, source_name: str, target_name: str,
                 relationship_type: str, description: str = "",
                 source_chunk_ids: list[str] | None = None):
        self.source_name = source_name.strip().lower()
        self.target_name = target_name.strip().lower()
        self.relationship_type = relationship_type.upper()
        self.description = description
        self.source_chunk_ids = source_chunk_ids or []


class KnowledgeGraphExtractor:
    """Extract entities and relationships from document chunks using LLM."""

    def __init__(self, llm: BaseLLM):
        self.llm = llm

    async def extract_from_chunk(
        self, chunk_content: str, chunk_id: str,
    ) -> tuple[list[EntityData], list[RelationshipData]]:
        """Extract entities and relationships from a single chunk."""
        try:
            response = await self.llm.generate(
                prompt=ENTITY_EXTRACTION_PROMPT.format(text=chunk_content[:2000]),
                temperature=0.0,
                max_tokens=1000,
            )
            parsed = parse_json_response(
                response.content,
                default={"entities": [], "relationships": []},
            )

            entities = []
            for e in parsed.get("entities", []):
                if isinstance(e, dict) and e.get("name"):
                    entities.append(EntityData(
                        name=e["name"],
                        entity_type=e.get("type", "CONCEPT"),
                        description=e.get("description", ""),
                        source_chunk_ids=[chunk_id],
                    ))

            relationships = []
            for r in parsed.get("relationships", []):
                if isinstance(r, dict) and r.get("source") and r.get("target"):
                    relationships.append(RelationshipData(
                        source_name=r["source"],
                        target_name=r["target"],
                        relationship_type=r.get("type", "RELATES_TO"),
                        description=r.get("description", ""),
                        source_chunk_ids=[chunk_id],
                    ))

            return entities, relationships

        except Exception as e:
            logger.warning("kg_extraction_failed", chunk_id=chunk_id, error=str(e))
            return [], []

    async def extract_from_document(
        self,
        chunks: list[dict],
        batch_size: int = 5,
    ) -> tuple[list[EntityData], list[RelationshipData]]:
        """Extract and deduplicate entities/relationships across all chunks.

        Args:
            chunks: List of dicts with 'content' and 'chunk_id' keys
            batch_size: Parallel extraction batch size
        """
        all_entities: list[EntityData] = []
        all_relationships: list[RelationshipData] = []

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            results = await asyncio.gather(*[
                self.extract_from_chunk(c["content"], c["chunk_id"])
                for c in batch
            ])
            for entities, rels in results:
                all_entities.extend(entities)
                all_relationships.extend(rels)

        # Deduplicate entities by normalized name
        entity_map: dict[str, EntityData] = {}
        for entity in all_entities:
            key = entity.name
            if key in entity_map:
                # Merge: combine source chunks, keep longer description
                existing = entity_map[key]
                existing.source_chunk_ids.extend(entity.source_chunk_ids)
                if len(entity.description) > len(existing.description):
                    existing.description = entity.description
            else:
                entity_map[key] = entity

        # Deduplicate relationships
        rel_map: dict[str, RelationshipData] = {}
        for rel in all_relationships:
            key = f"{rel.source_name}:{rel.relationship_type}:{rel.target_name}"
            if key in rel_map:
                rel_map[key].source_chunk_ids.extend(rel.source_chunk_ids)
            else:
                rel_map[key] = rel

        deduped_entities = list(entity_map.values())
        deduped_rels = list(rel_map.values())

        logger.info(
            "kg_extraction_complete",
            raw_entities=len(all_entities),
            deduped_entities=len(deduped_entities),
            raw_relationships=len(all_relationships),
            deduped_relationships=len(deduped_rels),
        )

        return deduped_entities, deduped_rels

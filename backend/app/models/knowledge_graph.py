"""Knowledge graph models - entities, relationships, and communities."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Entity(UUIDMixin, TimestampMixin, Base):
    """A named entity extracted from document chunks."""
    __tablename__ = "kg_entities"
    __table_args__ = (
        Index("ix_kg_entities_workspace", "workspace_id"),
        Index("ix_kg_entities_name", "workspace_id", "name"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)  # Normalized (lowercase)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)  # Original case
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # PERSON, ORG, CONCEPT, etc.
    description: Mapped[str] = mapped_column(Text, nullable=True)
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=True)
    source_chunks: Mapped[list] = mapped_column(JSONB, default=list)  # List of chunk_id strings
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Relationships
    outgoing_relationships = relationship(
        "Relationship", foreign_keys="Relationship.source_entity_id",
        back_populates="source_entity", cascade="all, delete-orphan",
    )
    incoming_relationships = relationship(
        "Relationship", foreign_keys="Relationship.target_entity_id",
        back_populates="target_entity", cascade="all, delete-orphan",
    )


class Relationship(UUIDMixin, TimestampMixin, Base):
    """A directed relationship between two entities."""
    __tablename__ = "kg_relationships"
    __table_args__ = (
        Index("ix_kg_rels_workspace", "workspace_id"),
        Index("ix_kg_rels_source", "source_entity_id"),
        Index("ix_kg_rels_target", "target_entity_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    source_chunks: Mapped[list] = mapped_column(JSONB, default=list)

    # Relationships
    source_entity = relationship("Entity", foreign_keys=[source_entity_id], back_populates="outgoing_relationships")
    target_entity = relationship("Entity", foreign_keys=[target_entity_id], back_populates="incoming_relationships")


class Community(UUIDMixin, TimestampMixin, Base):
    """A community of related entities with an LLM-generated summary."""
    __tablename__ = "kg_communities"
    __table_args__ = (
        Index("ix_kg_communities_workspace", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    entity_ids: Mapped[list] = mapped_column(JSONB, default=list)  # List of entity_id strings
    level: Mapped[int] = mapped_column(Integer, default=0)  # Hierarchy level
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)

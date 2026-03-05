"""Workspace model for multi-tenant document isolation (inspired by AnythingLLM)."""

import enum
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class WorkspaceRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class Workspace(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # RAG Configuration per workspace
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=True)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=True)
    embedding_provider: Mapped[str] = mapped_column(String(50), nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=True)
    temperature: Mapped[float] = mapped_column(default=0.1)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=True)
    chunk_size: Mapped[int] = mapped_column(default=512)
    chunk_overlap: Mapped[int] = mapped_column(default=50)
    similarity_top_k: Mapped[int] = mapped_column(default=5)
    enable_hybrid_search: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_reranking: Mapped[bool] = mapped_column(Boolean, default=True)

    # Agentic RAG features
    enable_adaptive_routing: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_self_reflection: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_hyde: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_query_decomposition: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_contextual_embeddings: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_knowledge_graph: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_semantic_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    chunk_strategy: Mapped[str] = mapped_column(String(50), default="recursive")
    max_retrieval_attempts: Mapped[int] = mapped_column(Integer, default=3)
    max_generation_attempts: Mapped[int] = mapped_column(Integer, default=2)
    cache_ttl_seconds: Mapped[int] = mapped_column(Integer, default=3600)

    # Relationships
    members = relationship("WorkspaceMember", back_populates="workspace")
    documents = relationship("Document", back_populates="workspace")
    conversations = relationship("Conversation", back_populates="workspace")


class WorkspaceMember(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(20),
        default=WorkspaceRole.VIEWER.value,
    )

    # Relationships
    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="workspace_memberships")

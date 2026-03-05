"""Workspace model for multi-tenant document isolation (inspired by AnythingLLM)."""

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text, UniqueConstraint
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
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole, name="workspace_role_enum", create_constraint=True),
        default=WorkspaceRole.VIEWER,
    )

    # Relationships
    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="workspace_memberships")

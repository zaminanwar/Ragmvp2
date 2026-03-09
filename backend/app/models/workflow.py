"""Workflow orchestration models — definitions, runs, steps, approvals, audit."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


# ── Enums ────────────────────────────────────────────────────────────────────


class DefinitionStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ── Models ───────────────────────────────────────────────────────────────────


class WorkflowDefinition(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workflow_definitions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(
        String(20), default=DefinitionStatus.DRAFT.value
    )
    definition_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    required_role: Mapped[str] = mapped_column(String(20), default="member")

    # Relationships
    workspace = relationship("Workspace")
    created_by_user = relationship("User", foreign_keys=[created_by])
    runs = relationship(
        "WorkflowRun", back_populates="workflow_definition", cascade="all, delete-orphan"
    )


class WorkflowRun(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_workspace_status", "workspace_id", "status"),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    triggered_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=RunStatus.PENDING.value
    )
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    state_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    input_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    definition_snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Re-run support: link to original run + per-step overrides
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    overrides_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    workflow_definition = relationship("WorkflowDefinition", back_populates="runs")
    triggered_by_user = relationship("User", foreign_keys=[triggered_by])
    parent_run = relationship("WorkflowRun", remote_side="WorkflowRun.id")
    step_results = relationship(
        "WorkflowStepResult", back_populates="run", cascade="all, delete-orphan"
    )
    approvals = relationship(
        "WorkflowApproval", back_populates="run", cascade="all, delete-orphan"
    )
    audit_entries = relationship(
        "WorkflowAuditEntry", back_populates="run", cascade="all, delete-orphan"
    )


class WorkflowStepResult(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workflow_step_results"
    __table_args__ = (
        Index("ix_step_results_run_index", "run_id", "step_index"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str] = mapped_column(String(100), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=StepStatus.PENDING.value
    )
    input_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    run = relationship("WorkflowRun", back_populates="step_results")


class WorkflowApproval(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workflow_approvals"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=ApprovalStatus.PENDING.value
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_json: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Relationships
    run = relationship("WorkflowRun", back_populates="approvals")
    decided_by_user = relationship("User", foreign_keys=[decided_by])


class WorkflowAuditEntry(UUIDMixin, Base):
    __tablename__ = "workflow_audit_entries"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    step_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    details_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    run = relationship("WorkflowRun", back_populates="audit_entries")
    user = relationship("User", foreign_keys=[user_id])

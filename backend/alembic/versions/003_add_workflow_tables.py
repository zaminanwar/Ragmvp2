"""Add workflow orchestration tables: definitions, runs, steps, approvals, audit.

Revision ID: 003
Revises: 002
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── WorkflowDefinition ───────────────────────────────────────────────
    op.create_table(
        'workflow_definitions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('workspace_id', UUID(as_uuid=True),
                  sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('status', sa.String(20), server_default='draft'),
        sa.Column('definition_json', JSONB(), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('is_template', sa.Boolean(), server_default='false'),
        sa.Column('required_role', sa.String(20), server_default='member'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_workflow_definitions_slug', 'workflow_definitions', ['slug'])
    op.create_index('ix_workflow_definitions_workspace', 'workflow_definitions', ['workspace_id'])

    # ── WorkflowRun ──────────────────────────────────────────────────────
    op.create_table(
        'workflow_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('workflow_id', UUID(as_uuid=True),
                  sa.ForeignKey('workflow_definitions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workspace_id', UUID(as_uuid=True),
                  sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('triggered_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('current_step_index', sa.Integer(), server_default='0'),
        sa.Column('state_json', JSONB(), server_default='{}'),
        sa.Column('input_json', JSONB(), nullable=False),
        sa.Column('output_json', JSONB(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('progress_pct', sa.Integer(), server_default='0'),
        sa.Column('definition_snapshot_json', JSONB(), nullable=False),
        # Re-run support
        sa.Column('parent_run_id', UUID(as_uuid=True),
                  sa.ForeignKey('workflow_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('overrides_json', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_workflow_runs_workspace_status', 'workflow_runs', ['workspace_id', 'status'])

    # ── WorkflowStepResult ───────────────────────────────────────────────
    op.create_table(
        'workflow_step_results',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True),
                  sa.ForeignKey('workflow_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('step_id', sa.String(100), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=False),
        sa.Column('tool_name', sa.String(100), nullable=False),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('input_json', JSONB(), nullable=False),
        sa.Column('output_json', JSONB(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_step_results_run_index', 'workflow_step_results', ['run_id', 'step_index'])

    # ── WorkflowApproval ─────────────────────────────────────────────────
    op.create_table(
        'workflow_approvals',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True),
                  sa.ForeignKey('workflow_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('step_id', sa.String(100), nullable=False),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('decided_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('context_json', JSONB(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── WorkflowAuditEntry ───────────────────────────────────────────────
    op.create_table(
        'workflow_audit_entries',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True),
                  sa.ForeignKey('workflow_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('step_id', sa.String(100), nullable=True),
        sa.Column('user_id', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('details_json', JSONB(), server_default='{}'),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_audit_entries_run', 'workflow_audit_entries', ['run_id'])


def downgrade() -> None:
    op.drop_table('workflow_audit_entries')
    op.drop_table('workflow_approvals')
    op.drop_table('workflow_step_results')
    op.drop_table('workflow_runs')
    op.drop_table('workflow_definitions')

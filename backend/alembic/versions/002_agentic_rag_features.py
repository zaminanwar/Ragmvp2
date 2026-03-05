"""Add agentic RAG features: workspace config, message trace, knowledge graph tables.

Revision ID: 002
Revises: 001
Create Date: 2026-03-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Workspace: Agentic RAG feature flags ──────────────────────────────
    op.add_column('workspaces', sa.Column('enable_adaptive_routing', sa.Boolean(), server_default='true'))
    op.add_column('workspaces', sa.Column('enable_self_reflection', sa.Boolean(), server_default='true'))
    op.add_column('workspaces', sa.Column('enable_hyde', sa.Boolean(), server_default='false'))
    op.add_column('workspaces', sa.Column('enable_query_decomposition', sa.Boolean(), server_default='false'))
    op.add_column('workspaces', sa.Column('enable_contextual_embeddings', sa.Boolean(), server_default='false'))
    op.add_column('workspaces', sa.Column('enable_knowledge_graph', sa.Boolean(), server_default='false'))
    op.add_column('workspaces', sa.Column('enable_semantic_cache', sa.Boolean(), server_default='false'))
    op.add_column('workspaces', sa.Column('chunk_strategy', sa.String(50), server_default='recursive'))
    op.add_column('workspaces', sa.Column('max_retrieval_attempts', sa.Integer(), server_default='3'))
    op.add_column('workspaces', sa.Column('max_generation_attempts', sa.Integer(), server_default='2'))
    op.add_column('workspaces', sa.Column('cache_ttl_seconds', sa.Integer(), server_default='3600'))

    # ── Messages: Agent trace fields ──────────────────────────────────────
    op.add_column('messages', sa.Column('agent_trace', JSONB(), nullable=True))
    op.add_column('messages', sa.Column('search_mode_used', sa.String(50), nullable=True))
    op.add_column('messages', sa.Column('input_tokens', sa.Integer(), server_default='0'))
    op.add_column('messages', sa.Column('output_tokens', sa.Integer(), server_default='0'))

    # ── Knowledge Graph: Entities ─────────────────────────────────────────
    op.create_table(
        'kg_entities',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(512), nullable=False),
        sa.Column('display_name', sa.String(512), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('embedding', Vector(1536), nullable=True),
        sa.Column('source_chunks', JSONB(), server_default='[]'),
        sa.Column('metadata_json', JSONB(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_kg_entities_workspace', 'kg_entities', ['workspace_id'])
    op.create_index('ix_kg_entities_name', 'kg_entities', ['workspace_id', 'name'])

    # ── Knowledge Graph: Relationships ────────────────────────────────────
    op.create_table(
        'kg_relationships',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_entity_id', UUID(as_uuid=True), sa.ForeignKey('kg_entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_entity_id', UUID(as_uuid=True), sa.ForeignKey('kg_entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('relationship_type', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('weight', sa.Float(), server_default='1.0'),
        sa.Column('source_chunks', JSONB(), server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_kg_rels_workspace', 'kg_relationships', ['workspace_id'])
    op.create_index('ix_kg_rels_source', 'kg_relationships', ['source_entity_id'])
    op.create_index('ix_kg_rels_target', 'kg_relationships', ['target_entity_id'])

    # ── Knowledge Graph: Communities ──────────────────────────────────────
    op.create_table(
        'kg_communities',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(512), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('entity_ids', JSONB(), server_default='[]'),
        sa.Column('level', sa.Integer(), server_default='0'),
        sa.Column('metadata_json', JSONB(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_kg_communities_workspace', 'kg_communities', ['workspace_id'])


def downgrade() -> None:
    # Drop KG tables
    op.drop_table('kg_communities')
    op.drop_table('kg_relationships')
    op.drop_table('kg_entities')

    # Drop message columns
    op.drop_column('messages', 'output_tokens')
    op.drop_column('messages', 'input_tokens')
    op.drop_column('messages', 'search_mode_used')
    op.drop_column('messages', 'agent_trace')

    # Drop workspace columns
    op.drop_column('workspaces', 'cache_ttl_seconds')
    op.drop_column('workspaces', 'max_generation_attempts')
    op.drop_column('workspaces', 'max_retrieval_attempts')
    op.drop_column('workspaces', 'chunk_strategy')
    op.drop_column('workspaces', 'enable_semantic_cache')
    op.drop_column('workspaces', 'enable_knowledge_graph')
    op.drop_column('workspaces', 'enable_contextual_embeddings')
    op.drop_column('workspaces', 'enable_query_decomposition')
    op.drop_column('workspaces', 'enable_hyde')
    op.drop_column('workspaces', 'enable_self_reflection')
    op.drop_column('workspaces', 'enable_adaptive_routing')

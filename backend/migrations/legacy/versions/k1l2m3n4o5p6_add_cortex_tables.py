"""Add CORTEX memory architecture tables

Revision ID: k1l2m3n4o5p6
Revises: j1k2l3m4n5o6
Create Date: 2026-03-08

Creates cortex_trees and cortex_nodes tables for the CORTEX
(Cognitive Orchestrated Recursive Tree EXecution) memory system.
Also adds tree_id foreign key to episodic_memories.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'k1l2m3n4o5p6'
down_revision = 'j1k2l3m4n5o6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Create enum types ---
    cortex_tree_status = postgresql.ENUM(
        'active', 'suspended', 'complete', 'archived',
        name='cortex_tree_status', create_type=False,
    )
    cortex_node_type = postgresql.ENUM(
        'root', 'knowledge', 'finding', 'task', 'output', 'checkpoint',
        name='cortex_node_type', create_type=False,
    )
    cortex_node_status = postgresql.ENUM(
        'pending', 'active', 'complete', 'summarised',
        name='cortex_node_status', create_type=False,
    )

    cortex_tree_status.create(op.get_bind(), checkfirst=True)
    cortex_node_type.create(op.get_bind(), checkfirst=True)
    cortex_node_status.create(op.get_bind(), checkfirst=True)

    # --- cortex_trees ---
    op.create_table(
        'cortex_trees',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('hierarchical_entities.id'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('companies.id'), nullable=False),

        sa.Column('task_description', sa.Text(), nullable=True),
        sa.Column('status', cortex_tree_status, nullable=False, server_default='active'),

        sa.Column('total_nodes', sa.Integer(), server_default='0'),
        sa.Column('root_node_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('output_root_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('resume_cursor_id', postgresql.UUID(as_uuid=True), nullable=True),

        # Configuration columns
        sa.Column('max_children', sa.Integer(), server_default='12'),
        sa.Column('page_size_tokens', sa.Integer(), server_default='8000'),
        sa.Column('context_budget_pct', sa.Integer(), server_default='40'),

        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('last_active_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_cortex_trees_entity_id', 'cortex_trees', ['entity_id'])
    op.create_index('ix_cortex_trees_company_id', 'cortex_trees', ['company_id'])
    op.create_index('ix_cortex_trees_status', 'cortex_trees', ['status'])

    # --- cortex_nodes ---
    op.create_table(
        'cortex_nodes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tree_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('cortex_trees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('cortex_nodes.id', ondelete='SET NULL'), nullable=True),

        sa.Column('node_type', cortex_node_type, nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('content_tokens', sa.Integer(), server_default='0'),

        sa.Column('status', cortex_node_status, nullable=False, server_default='pending'),
        sa.Column('source_ref', postgresql.JSONB(), nullable=True),
        sa.Column('execution_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('execution_runs.id'), nullable=True),

        sa.Column('depth', sa.Integer(), server_default='0'),
        sa.Column('sibling_order', sa.Integer(), server_default='0'),

        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('metadata_extra', postgresql.JSONB(), nullable=True),
    )
    op.create_index('ix_cortex_nodes_tree_id', 'cortex_nodes', ['tree_id'])
    op.create_index('ix_cortex_nodes_parent_id', 'cortex_nodes', ['parent_id'])
    op.create_index('ix_cortex_nodes_tree_parent', 'cortex_nodes', ['tree_id', 'parent_id'])
    op.create_index('ix_cortex_nodes_tree_type', 'cortex_nodes', ['tree_id', 'node_type'])
    op.create_index('ix_cortex_nodes_status', 'cortex_nodes', ['status'])

    # --- Add tree_id FK to cortex_trees for root/output/cursor nodes ---
    # (these are deferred FKs since the nodes table didn't exist yet)
    op.create_foreign_key(
        'fk_cortex_trees_root_node',
        'cortex_trees', 'cortex_nodes',
        ['root_node_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_cortex_trees_output_root',
        'cortex_trees', 'cortex_nodes',
        ['output_root_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_cortex_trees_resume_cursor',
        'cortex_trees', 'cortex_nodes',
        ['resume_cursor_id'], ['id'],
        ondelete='SET NULL',
    )

    # --- Add tree_id to episodic_memories (if table exists) ---
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'episodic_memories')")
    )
    has_episodic = result.scalar()

    if has_episodic:
        op.add_column(
            'episodic_memories',
            sa.Column('tree_id', postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            'fk_episodic_memories_tree_id',
            'episodic_memories', 'cortex_trees',
            ['tree_id'], ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    # --- Remove tree_id from episodic_memories (if table exists) ---
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'episodic_memories' AND column_name = 'tree_id')")
    )
    has_column = result.scalar()

    if has_column:
        op.drop_constraint('fk_episodic_memories_tree_id', 'episodic_memories', type_='foreignkey')
        op.drop_column('episodic_memories', 'tree_id')

    # --- Drop foreign keys from cortex_trees ---
    op.drop_constraint('fk_cortex_trees_resume_cursor', 'cortex_trees', type_='foreignkey')
    op.drop_constraint('fk_cortex_trees_output_root', 'cortex_trees', type_='foreignkey')
    op.drop_constraint('fk_cortex_trees_root_node', 'cortex_trees', type_='foreignkey')

    # --- Drop tables ---
    op.drop_table('cortex_nodes')
    op.drop_table('cortex_trees')

    # --- Drop enum types ---
    op.execute("DROP TYPE IF EXISTS cortex_node_status")
    op.execute("DROP TYPE IF EXISTS cortex_node_type")
    op.execute("DROP TYPE IF EXISTS cortex_tree_status")


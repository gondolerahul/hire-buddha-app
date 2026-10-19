"""Add unified CORTEX memory v2 schema

Phase A of the Unified CORTEX Memory Architecture v2.0 migration.

Adds:
- memory_domain enum type (knowledge, experience, intelligence, episodic)
- scope_level enum type (app, partner, tenant, user, entity, runtime)
- 12 new values to cortex_node_type enum
- New columns on cortex_trees (domain, scope, scheduling, consolidation)
- New columns on cortex_nodes (embedding, access tracking, importance)
- New cortex_edges table for the semantic graph layer
- HNSW and composite indexes

IMPORTANT: ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
This migration uses AUTOCOMMIT for enum extension statements, then a
regular transaction for everything else.

Revision ID: x1y2z3a4b5c6
Revises: w1x2y3z4a5b6
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'x1y2z3a4b5c6'
down_revision = ('p3_idempotency_001', 'v1w2x3y4z5a6')
branch_labels = None
depends_on = None


# --- New node type values to add to the existing enum ---
NEW_NODE_TYPES = [
    'group',
    'document',
    'section',
    'chunk',
    'observation',
    'pattern',
    'suggestion',
    'instruction',
    'strategy',
    'preference',
    'episode',
    'episode_group',
]


def upgrade() -> None:
    # ══════════════════════════════════════════════════════════════════
    # PHASE 1: Non-transactional enum extensions (AUTOCOMMIT required)
    # PostgreSQL does not allow ALTER TYPE ... ADD VALUE in a transaction.
    # ══════════════════════════════════════════════════════════════════

    # Create new enum types
    op.execute("CREATE TYPE memory_domain AS ENUM ('knowledge', 'experience', 'intelligence', 'episodic')")
    op.execute("CREATE TYPE scope_level AS ENUM ('app', 'partner', 'tenant', 'user', 'entity', 'runtime')")

    # Extend existing cortex_node_type enum with new values
    # NOTE: ADD VALUE IF NOT EXISTS requires PostgreSQL 9.3+
    for val in NEW_NODE_TYPES:
        op.execute(f"ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS '{val}'")

    # ══════════════════════════════════════════════════════════════════
    # PHASE 2: Transactional schema changes
    # ══════════════════════════════════════════════════════════════════

    # --- Extend cortex_trees table ---
    op.add_column('cortex_trees', sa.Column(
        'memory_domain',
        postgresql.ENUM('knowledge', 'experience', 'intelligence', 'episodic',
                        name='memory_domain', create_type=False),
        server_default='knowledge',
        nullable=False,
    ))
    op.add_column('cortex_trees', sa.Column(
        'scope_level',
        postgresql.ENUM('app', 'partner', 'tenant', 'user', 'entity', 'runtime',
                        name='scope_level', create_type=False),
        server_default='runtime',
        nullable=False,
    ))
    op.add_column('cortex_trees', sa.Column(
        'app_id', postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.add_column('cortex_trees', sa.Column(
        'partner_id', postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.add_column('cortex_trees', sa.Column(
        'run_id', postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.add_column('cortex_trees', sa.Column(
        'tree_category', sa.String(100), nullable=True,
    ))
    op.add_column('cortex_trees', sa.Column(
        'expires_at', sa.DateTime(), nullable=True,
    ))
    op.add_column('cortex_trees', sa.Column(
        'is_persistent', sa.Boolean(), server_default='true', nullable=False,
    ))
    op.add_column('cortex_trees', sa.Column(
        'last_consolidated_at', sa.DateTime(), nullable=True,
    ))
    op.add_column('cortex_trees', sa.Column(
        'consolidation_generation', sa.Integer(), server_default='0', nullable=False,
    ))
    op.add_column('cortex_trees', sa.Column(
        'source_run_ids', postgresql.JSONB(), nullable=True,
    ))

    # Foreign keys for scope columns
    op.create_foreign_key(
        'fk_cortex_trees_app_id', 'cortex_trees', 'companies',
        ['app_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_cortex_trees_partner_id', 'cortex_trees', 'companies',
        ['partner_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_cortex_trees_run_id', 'cortex_trees', 'execution_runs',
        ['run_id'], ['id'], ondelete='SET NULL',
    )

    # --- Extend cortex_nodes table ---
    # pgvector embedding column (768 dimensions for Gemini embeddings)
    op.execute("ALTER TABLE cortex_nodes ADD COLUMN embedding vector(768)")
    op.add_column('cortex_nodes', sa.Column(
        'embedding_model', sa.String(100), nullable=True,
    ))
    op.add_column('cortex_nodes', sa.Column(
        'cross_refs', postgresql.JSONB(), nullable=True,
    ))
    op.add_column('cortex_nodes', sa.Column(
        'access_count', sa.Integer(), server_default='0', nullable=False,
    ))
    op.add_column('cortex_nodes', sa.Column(
        'last_accessed_at', sa.DateTime(), nullable=True,
    ))
    op.add_column('cortex_nodes', sa.Column(
        'importance_score', sa.Numeric(5, 3), server_default='0.500', nullable=False,
    ))

    # --- Create cortex_edges table ---
    op.create_table(
        'cortex_edges',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('source_node_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('cortex_nodes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_node_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('cortex_nodes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('edge_type', sa.String(50), nullable=False),
        sa.Column('weight', sa.Numeric(5, 4), server_default='0.5000'),
        sa.Column('traversal_count', sa.Integer(), server_default='0'),
        sa.Column('last_traversed_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.String(50), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('source_node_id', 'target_node_id', 'edge_type',
                            name='uq_cortex_edges_src_tgt_type'),
    )

    # --- Indexes ---
    # cortex_trees: domain and scope queries
    op.create_index('ix_cortex_trees_domain_scope', 'cortex_trees',
                    ['memory_domain', 'scope_level'])
    op.create_index('ix_cortex_trees_scope_entity', 'cortex_trees',
                    ['scope_level', 'entity_id'],
                    postgresql_where=sa.text('entity_id IS NOT NULL'))
    op.create_index('ix_cortex_trees_scope_user', 'cortex_trees',
                    ['scope_level', 'user_id'],
                    postgresql_where=sa.text('user_id IS NOT NULL'))
    op.create_index('ix_cortex_trees_scope_company', 'cortex_trees',
                    ['scope_level', 'company_id'])

    # cortex_nodes: HNSW vector index for embedding similarity search
    op.execute("""
        CREATE INDEX ix_cortex_nodes_embedding
        ON cortex_nodes
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.create_index('ix_cortex_nodes_importance', 'cortex_nodes',
                    [sa.text('importance_score DESC')])
    op.create_index('ix_cortex_nodes_tree_type_status', 'cortex_nodes',
                    ['tree_id', 'node_type', 'status'])
    op.create_index('ix_cortex_nodes_created_at', 'cortex_nodes',
                    ['created_at'])

    # cortex_edges: traversal and lookup indexes
    op.create_index('ix_cortex_edges_source', 'cortex_edges', ['source_node_id'])
    op.create_index('ix_cortex_edges_target', 'cortex_edges', ['target_node_id'])
    op.create_index('ix_cortex_edges_type_weight', 'cortex_edges',
                    ['edge_type', sa.text('weight DESC')])


def downgrade() -> None:
    # --- Drop indexes ---
    op.drop_index('ix_cortex_edges_type_weight', table_name='cortex_edges')
    op.drop_index('ix_cortex_edges_target', table_name='cortex_edges')
    op.drop_index('ix_cortex_edges_source', table_name='cortex_edges')
    op.drop_index('ix_cortex_nodes_created_at', table_name='cortex_nodes')
    op.drop_index('ix_cortex_nodes_tree_type_status', table_name='cortex_nodes')
    op.drop_index('ix_cortex_nodes_importance', table_name='cortex_nodes')
    op.drop_index('ix_cortex_nodes_embedding', table_name='cortex_nodes')
    op.drop_index('ix_cortex_trees_scope_company', table_name='cortex_trees')
    op.drop_index('ix_cortex_trees_scope_user', table_name='cortex_trees')
    op.drop_index('ix_cortex_trees_scope_entity', table_name='cortex_trees')
    op.drop_index('ix_cortex_trees_domain_scope', table_name='cortex_trees')

    # --- Drop cortex_edges table ---
    op.drop_table('cortex_edges')

    # --- Remove new columns from cortex_nodes ---
    op.drop_column('cortex_nodes', 'importance_score')
    op.drop_column('cortex_nodes', 'last_accessed_at')
    op.drop_column('cortex_nodes', 'access_count')
    op.drop_column('cortex_nodes', 'cross_refs')
    op.drop_column('cortex_nodes', 'embedding_model')
    op.drop_column('cortex_nodes', 'embedding')

    # --- Remove foreign keys and new columns from cortex_trees ---
    op.drop_constraint('fk_cortex_trees_run_id', 'cortex_trees', type_='foreignkey')
    op.drop_constraint('fk_cortex_trees_partner_id', 'cortex_trees', type_='foreignkey')
    op.drop_constraint('fk_cortex_trees_app_id', 'cortex_trees', type_='foreignkey')
    op.drop_column('cortex_trees', 'source_run_ids')
    op.drop_column('cortex_trees', 'consolidation_generation')
    op.drop_column('cortex_trees', 'last_consolidated_at')
    op.drop_column('cortex_trees', 'is_persistent')
    op.drop_column('cortex_trees', 'expires_at')
    op.drop_column('cortex_trees', 'tree_category')
    op.drop_column('cortex_trees', 'run_id')
    op.drop_column('cortex_trees', 'partner_id')
    op.drop_column('cortex_trees', 'app_id')
    op.drop_column('cortex_trees', 'scope_level')
    op.drop_column('cortex_trees', 'memory_domain')

    # --- Drop new enum types ---
    # NOTE: Cannot remove values from an existing enum in PostgreSQL.
    # The new cortex_node_type values will remain.
    op.execute("DROP TYPE IF EXISTS scope_level")
    op.execute("DROP TYPE IF EXISTS memory_domain")

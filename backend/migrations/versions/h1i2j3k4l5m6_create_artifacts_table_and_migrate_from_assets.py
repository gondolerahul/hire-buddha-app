"""create_artifacts_table_and_migrate_from_assets

Revision ID: h1i2j3k4l5m6
Revises: g1h2i3j4k5l6
Create Date: 2026-03-02 08:00:00.000000

This migration:
  1. Creates the unified 'artifacts' table (replaces 'assets')
  2. Migrates existing data from 'assets' into 'artifacts'
  3. Updates the 'call_content' table's audio_asset_id → audio_artifact_id FK
  4. Leaves 'assets' table in place (dropped last after verification)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'h1i2j3k4l5m6'
down_revision: Union[str, Sequence[str], None] = 'g1h2i3j4k5l6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # 1. CREATE ARTIFACTS TABLE
    # Replaces 'assets'. Stores both user-uploaded and system-generated files.
    # Storage path: artifact/{origin}/{company_id}/{YYYY-MM-DD}/{file_name}
    # =========================================================================
    op.create_table(
        'artifacts',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=True),
        sa.Column('agent_id', sa.UUID(), nullable=True),
        sa.Column('run_id', sa.UUID(), nullable=True),
        # Origin: who produced this file
        sa.Column('origin', sa.String(30), nullable=False, server_default='system-generated'),
        # What kind of content
        sa.Column('file_category', sa.String(50), nullable=False, server_default='documents'),
        sa.Column('file_name', sa.String(500), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(100), nullable=True),
        # Provenance
        sa.Column('purpose', sa.Text(), nullable=True),
        sa.Column('generated_by', sa.String(200), nullable=True),
        sa.Column('artifact_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['campaign_id'], ['hierarchical_entities.id']),
        sa.ForeignKeyConstraint(['agent_id'], ['hierarchical_entities.id']),
        sa.ForeignKeyConstraint(['run_id'], ['execution_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # Indexes for common query patterns
    op.create_index('idx_artifacts_company', 'artifacts', ['company_id'])
    op.create_index('idx_artifacts_campaign', 'artifacts', ['campaign_id'])
    op.create_index('idx_artifacts_agent', 'artifacts', ['agent_id'])
    op.create_index('idx_artifacts_origin', 'artifacts', ['origin'])
    op.create_index('idx_artifacts_file_category', 'artifacts', ['file_category'])
    op.create_index('idx_artifacts_created_at', 'artifacts', ['created_at'])

    # =========================================================================
    # 2. MIGRATE DATA FROM assets → artifacts
    # Map: file_type → file_category, asset_metadata → artifact_metadata
    # All existing assets are treated as 'system-generated'
    # =========================================================================
    op.execute("""
        INSERT INTO artifacts (
            id, company_id, campaign_id, agent_id, run_id,
            origin, file_category, file_name, file_path,
            file_size, duration_seconds, mime_type,
            purpose, generated_by, artifact_metadata, created_at
        )
        SELECT
            id,
            company_id,
            campaign_id,
            agent_id,
            run_id,
            'system-generated'                          AS origin,
            COALESCE(file_type, 'documents')            AS file_category,
            file_name,
            COALESCE(file_path, '')                     AS file_path,
            file_size,
            duration_seconds,
            mime_type,
            'Migrated from legacy assets table'         AS purpose,
            'legacy:asset_migration'                    AS generated_by,
            COALESCE(asset_metadata, '{}'::json)        AS artifact_metadata,
            created_at
        FROM assets
        ON CONFLICT (id) DO NOTHING
    """)

    # =========================================================================
    # 3. UPDATE call_content TO REFERENCE artifacts INSTEAD OF assets
    # =========================================================================
    # Add new FK column
    op.add_column('call_content', sa.Column('audio_artifact_id', sa.UUID(), nullable=True))

    # Copy existing references
    op.execute("""
        UPDATE call_content
        SET audio_artifact_id = audio_asset_id
        WHERE audio_asset_id IS NOT NULL
    """)

    # Add FK constraint to artifacts
    op.create_foreign_key(
        'fk_call_content_audio_artifact',
        'call_content', 'artifacts',
        ['audio_artifact_id'], ['id']
    )

    # Drop old column (keep audio_asset_id for one release as a safety backup)
    # We intentionally leave audio_asset_id in place — it can be dropped in a
    # follow-up migration once the deployment has been verified.


def downgrade() -> None:
    # Remove FK and column added to call_content
    op.drop_constraint('fk_call_content_audio_artifact', 'call_content', type_='foreignkey')
    op.drop_column('call_content', 'audio_artifact_id')

    # Drop artifacts table and its indexes
    op.drop_index('idx_artifacts_created_at', 'artifacts')
    op.drop_index('idx_artifacts_file_category', 'artifacts')
    op.drop_index('idx_artifacts_origin', 'artifacts')
    op.drop_index('idx_artifacts_agent', 'artifacts')
    op.drop_index('idx_artifacts_campaign', 'artifacts')
    op.drop_index('idx_artifacts_company', 'artifacts')
    op.drop_table('artifacts')

"""Remove legacy entity fields (is_active, static_plan, llm_config, toolkit)

Revision ID: s1t2u3v4w5x6
Revises: r1s2t3u4v5w6
Create Date: 2026-04-16

These columns have been superseded by the unified entity structure:
  - is_active  → replaced by status column (DRAFT/ACTIVE/DEPRECATED/ARCHIVED)
  - static_plan → moved into planning.static_plan JSON field
  - llm_config  → moved into logic_gate.reasoning_config JSON field
  - toolkit     → moved into capabilities.tools JSON field

Before dropping, the upgrade() migrates any remaining data:
  - is_active=False → status='ARCHIVED' (if status was still ACTIVE)
  - static_plan data → merged into planning JSON blob
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = 's1t2u3v4w5x6'
down_revision = 'r1s2t3u4v5w6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Step 1: Migrate is_active=False → status='ARCHIVED' ──────────
    conn.execute(text("""
        UPDATE hierarchical_entities
        SET status = 'ARCHIVED'
        WHERE is_active = false
          AND status = 'ACTIVE'
    """))

    # ── Step 2: Migrate static_plan into planning JSON ───────────────
    # For entities that have a top-level static_plan but no planning.static_plan,
    # merge it into the planning blob.
    conn.execute(text("""
        UPDATE hierarchical_entities
        SET planning = jsonb_set(
            COALESCE(planning::jsonb, '{}'::jsonb),
            '{static_plan}',
            static_plan::jsonb
        )
        WHERE static_plan IS NOT NULL
          AND static_plan::text != 'null'
          AND (planning IS NULL OR NOT (planning::jsonb ? 'static_plan')
               OR (planning::jsonb -> 'static_plan')::text = '{}')
    """))

    # ── Step 3: Migrate llm_config into logic_gate.reasoning_config ──
    conn.execute(text("""
        UPDATE hierarchical_entities
        SET logic_gate = jsonb_set(
            COALESCE(logic_gate::jsonb, '{"reasoning_config": {}}'::jsonb),
            '{reasoning_config}',
            llm_config::jsonb
        )
        WHERE llm_config IS NOT NULL
          AND llm_config::text != 'null'
          AND (logic_gate IS NULL OR NOT (logic_gate::jsonb ? 'reasoning_config')
               OR (logic_gate::jsonb -> 'reasoning_config')::text = '{}')
    """))

    # ── Step 4: Drop legacy columns ──────────────────────────────────
    op.drop_column('hierarchical_entities', 'is_active')
    op.drop_column('hierarchical_entities', 'static_plan')
    op.drop_column('hierarchical_entities', 'llm_config')
    op.drop_column('hierarchical_entities', 'toolkit')


def downgrade() -> None:
    # Re-add columns with defaults
    op.add_column('hierarchical_entities',
                  sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=True))
    op.add_column('hierarchical_entities',
                  sa.Column('static_plan', sa.JSON(), nullable=True))
    op.add_column('hierarchical_entities',
                  sa.Column('llm_config', sa.JSON(), nullable=True))
    op.add_column('hierarchical_entities',
                  sa.Column('toolkit', sa.JSON(), nullable=True))

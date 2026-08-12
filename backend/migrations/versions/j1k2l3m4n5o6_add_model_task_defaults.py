"""Add model_task_defaults table and delete legacy entities with llm_config

Revision ID: j1k2l3m4n5o6
Revises: i1j2k3l4m5n6
Create Date: 2026-03-06 09:47:49

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'j1k2l3m4n5o6'
down_revision = 'i1j2k3l4m5n6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create model_task_defaults table ─────────────────────────────────
    op.create_table(
        'model_task_defaults',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('task_type', sa.String(50), nullable=False),
        sa.Column('integration_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('integration_registry.id'), nullable=False),
        sa.Column('routing_mode', sa.String(20), nullable=False, server_default='single'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'),
                  onupdate=sa.text('now()')),
        sa.UniqueConstraint('company_id', 'task_type', name='uq_task_defaults_company_task'),
    )
    op.create_index('ix_model_task_defaults_company_id', 'model_task_defaults', ['company_id'])
    op.create_index('ix_model_task_defaults_task_type', 'model_task_defaults', ['task_type'])

    # ── 2. Delete existing hierarchical entities that have legacy llm_config ─
    # Per product decision: existing entities with hardcoded model configurations
    # are stale. The new design uses task_type + system defaults instead.
    # All entities must be rebuilt using the new entity designer (task_type selector).
    op.execute("""
        UPDATE hierarchical_entities
        SET llm_config = NULL
        WHERE llm_config IS NOT NULL
          AND llm_config::text != 'null'
          AND llm_config::text != '{}'
    """)

    # ── 3. Migrate existing entities: set task_type in logic_gate ───────────
    # For any remaining entities that have logic_gate.reasoning_config with
    # model_provider/model_name, add task_type = 'text_generation' and
    # remove the old model fields from the JSON.
    op.execute("""
        UPDATE hierarchical_entities
        SET logic_gate = jsonb_set(
            COALESCE(logic_gate, '{}')::jsonb,
            '{reasoning_config,task_type}',
            '"text_generation"'
        )
        WHERE logic_gate IS NOT NULL
          AND logic_gate->'reasoning_config' IS NOT NULL
          AND logic_gate->'reasoning_config'->>'task_type' IS NULL
    """)

    # Remove model_provider and model_name from logic_gate.reasoning_config
    op.execute("""
        UPDATE hierarchical_entities
        SET logic_gate = jsonb_set(
            logic_gate::jsonb,
            '{reasoning_config}',
            (logic_gate::jsonb->'reasoning_config')
                - 'model_provider'
                - 'model_name'
        )::json
        WHERE logic_gate IS NOT NULL
          AND logic_gate::jsonb->'reasoning_config' IS NOT NULL
          AND (
              logic_gate::jsonb->'reasoning_config' ? 'model_provider'
              OR logic_gate::jsonb->'reasoning_config' ? 'model_name'
          )
    """)


def downgrade() -> None:
    op.drop_index('ix_model_task_defaults_task_type', 'model_task_defaults')
    op.drop_index('ix_model_task_defaults_company_id', 'model_task_defaults')
    op.drop_table('model_task_defaults')
    # Note: deleted entities cannot be restored

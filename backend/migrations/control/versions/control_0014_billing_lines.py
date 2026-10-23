"""billing lines and the shadow comparison (Phase 15 T3-4, T3-7)

Revision ID: control_0014_billing_lines
Revises: control_0013_usage_rating
Create Date: 2026-10-23

* ``billing_lines`` — billed per company, day, category and grouping (entity
  id), in USD and in the company's currency at the settlement's locked rate
  (tech design §5.3). Written beside ``billing_events`` from now on; it
  replaces them for reporting (T3-8).
* ``billing_shadow_diffs`` — each settled run or call priced the old way and
  as the sum of its rated rows (T3-7).
* ``platform_settings`` ``billing.v2_mode`` = ``shadow``: the comparison is
  recorded; nothing is billed differently (plan §6).

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'control_0014_billing_lines'
down_revision: Union[str, Sequence[str], None] = 'control_0013_usage_rating'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXACT = sa.Numeric(precision=24, scale=10)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('billing_lines',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('period_day', sa.Date(), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('grouping_type', sa.String(length=30), nullable=True),
    sa.Column('grouping_id', sa.UUID(), nullable=True),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('fx_rate_id', sa.UUID(), nullable=True),
    sa.Column('cost_usd', EXACT, nullable=False),
    sa.Column('billed_usd', EXACT, nullable=False),
    sa.Column('billed_ccy', EXACT, nullable=False),
    sa.Column('quantity', EXACT, nullable=False),
    sa.Column('rows', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'period_day', 'category', 'grouping_type', 'grouping_id', 'currency',
                        name='uq_billing_lines_key', postgresql_nulls_not_distinct=True),
    info={'plane': 'control'}
    )
    op.create_index('ix_billing_lines_company_day', 'billing_lines', ['company_id', 'period_day'], unique=False)
    op.create_table('billing_shadow_diffs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('subject_type', sa.String(length=10), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=True),
    sa.Column('v1_cost_usd', EXACT, nullable=False),
    sa.Column('v1_billed_usd', EXACT, nullable=False),
    sa.Column('v2_cost_usd', EXACT, nullable=False),
    sa.Column('v2_billed_usd', EXACT, nullable=False),
    sa.Column('diff_usd', EXACT, nullable=False),
    sa.Column('rows', sa.Integer(), nullable=False),
    sa.Column('formula_ids', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"),
              nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'control'}
    )
    op.create_index('ix_billing_shadow_diffs_company', 'billing_shadow_diffs', ['company_id', 'created_at'],
                    unique=False)
    op.execute("INSERT INTO platform_settings (key, scope, value_json) VALUES ('billing.v2_mode', 'platform', "
               "'\"shadow\"'::jsonb) ON CONFLICT DO NOTHING")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM platform_settings WHERE key = 'billing.v2_mode'")
    op.drop_index('ix_billing_shadow_diffs_company', table_name='billing_shadow_diffs')
    op.drop_table('billing_shadow_diffs')
    op.drop_index('ix_billing_lines_company_day', table_name='billing_lines')
    op.drop_table('billing_lines')

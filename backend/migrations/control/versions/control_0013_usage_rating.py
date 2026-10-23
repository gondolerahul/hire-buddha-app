"""usage rows rated at write (Phase 15 T3-3)

Revision ID: control_0013_usage_rating
Revises: control_0012_billing_formulas
Create Date: 2026-10-23

``usage_logs`` + ``billed_usd``, ``formula_id``, ``category`` (rated when the
row is written, tech design §5.1, §5.3) and ``settlement_id``, ``currency``,
``billed_ccy``, ``fx_rate_id`` (filled when the row is settled, WS15-4), with a
partial index on the unsettled rows.

Existing rows are rated with the formula in effect now — the company's, else
the platform's, else billed = cost — and given their category, so billed
amounts can be shown for history. ``settlement_id`` stays NULL: the old
settlement path still charges runs and calls; the rows it charged are marked
when the new path takes over (plan §4 step 5, at the switch).

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'control_0013_usage_rating'
down_revision: Union[str, Sequence[str], None] = 'control_0012_billing_formulas'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ('billed_usd', 'formula_id', 'category', 'settlement_id', 'currency', 'billed_ccy', 'fx_rate_id')


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('usage_logs', sa.Column('billed_usd', sa.Numeric(precision=24, scale=10), nullable=True))
    op.add_column('usage_logs', sa.Column('formula_id', sa.UUID(), nullable=True))
    op.add_column('usage_logs', sa.Column('category', sa.String(length=30), nullable=True))
    op.add_column('usage_logs', sa.Column('settlement_id', sa.UUID(), nullable=True))
    op.add_column('usage_logs', sa.Column('currency', sa.CHAR(length=3), nullable=True))
    op.add_column('usage_logs', sa.Column('billed_ccy', sa.Numeric(precision=24, scale=10), nullable=True))
    op.add_column('usage_logs', sa.Column('fx_rate_id', sa.UUID(), nullable=True))
    op.create_index('ix_usage_logs_unsettled', 'usage_logs', ['company_id'], unique=False,
                    postgresql_where=sa.text('settlement_id IS NULL'))
    op.execute("""
        UPDATE usage_logs u SET
            billed_usd = u.calculated_cost * COALESCE(f.mf, 1) * (1 + COALESCE(f.pf, 0) - COALESCE(f.d, 0)),
            formula_id = f.id
        FROM usage_logs u2
        LEFT JOIN LATERAL (
            SELECT bf.id, bf.mf, bf.pf, bf.d FROM billing_formulas bf
            WHERE bf.active AND bf.effective_from <= now()
              AND ((bf.scope = 'company' AND bf.scope_id = u2.company_id) OR bf.scope = 'platform')
            ORDER BY (bf.scope = 'company') DESC, bf.effective_from DESC
            LIMIT 1
        ) f ON true
        WHERE u2.id = u.id
    """)
    op.execute("""
        UPDATE usage_logs u SET category = CASE
            WHEN u.attribution IN ('planner', 'actor_step', 'critic_pre', 'critic_post', 'critic_align',
                                   'critic_super', 'reformat_retry', 'meta_review', 'dreaming',
                                   'meta_spec_critic', 'test_driver', 'child_run') THEN 'ai_models'
            WHEN u.attribution = 'embedding' THEN 'knowledge'
            WHEN u.attribution = 'voice_call' THEN 'voice'
            WHEN u.attribution = 'video_frame' THEN 'video'
            WHEN u.attribution = 'sandbox' THEN 'sandbox'
            WHEN u.attribution = 'hosting' AND r.service_sku IN ('tenant-db-pool-share', 'tenant-db-dedicated')
                THEN 'database'
            WHEN u.attribution = 'hosting' THEN 'hosting'
            WHEN r.service_category IN ('IMAGE_GENERATION', 'VIDEO_GENERATION', 'SPEECH_GENERATION',
                                        'MUSIC_GENERATION') THEN 'media'
            ELSE 'tools' END
        FROM usage_logs u2 LEFT JOIN integration_registry r ON r.id = u2.sku_id
        WHERE u2.id = u.id
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_usage_logs_unsettled', table_name='usage_logs', postgresql_where=sa.text('settlement_id IS NULL'))
    for column in reversed(COLUMNS):
        op.drop_column('usage_logs', column)

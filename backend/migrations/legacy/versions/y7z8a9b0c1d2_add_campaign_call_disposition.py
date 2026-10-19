"""add_campaign_call_disposition

Revision ID: y7z8a9b0c1d2
Revises: p12_run_csat
Create Date: 2026-07-12

Adds campaign_calls.disposition for report sorting (interested |
not_interested | voicemail | rejected | busy | no_answer | failed) and
backfills it from existing telephony outcomes. Also widens status to hold
the new 'completed-voicemail' value (19 chars fits String(20); no DDL
needed there).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'y7z8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'p12_run_csat'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'campaign_calls',
        sa.Column('disposition', sa.String(30), nullable=True),
    )
    op.create_index(
        'idx_campaign_calls_disposition', 'campaign_calls', ['disposition']
    )
    # Backfill from telephony outcomes; answered/completed calls stay NULL
    # until the LLM classification pass assigns interested/not_interested.
    op.execute(
        "UPDATE campaign_calls SET disposition = outcome "
        "WHERE disposition IS NULL "
        "AND outcome IN ('busy', 'no_answer', 'rejected', 'failed')"
    )
    op.execute(
        "UPDATE campaign_calls SET disposition = 'failed' "
        "WHERE disposition IS NULL AND status = 'failed'"
    )


def downgrade() -> None:
    op.drop_index('idx_campaign_calls_disposition', table_name='campaign_calls')
    op.drop_column('campaign_calls', 'disposition')

"""add_campaign_call_disposition_reason

Revision ID: z9b0c1d2e3f4
Revises: y7z8a9b0c1d2
Create Date: 2026-07-15

Adds campaign_calls.disposition_reason: the LLM-classified reason a lead
was not interested (budget_low | not_suitable | not_investing |
already_bought | other). NULL for every other disposition.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'z9b0c1d2e3f4'
down_revision: Union[str, Sequence[str], None] = 'y7z8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'campaign_calls',
        sa.Column('disposition_reason', sa.String(30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('campaign_calls', 'disposition_reason')

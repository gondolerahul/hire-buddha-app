"""fix billing config columns

Revision ID: 2999001a9221
Revises: f858e53bdd32
Create Date: 2026-04-07 16:37:01.005024

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2999001a9221'
down_revision = 'q1r2s3t4u5v6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Adding missing columns to billing_config
    op.add_column('billing_config', sa.Column('default_daily_credits', sa.Numeric(precision=10, scale=4), nullable=False, server_default='5.0'))
    op.add_column('billing_config', sa.Column('base_cost_telephony', sa.Numeric(precision=14, scale=6), nullable=True))
    op.add_column('billing_config', sa.Column('base_cost_llm', sa.Numeric(precision=14, scale=6), nullable=True))
    op.add_column('billing_config', sa.Column('base_cost_image_gen', sa.Numeric(precision=14, scale=6), nullable=True))

    # Adding missing columns to billing_events
    op.add_column('billing_events', sa.Column('telephony_charge', sa.Numeric(precision=14, scale=6), nullable=False, server_default='0'))
    op.add_column('billing_events', sa.Column('llm_charge', sa.Numeric(precision=14, scale=6), nullable=False, server_default='0'))
    op.add_column('billing_events', sa.Column('image_charge', sa.Numeric(precision=14, scale=6), nullable=False, server_default='0'))
    op.add_column('billing_events', sa.Column('video_charge', sa.Numeric(precision=14, scale=6), nullable=False, server_default='0'))
    op.add_column('billing_events', sa.Column('api_charge', sa.Numeric(precision=14, scale=6), nullable=False, server_default='0'))


def downgrade() -> None:
    # Dropping columns from billing_events
    op.drop_column('billing_events', 'api_charge')
    op.drop_column('billing_events', 'video_charge')
    op.drop_column('billing_events', 'image_charge')
    op.drop_column('billing_events', 'llm_charge')
    op.drop_column('billing_events', 'telephony_charge')

    # Dropping columns from billing_config
    op.drop_column('billing_config', 'base_cost_image_gen')
    op.drop_column('billing_config', 'base_cost_llm')
    op.drop_column('billing_config', 'base_cost_telephony')
    op.drop_column('billing_config', 'default_daily_credits')

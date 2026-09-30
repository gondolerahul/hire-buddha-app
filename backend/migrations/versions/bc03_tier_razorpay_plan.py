"""A subscription tier carries its Razorpay plan (BC-03, BC-16)

Revision ID: bc03_tier_razorpay_plan
Revises: dm04_billing_event_unique
Create Date: 2026-09-30

Subscriptions became Razorpay Subscriptions: each is created on a Razorpay plan
made from the tier (monthly, the tier's fee in USD cents). The plan id is stored
on the tier so every subscriber to it shares one plan; it is cleared when the
tier's fee changes, because Razorpay plans are immutable.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "bc03_tier_razorpay_plan"
down_revision: Union[str, Sequence[str], None] = "dm04_billing_event_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("subscription_tiers")}
    if "razorpay_plan_id" not in have:
        op.add_column("subscription_tiers", sa.Column("razorpay_plan_id", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("subscription_tiers", "razorpay_plan_id")

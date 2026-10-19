"""A usage_logs row may have no SKU (BC-07)

Revision ID: bc07_usage_log_sku_nullable
Revises: au08_verify_existing_users
Create Date: 2026-09-30

A fixed-cost tool charge (image_generation, video_generate) has no
integration_registry row, and usage_logs.sku_id was NOT NULL, so the charge
reached run.total_cost_usd with no line item. The row is now written with a
NULL SKU and the tool's name in log_metadata.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "bc07_usage_log_sku_nullable"
down_revision: Union[str, Sequence[str], None] = "au08_verify_existing_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("usage_logs", "sku_id", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM usage_logs WHERE sku_id IS NULL")
    op.alter_column("usage_logs", "sku_id", nullable=False)

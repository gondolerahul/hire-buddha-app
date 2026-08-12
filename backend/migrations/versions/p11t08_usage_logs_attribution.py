"""Phase 11 Track 8 — usage_logs.attribution column.

Adds a structured attribution tag to every billing row so the cost
dashboard (Track 9) can break run cost down by source: planner,
actor_step, critic_*, tool, child_run, embedding, etc. The default
``'tool'`` covers existing rows so the migration is non-destructive.

Revision ID: p11t08_usage_attr
Revises: x1y2z3a4b5c6
Create Date: 2026-05-27
"""
from alembic import op
import sqlalchemy as sa


revision = "p11t08_usage_attr"
down_revision = "x1y2z3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usage_logs",
        sa.Column(
            "attribution",
            sa.String(40),
            nullable=False,
            server_default="tool",
        ),
    )
    op.create_index(
        "ix_usage_logs_attribution",
        "usage_logs",
        ["attribution"],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_logs_attribution", table_name="usage_logs")
    op.drop_column("usage_logs", "attribution")

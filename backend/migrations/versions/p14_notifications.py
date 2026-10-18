"""In-app notifications (Phase 14 WS3 3.11; functional spec §3.6).

Revision ID: p14_notifications
Revises: p14_webhook_triggers
Create Date: 2026-10-18

Control plane: one row per person told; ``dedupe_key`` unique per person.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p14_notifications"
down_revision: Union[str, Sequence[str], None] = "p14_webhook_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False, server_default="warning"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("link", sa.Text()),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("read_at", TS),
        sa.Column("emailed_at", TS),
        sa.CheckConstraint("severity IN ('info', 'warning', 'error')", name="ck_notifications_severity"),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe"),
    )
    op.create_index("ix_notifications_user_unread", "notifications", ["user_id", "created_at"],
                    postgresql_where=sa.text("read_at IS NULL"))


def downgrade() -> None:
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_table("notifications")

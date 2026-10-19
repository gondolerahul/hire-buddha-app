"""Webhook endpoints: a tenant's webhooks arrive at a registered, signed endpoint (GW-01)

Revision ID: h2_webhook_endpoints
Revises: p9_task_fallback
Create Date: 2026-10-07

``POST /webhook/inbound`` took the tenant from a ``client_id`` query parameter and
picked the signature scheme from the request's own headers, and every scheme
returned True. Webhooks now arrive at ``/webhook/inbound/{endpoint_id}``; the
endpoint row names the company, the source, the (encrypted) secret and,
optionally, the agent.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "h2_webhook_endpoints"
down_revision: Union[str, Sequence[str], None] = "p9_task_fallback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SOURCES = ("github", "facebook", "instagram", "linkedin", "twitter", "tiktok", "youtube",
           "twilio", "email", "crm", "pinterest", "generic")


def upgrade() -> None:
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True),
                  sa.ForeignKey("hierarchical_entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("source IN (" + ", ".join(f"'{s}'" for s in SOURCES) + ")",
                           name="ck_webhook_endpoints_source"),
    )
    op.create_index("ix_webhook_endpoints_company", "webhook_endpoints", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_webhook_endpoints_company", table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")

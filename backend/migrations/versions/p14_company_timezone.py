"""A company's business time zone (Phase 14 WS1 1.10)

Revision ID: p14_company_timezone
Revises: p14_artifact_storage_key
Create Date: 2026-10-17

Schedules, reports and an agent's "today" use the company's IANA time zone
instead of a hard-coded India time. Every existing company gets Asia/Kolkata,
which is what the code assumed. Temporary home until the tenant directory
(WS2) carries it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p14_company_timezone"
down_revision: Union[str, Sequence[str], None] = "p14_artifact_storage_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("timezone", sa.String(64), nullable=False,
                                         server_default="Asia/Kolkata"))


def downgrade() -> None:
    op.drop_column("companies", "timezone")

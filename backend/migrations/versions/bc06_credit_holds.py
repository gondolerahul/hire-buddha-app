"""A running execution holds credit (BC-06)

Revision ID: bc06_credit_holds
Revises: au05_token_version
Create Date: 2026-09-30

A top-level run holds its estimated bill from admission until settlement.
Other runs of the company may start only on what the wallet has beyond the
holds, and a running one is stopped when its bill reaches what it may spend —
so two runs cannot both spend the same credit.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "bc06_credit_holds"
down_revision: Union[str, Sequence[str], None] = "au05_token_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "credit_holds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("execution_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(14, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("released_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_credit_holds_open", "credit_holds", ["company_id"],
                    postgresql_where=sa.text("released_at IS NULL"))


def downgrade() -> None:
    op.drop_index("idx_credit_holds_open", table_name="credit_holds")
    op.drop_table("credit_holds")

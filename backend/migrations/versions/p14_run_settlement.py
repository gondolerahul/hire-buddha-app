"""A run's settlement, recorded once on its credit hold (Phase 14 WS2 2.6)

Revision ID: p14_run_settlement
Revises: p14_records
Create Date: 2026-10-19

A run is finished in its tenant's database and charged in the control one, so
the two can no longer commit together. ``credit_holds`` (one row per run, a
control table) now also says when the run was settled and for how much:
settlement sets both in the same transaction as the wallet deduction and the
billing event, and only if the run is not settled yet — a retried
finalisation charges nothing.

Holds already released were released by their run's settlement: they count
as settled (the amount billed is not known for them).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p14_run_settlement"
down_revision: Union[str, Sequence[str], None] = "p14_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("credit_holds", sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("credit_holds", sa.Column("billed_amount", sa.Numeric(14, 6), nullable=True))
    op.execute("UPDATE credit_holds SET settled_at = released_at WHERE released_at IS NOT NULL")


def downgrade() -> None:
    op.drop_column("credit_holds", "billed_amount")
    op.drop_column("credit_holds", "settled_at")

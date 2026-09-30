"""A Razorpay order or payment is recorded once (BC-01)

Revision ID: bc01_payment_txn_unique
Revises: dm05_run_indexes
Create Date: 2026-09-30

``payment_transactions.razorpay_order_id`` was indexed but not unique, and
``razorpay_payment_id`` not indexed at all. Top-up verification looks the
transaction up by order id and credits it once; these indexes make a second
row for the same order or payment impossible, so neither a replayed callback
nor the webhook can credit a payment twice.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "bc01_payment_txn_unique"
down_revision: Union[str, Sequence[str], None] = "dm05_run_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_payment_transactions_razorpay_order")
    op.create_index(
        "uq_payment_transactions_razorpay_order", "payment_transactions", ["razorpay_order_id"],
        unique=True, postgresql_where=sa.text("razorpay_order_id IS NOT NULL"),
    )
    op.create_index(
        "uq_payment_transactions_razorpay_payment", "payment_transactions", ["razorpay_payment_id"],
        unique=True, postgresql_where=sa.text("razorpay_payment_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_payment_transactions_razorpay_payment", table_name="payment_transactions")
    op.drop_index("uq_payment_transactions_razorpay_order", table_name="payment_transactions")
    op.create_index("idx_payment_transactions_razorpay_order", "payment_transactions", ["razorpay_order_id"])

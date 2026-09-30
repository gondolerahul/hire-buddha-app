"""One billing_events row per company, month and grouping (DM-04)

Revision ID: dm04_billing_event_unique
Revises: bc01_payment_txn_unique
Create Date: 2026-09-30

``record_billing_event`` looked for the month's row and inserted one when it
found none, so two concurrent settlements could insert two rows — and every
report summing the table over-counted by the duplicates. Existing duplicates
are merged first: amounts are summed into the oldest row of each group and the
others deleted. Then the unique constraint goes on, with ``NULLS NOT DISTINCT``
(Postgres 15+) so ungrouped rows are covered too.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "dm04_billing_event_unique"
down_revision: Union[str, Sequence[str], None] = "bc01_payment_txn_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAME = "uq_billing_events_period_grouping"
KEY = ["company_id", "period_month", "grouping_type", "grouping_value"]
SUMMED = [
    "base_cost", "multiplied_cost", "platform_fee_amount", "partner_fee_amount",
    "discount_amount", "total_billing", "telephony_charge", "llm_charge", "image_charge",
    "video_charge", "api_charge", "telephony_in_minutes", "telephony_out_minutes",
    "image_gen_count", "video_gen_count", "other_ai_cost",
]


def upgrade() -> None:
    bind = op.get_bind()
    if int(bind.execute(sa.text("SHOW server_version_num")).scalar_one()) < 150000:
        raise RuntimeError("billing_events' unique key needs Postgres 15+ (NULLS NOT DISTINCT)")

    sums = ", ".join(f"sum({c}) AS {c}" for c in SUMMED)
    op.execute(f"""
        CREATE TEMP TABLE billing_event_duplicates ON COMMIT DROP AS
        SELECT (array_agg(id ORDER BY created_at, id))[1] AS keep_id,
               array_agg(id) AS ids, {sums}, max(updated_at) AS updated_at
        FROM billing_events
        GROUP BY {", ".join(KEY)}
        HAVING count(*) > 1
    """)
    assignments = ", ".join(f"{c} = d.{c}" for c in SUMMED + ["updated_at"])
    op.execute(f"UPDATE billing_events b SET {assignments} FROM billing_event_duplicates d WHERE b.id = d.keep_id")
    op.execute("""
        DELETE FROM billing_events b USING billing_event_duplicates d
        WHERE b.id = ANY(d.ids) AND b.id <> d.keep_id
    """)
    op.create_unique_constraint(NAME, "billing_events", KEY, postgresql_nulls_not_distinct=True)


def downgrade() -> None:
    op.drop_constraint(NAME, "billing_events", type_="unique")

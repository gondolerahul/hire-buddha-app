"""A company's monthly spend cap (GH-18)

Revision ID: h4_company_spend_cap
Revises: h4_approval_consumed_at
Create Date: 2026-10-08

Budget lived only on each entity (``governance.max_cost_usd``): there was no
single lever on what a company spends. ``companies.monthly_spend_cap_usd`` is
what the company may be billed in a calendar month; NULL (every existing row)
means no cap. ``CreditService`` checks it before a run, call or campaign
starts, and the run's circuit breaker stops a running run at it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h4_company_spend_cap"
down_revision: Union[str, Sequence[str], None] = "h4_approval_consumed_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("monthly_spend_cap_usd", sa.Numeric(14, 4), nullable=True))
    op.create_check_constraint("ck_companies_spend_cap_positive", "companies",
                               "monthly_spend_cap_usd IS NULL OR monthly_spend_cap_usd > 0")


def downgrade() -> None:
    op.drop_constraint("ck_companies_spend_cap_positive", "companies", type_="check")
    op.drop_column("companies", "monthly_spend_cap_usd")

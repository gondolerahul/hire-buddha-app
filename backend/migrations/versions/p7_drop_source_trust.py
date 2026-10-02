"""Drop source_trust_scores: TrustLearner is deleted (PC-11, D20)

Revision ID: p7_drop_source_trust
Revises: p6_run_subjects
Create Date: 2026-10-03

The in-tenant source trust learner had no writer and no reader: nothing
called ``TrustLearner``, and the flag that would have gated it was never
read. Wiring it means changing memory retrieval (register 08, deferred by
the product owner), so it is deleted with its table. Nothing ever wrote a
row; the downgrade recreates the empty table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "p7_drop_source_trust"
down_revision: Union[str, Sequence[str], None] = "p6_run_subjects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_source_trust_company", table_name="source_trust_scores")
    op.drop_table("source_trust_scores")


def downgrade() -> None:
    op.create_table(
        "source_trust_scores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("source_key", sa.String(255), nullable=False),
        sa.Column("observations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successes", sa.Float(), nullable=False, server_default="0"),
        sa.Column("prior", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("learned_trust", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("company_id", "source_key", name="uq_source_trust_company_key"),
    )
    op.create_index("ix_source_trust_company", "source_trust_scores", ["company_id"])

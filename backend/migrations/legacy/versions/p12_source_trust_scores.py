"""Phase 12 (`07` §3): learned per-source provenance trust scores.

Adds ``source_trust_scores`` — the host-side table backing the in-tenant
trust-learning loop (``src/ai/memory/trust_learning.py``). One row per
(company, source identity) accumulates outcome observations and a smoothed
learned trust score; reads blend it with the static per-source-type prior from
the CORTEX ``Provenance`` model.

Revision ID: p12_source_trust_scores
Revises: p12_retire_reasoning_modes
Create Date: 2026-06-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "p12_source_trust_scores"  # 24 chars — under the 32-char cap
down_revision = "p12_retire_reasoning_modes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_trust_scores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True),
                  sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("source_key", sa.String(255), nullable=False),
        sa.Column("observations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successes", sa.Float(), nullable=False, server_default="0"),
        sa.Column("prior", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("learned_trust", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("company_id", "source_key",
                            name="uq_source_trust_company_key"),
    )
    op.create_index("ix_source_trust_company", "source_trust_scores", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_source_trust_company", table_name="source_trust_scores")
    op.drop_table("source_trust_scores")

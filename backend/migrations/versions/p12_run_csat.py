"""Phase 12 (`07` §6, P-O2): first-party CSAT capture on execution runs.

Adds ``csat_score`` (+1 / -1) and ``csat_comment`` to ``execution_runs`` — the
only first-party "was this actually good?" signal, captured after a run
completes. Feeds critic false-pass calibration with ground truth.

Revision ID: p12_run_csat
Revises: p12_source_trust_scores
Create Date: 2026-06-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "p12_run_csat"
down_revision = "p12_source_trust_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("execution_runs", sa.Column("csat_score", sa.Integer(), nullable=True))
    op.add_column("execution_runs", sa.Column("csat_comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("execution_runs", "csat_comment")
    op.drop_column("execution_runs", "csat_score")

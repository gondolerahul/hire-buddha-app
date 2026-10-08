"""A HITL decision is used once (GH-07)

Revision ID: h4_approval_consumed_at
Revises: h2_seal_social_secrets
Create Date: 2026-10-08

A HITL checkpoint no longer holds a worker while a person decides: the run
parks PAUSED, and when it resumes the step's checkpoint finds its approval
again. ``human_approvals.consumed_at`` records that the step acted on the
decision, so the next time the checkpoint fires a person is asked again.
Existing rows were decided by a blocking wait that acted on them at once, so
every decided row is marked consumed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h4_approval_consumed_at"
down_revision: Union[str, Sequence[str], None] = "h2_seal_social_secrets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("human_approvals", sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE human_approvals SET consumed_at = COALESCE(responded_at, requested_at, now()) "
        "WHERE status <> 'PENDING'"
    )


def downgrade() -> None:
    op.drop_column("human_approvals", "consumed_at")

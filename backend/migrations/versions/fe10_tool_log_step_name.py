"""A tool call records the plan step that made it (FE-10)

Revision ID: fe10_tool_log_step_name
Revises: dm18_artifact_campaign_fk
Create Date: 2026-10-01

llm_interaction_logs has step_name; tool_interaction_logs did not, so the run
page could not show which step called which tool — its per-step tool list was
a stub that matched nothing. Existing rows stay NULL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fe10_tool_log_step_name"
down_revision: Union[str, Sequence[str], None] = "dm18_artifact_campaign_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tool_interaction_logs", sa.Column("step_name", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("tool_interaction_logs", "step_name")

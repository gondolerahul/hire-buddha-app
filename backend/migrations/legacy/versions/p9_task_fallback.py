"""A task default may name a fallback integration; routing_mode is gone (LP-08, D25)

Revision ID: p9_task_fallback
Revises: p9_one_app_company
Create Date: 2026-10-03

``model_task_defaults.routing_mode`` ('single' | 'router') was stored, returned
and rendered, and read by nothing: there was no second provider to route to.
It is replaced by ``fallback_integration_id`` — the integration the router
calls when the default's call fails after its retries. Every existing row was
'single', which is what no fallback means.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "p9_task_fallback"
down_revision: Union[str, Sequence[str], None] = "p9_one_app_company"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("model_task_defaults", sa.Column("fallback_integration_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_model_task_defaults_fallback_integration", "model_task_defaults",
                          "integration_registry", ["fallback_integration_id"], ["id"], ondelete="SET NULL")
    op.drop_column("model_task_defaults", "routing_mode")


def downgrade() -> None:
    op.add_column("model_task_defaults", sa.Column("routing_mode", sa.String(20), nullable=False,
                                                   server_default="single"))
    op.drop_constraint("fk_model_task_defaults_fallback_integration", "model_task_defaults", type_="foreignkey")
    op.drop_column("model_task_defaults", "fallback_integration_id")

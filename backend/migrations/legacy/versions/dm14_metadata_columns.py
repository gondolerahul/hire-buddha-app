"""No column is named "metadata": rename it to the attribute each model maps (DM-14)

Revision ID: dm14_metadata_columns
Revises: dm09_log_company_id
Create Date: 2026-10-01

SQLAlchemy reserves ``metadata`` on a declarative class, so these three
columns were mapped under other attribute names. ``Model(metadata=...)`` is
accepted without error, because the class has a ``metadata`` attribute, and
the value is never stored. ``SemanticGraphService.create_edge`` did exactly
that, so no edge kept its metadata. Each column now has the name of the
attribute that maps it:

- ``campaigns.metadata`` → ``campaign_metadata``
- ``campaign_calls.metadata`` → ``call_metadata``
- ``cortex_edges.metadata`` → ``edge_metadata``
"""
from typing import Sequence, Union

from alembic import op

revision: str = "dm14_metadata_columns"
down_revision: Union[str, Sequence[str], None] = "dm09_log_company_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RENAMES = (
    ("campaigns", "campaign_metadata"),
    ("campaign_calls", "call_metadata"),
    ("cortex_edges", "edge_metadata"),
)


def upgrade() -> None:
    for table, column in RENAMES:
        op.alter_column(table, "metadata", new_column_name=column)


def downgrade() -> None:
    for table, column in RENAMES:
        op.alter_column(table, column, new_column_name="metadata")

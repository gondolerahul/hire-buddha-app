"""Tool names are unique per company, not across all tenants (DM-08)

Revision ID: dm08_tool_name_per_company
Revises: bc07_usage_log_sku_nullable
Create Date: 2026-10-01

``tool_registry_entries.name`` had a global unique constraint, while
synthesized tools are written per tenant: the second tenant to synthesize a
tool called, say, ``crm_sync`` got an IntegrityError. The key becomes
``(company_id, name)`` with NULLS NOT DISTINCT (Postgres 15+), so built-in rows
(no company) stay unique by name. The plain index on ``name`` stays for lookups.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "dm08_tool_name_per_company"
down_revision: Union[str, Sequence[str], None] = "bc07_usage_log_sku_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if int(bind.execute(sa.text("SHOW server_version_num")).scalar_one()) < 150000:
        raise RuntimeError("the per-company tool name key needs Postgres 15+ (NULLS NOT DISTINCT)")
    op.execute("ALTER TABLE tool_registry_entries DROP CONSTRAINT IF EXISTS tool_registry_entries_name_key")
    op.create_index("ix_tool_registry_entries_name", "tool_registry_entries", ["name"], if_not_exists=True)
    op.create_unique_constraint(
        "uq_tool_registry_company_name", "tool_registry_entries", ["company_id", "name"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_constraint("uq_tool_registry_company_name", "tool_registry_entries", type_="unique")
    op.create_unique_constraint("tool_registry_entries_name_key", "tool_registry_entries", ["name"])

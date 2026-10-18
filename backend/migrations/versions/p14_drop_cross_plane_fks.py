"""No foreign keys between control and tenant tables (Phase 14 WS2 2.3)

Revision ID: p14_drop_cross_plane_fks
Revises: p14_tenant_directory
Create Date: 2026-10-17

A tenant's tables move to a database of their own, which cannot hold a foreign
key to a control table — nor a control table one to it (tech spec §5.3 rule 2).
The 38 keys between the two planes are dropped here: the 34 the models
declared, and four the chain gave ``cortex_trees`` (whose package declares
none). Their columns stay as plain UUIDs (``bases.cross_plane_references()``).
What the keys did is now done by the services: ids that come from a request
are checked where they are written, and the ``ON DELETE`` actions (two
``CASCADE``, four ``SET NULL``) are done by the code that deletes those rows.

Upgrade finds each key by its table, column and referred table, not by name,
so a database whose keys were named differently is handled too. Downgrade
restores them with the names and actions the migration chain gave them; it
fails if rows written since then name a row this database does not have
(e.g. a number assigned to an agent that lives in a tenant database).
"""
from typing import Optional, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p14_drop_cross_plane_fks"
down_revision: Union[str, Sequence[str], None] = "p14_tenant_directory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, referred table, ON DELETE) — each refers to ``<referred>.id``.
CROSS_PLANE_KEYS: tuple[tuple[str, str, str, Optional[str]], ...] = (
    ("artifacts", "company_id", "companies", None),
    ("call_logs", "company_id", "companies", None),
    ("campaign_assignees", "user_id", "users", "CASCADE"),
    ("campaigns", "company_id", "companies", None),
    ("campaigns", "created_by", "users", None),
    ("contact_uploads", "company_id", "companies", None),
    ("contact_uploads", "uploaded_by", "users", None),
    ("conversation_history", "company_id", "companies", None),
    ("cortex_trees", "app_id", "companies", "SET NULL"),
    ("cortex_trees", "company_id", "companies", None),
    ("cortex_trees", "partner_id", "companies", "SET NULL"),
    ("cortex_trees", "user_id", "users", None),
    ("credit_holds", "run_id", "execution_runs", "CASCADE"),
    ("documents", "company_id", "companies", None),
    ("email_connections", "company_id", "companies", None),
    ("entity_versions", "company_id", "companies", None),
    ("entity_versions", "created_by", "users", None),
    ("entity_versions", "published_by", "users", None),
    ("execution_runs", "company_id", "companies", None),
    ("execution_runs", "user_id", "users", None),
    ("hierarchical_entities", "company_id", "companies", None),
    ("hierarchical_entities", "created_by", "users", "SET NULL"),
    ("human_approvals", "responded_by", "users", None),
    ("lead_queue", "company_id", "companies", None),
    ("mobile_call_attempts", "company_id", "companies", None),
    ("mobile_call_attempts", "device_id", "user_devices", None),
    ("mobile_call_attempts", "user_id", "users", None),
    ("mobile_campaign_runs", "company_id", "companies", None),
    ("mobile_campaign_runs", "device_id", "user_devices", None),
    ("mobile_campaign_runs", "user_id", "users", None),
    ("mobile_client_logs", "company_id", "companies", None),
    ("mobile_client_logs", "user_id", "users", None),
    ("phone_numbers", "agent_id", "hierarchical_entities", None),
    ("social_connections", "company_id", "companies", None),
    ("usage_logs", "run_id", "execution_runs", None),
    ("voice_sessions", "company_id", "companies", None),
    ("webhook_endpoints", "entity_id", "hierarchical_entities", "SET NULL"),
    ("whatsapp_sessions", "company_id", "companies", None),
)

# Names the chain gave that are not Postgres's ``<table>_<column>_fkey``.
_NAMES = {
    ("hierarchical_entities", "created_by"): "fk_entities_created_by",
    ("cortex_trees", "app_id"): "fk_cortex_trees_app_id",
    ("cortex_trees", "partner_id"): "fk_cortex_trees_partner_id",
}

_FIND = sa.text("""
SELECT c.conname
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
WHERE c.contype = 'f'
  AND c.conrelid = to_regclass(:table)
  AND c.confrelid = to_regclass(:referred)
  AND cardinality(c.conkey) = 1
  AND a.attname = :column
""")


def upgrade() -> None:
    bind = op.get_bind()
    for table, column, referred, _ in CROSS_PLANE_KEYS:
        names = bind.execute(_FIND, {"table": table, "column": column, "referred": referred}).scalars().all()
        for name in names:
            op.drop_constraint(name, table, type_="foreignkey")


def downgrade() -> None:
    for table, column, referred, ondelete in CROSS_PLANE_KEYS:
        op.create_foreign_key(_NAMES.get((table, column), f"{table}_{column}_fkey"),
                              table, referred, [column], ["id"], ondelete=ondelete)

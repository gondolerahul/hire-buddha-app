"""The schema catches up with the ORM (DM-21, DM-01, DM-02)

Revision ID: dm21_schema_catch_up
Revises: mem1a2b3c4d5
Create Date: 2026-09-30

A database built by ``alembic upgrade head`` lacked what the running code
reads and writes: two tables and eleven columns had only ever been created by
hand (``create_all``, a standalone script, or psql). This revision creates them,
so a fresh database matches the ORM; ``tests/integration/test_schema_census.py``
checks that it stays that way.

- ``subscription_tiers`` (DM-01), seeded with the three plans the wallet page
  falls back to when the table is empty.
- ``phone_numbers`` (DM-02), which ``migrations/merge_phone_tables.py`` created
  outside the chain. Its data step is carried over: rows of the two legacy
  tables it replaced (``phone_number_pool``, ``customer_phone_numbers``) are
  copied in, and the legacy tables dropped. Backups the script made
  (``*_old``) are left alone.
- ``campaign_calls``: the six rep-disposition columns.
- ``execution_runs.billed_amount``, ``llm_interaction_logs.step_name``.
- ``voice_sessions`` / ``whatsapp_sessions``: ``metadata`` → ``session_metadata``;
  ``conversation_history``: ``metadata`` → ``message_metadata`` — the names the
  ORM maps. Where a hand-patched database already has both, the old column's
  values fill the new one's gaps and the old column is dropped.

Every step checks the live schema first: databases patched by hand already
have some of this, and must reach the same end state.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "dm21_schema_catch_up"
down_revision: Union[str, Sequence[str], None] = "mem1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (tier_level, name, monthly_fee, bonus_pct) — the wallet page's FALLBACK_PLANS.
DEFAULT_TIERS = [(1, "Starter", 29, 20), (2, "Growth", 79, 30), (3, "Scale", 199, 40)]

RENAMED_METADATA = [
    ("voice_sessions", "session_metadata"),
    ("whatsapp_sessions", "session_metadata"),
    ("conversation_history", "message_metadata"),
]


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _add_missing(table: str, *columns: sa.Column) -> None:
    have = _columns(table)
    for column in columns:
        if column.name not in have:
            op.add_column(table, column)


def _subscription_tiers() -> None:
    if "subscription_tiers" not in _tables():
        op.create_table(
            "subscription_tiers",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("name", sa.String(50), nullable=False),
            sa.Column("tier_level", sa.Integer(), nullable=False, unique=True),
            sa.Column("monthly_fee", sa.Numeric(10, 2), nullable=False),
            sa.Column("bonus_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        )
    empty = op.get_bind().execute(sa.text("SELECT NOT EXISTS (SELECT 1 FROM subscription_tiers)")).scalar()
    if empty:
        # Every column explicitly: a table made by create_all has no server defaults.
        for level, name, fee, bonus in DEFAULT_TIERS:
            op.execute(sa.text(
                "INSERT INTO subscription_tiers "
                "(id, name, tier_level, monthly_fee, bonus_pct, is_active, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :name, :level, :fee, :bonus, true, now(), now())"
            ).bindparams(name=name, level=level, fee=fee, bonus=bonus))


def _phone_numbers() -> None:
    tables = _tables()
    if "phone_numbers" not in tables:
        op.create_table(
            "phone_numbers",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("phone_number", sa.String(20), nullable=False, unique=True),
            sa.Column("provider", sa.String(20), nullable=False),
            sa.Column("country_code", sa.String(5), nullable=False, server_default="+91"),
            sa.Column("status", sa.String(20), nullable=False, server_default="available"),
            sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=True),
            sa.Column("claimed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("claimed_at", sa.DateTime(), nullable=True),
            sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("hierarchical_entities.id"), nullable=True),
            sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("customer_name", sa.String(255), nullable=True),
            sa.Column("customer_metadata", postgresql.JSONB(), nullable=True),
            sa.Column("assigned_at", sa.DateTime(), nullable=True),
            sa.Column("provider_sid", sa.String(100), nullable=True),
            sa.Column("capabilities", postgresql.JSONB(), nullable=True),
            sa.Column("monthly_cost_usd", sa.Numeric(10, 4), nullable=True),
            sa.Column("label", sa.String(100), nullable=True),
            sa.Column("notes", sa.String(500), nullable=True),
            sa.Column("added_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
        )
        for name, column in [("phone", "phone_number"), ("status", "status"), ("company", "company_id"),
                             ("agent", "agent_id"), ("customer", "customer_id"), ("provider", "provider")]:
            op.create_index(f"idx_phone_numbers_{name}", "phone_numbers", [column])

    if "phone_number_pool" in tables:
        op.execute("""
            INSERT INTO phone_numbers (
                id, phone_number, provider, country_code, status,
                company_id, claimed_by_user_id, claimed_at,
                provider_sid, capabilities, monthly_cost_usd, label, notes,
                added_by_user_id, is_active, created_at, updated_at)
            SELECT id, phone_number, provider, country_code, COALESCE(status, 'available'),
                   claimed_by_company_id, claimed_by_user_id, claimed_at,
                   provider_sid, capabilities, monthly_cost_usd, label, notes,
                   added_by_user_id, true, created_at, updated_at
            FROM phone_number_pool
            ON CONFLICT (phone_number) DO NOTHING
        """)
        op.drop_table("phone_number_pool")

    if "customer_phone_numbers" in tables:
        # An assignment to a number already in the pool updates that row; any
        # other assignment becomes a new, assigned row.
        op.execute("""
            UPDATE phone_numbers pn
            SET status = 'assigned',
                company_id = COALESCE(pn.company_id, cpn.company_id),
                agent_id = cpn.agent_id,
                customer_id = cpn.customer_id,
                customer_name = cpn.customer_name,
                customer_metadata = cpn.customer_metadata,
                assigned_at = cpn.assigned_at,
                is_active = cpn.is_active
            FROM customer_phone_numbers cpn
            WHERE pn.phone_number IN (cpn.phone_number, LTRIM(cpn.phone_number, '+'))
        """)
        op.execute("""
            INSERT INTO phone_numbers (
                id, phone_number, provider, country_code, status,
                company_id, agent_id, customer_id, customer_name,
                customer_metadata, assigned_at, is_active, created_at, updated_at)
            SELECT cpn.id, LTRIM(cpn.phone_number, '+'), cpn.provider,
                   CASE WHEN starts_with(cpn.phone_number, '+1') THEN '+1'
                        WHEN starts_with(cpn.phone_number, '+44') THEN '+44'
                        ELSE '+91' END,
                   'assigned', cpn.company_id, cpn.agent_id, cpn.customer_id, cpn.customer_name,
                   cpn.customer_metadata, cpn.assigned_at, cpn.is_active, cpn.assigned_at, cpn.assigned_at
            FROM customer_phone_numbers cpn
            WHERE NOT EXISTS (
                SELECT 1 FROM phone_numbers pn
                WHERE pn.phone_number IN (cpn.phone_number, LTRIM(cpn.phone_number, '+')))
            ON CONFLICT (phone_number) DO NOTHING
        """)
        op.drop_table("customer_phone_numbers")


def _renamed_metadata_columns() -> None:
    for table, new in RENAMED_METADATA:
        have = _columns(table)
        if "metadata" not in have:
            continue
        if new not in have:
            op.alter_column(table, "metadata", new_column_name=new)
            continue
        op.execute(f'UPDATE {table} SET {new} = "metadata" WHERE {new} IS NULL AND "metadata" IS NOT NULL')
        op.drop_column(table, "metadata")


def upgrade() -> None:
    _subscription_tiers()
    _phone_numbers()
    _add_missing(
        "campaign_calls",
        sa.Column("rep_disposition", sa.String(30), nullable=True),
        sa.Column("rep_note", sa.Text(), nullable=True),
        sa.Column("rep_dispositioned_at", sa.DateTime(), nullable=True),
        sa.Column("rep_dispositioned_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disposition_source", sa.String(10), nullable=True),
        sa.Column("callback_at", sa.DateTime(), nullable=True),
    )
    _add_missing("execution_runs", sa.Column("billed_amount", sa.Numeric(14, 6), nullable=True))
    _add_missing("llm_interaction_logs", sa.Column("step_name", sa.String(), nullable=True))
    _renamed_metadata_columns()


def downgrade() -> None:
    # Only the renames are undone. The tables and columns were already in use on
    # hand-built databases before this revision; dropping them would lose data.
    for table, new in RENAMED_METADATA:
        if new in _columns(table) and "metadata" not in _columns(table):
            op.alter_column(table, new, new_column_name="metadata")

"""Automation tables (Phase 14 WS3 3.2; decision D47)

Revision ID: p14_automation
Revises: p14_drop_cross_plane_fks
Create Date: 2026-10-18

Tenant tables (a business's own database; ``public`` while the shared
database serves single mode): ``events`` (the outbox: every accepted event
once, by ``dedupe_key``), ``triggers``, ``trigger_firings`` (one decision per
trigger per event), ``waits``. Control tables: ``time_index`` (what is due
when, across tenants) and ``automation_settings`` (D47: each business's
limits — none by default — and whether its automation runs; one platform row).
``execution_runs`` gains the trigger, event, correlation and chain depth that
started it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p14_automation"
down_revision: Union[str, Sequence[str], None] = "p14_drop_cross_plane_fks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
EMPTY = sa.text("'{}'::jsonb")


def _in(column: str, values: tuple) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text()),
        sa.Column("time", TS, nullable=False),
        sa.Column("received_at", TS, nullable=False, server_default=NOW),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("trust", sa.Text(), nullable=False),
        sa.Column("causation_id", UUID),
        sa.Column("correlation_id", UUID),
        sa.Column("chain_depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data", JSONB, nullable=False, server_default=EMPTY),
        sa.Column("data_ref", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="received"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("routed_at", TS),
        sa.CheckConstraint(_in("status", ("received", "routed", "parked", "dead")), name="ck_events_status"),
        sa.CheckConstraint(_in("trust", ("verified", "unverified", "internal")), name="ck_events_trust"),
        sa.UniqueConstraint("company_id", "dedupe_key", name="uq_events_company_dedupe"),
    )
    op.create_index("ix_events_pending", "events", ["status", "received_at"],
                    postgresql_where=sa.text("status IN ('received', 'parked')"))
    op.create_index("ix_events_type_time", "events", ["type", "time"])

    op.create_table(
        "triggers",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("entity_id", UUID, sa.ForeignKey("hierarchical_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_version_id", UUID),
        sa.Column("input_template", JSONB, nullable=False, server_default=EMPTY),
        sa.Column("event_type", sa.Text()),
        sa.Column("filter", JSONB),
        sa.Column("cron", sa.Text()),
        sa.Column("timezone", sa.Text()),
        sa.Column("run_at", TS),
        sa.Column("until_at", TS),
        sa.Column("max_firings", sa.Integer()),
        sa.Column("catch_up", sa.Text()),
        sa.Column("overlap", sa.Text()),
        sa.Column("max_concurrency", sa.Integer()),
        sa.Column("rate_per_hour", sa.Integer()),
        sa.Column("condition", JSONB),
        sa.Column("scope", sa.Text()),
        sa.Column("created_by_kind", sa.Text(), nullable=False),
        sa.Column("created_by_id", UUID),
        sa.Column("created_by_run_id", UUID),
        sa.Column("next_fire_at", TS),
        sa.Column("last_fired_at", TS),
        sa.Column("firings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paused_reason", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint(_in("kind", ("schedule", "timer", "event", "data", "condition", "manual")),
                           name="ck_triggers_kind"),
        sa.CheckConstraint("catch_up IS NULL OR " + _in("catch_up", ("skip", "once", "all")),
                           name="ck_triggers_catch_up"),
        sa.CheckConstraint("overlap IS NULL OR " + _in("overlap", ("skip", "queue", "allow")),
                           name="ck_triggers_overlap"),
        sa.CheckConstraint(_in("created_by_kind", ("user", "agent", "system")), name="ck_triggers_created_by_kind"),
    )
    op.create_index("ix_triggers_event_type", "triggers", ["event_type"], postgresql_where=sa.text("enabled"))
    op.create_index("ix_triggers_entity_id", "triggers", ["entity_id"])

    op.create_table(
        "trigger_firings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("trigger_id", UUID, sa.ForeignKey("triggers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", UUID, sa.ForeignKey("events.id")),
        sa.Column("run_id", UUID),
        sa.Column("decided_at", TS, nullable=False, server_default=NOW),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.CheckConstraint(_in("outcome", (
            "started", "queued", "skipped_overlap", "skipped_rate", "skipped_chain_depth", "skipped_condition_false",
            "skipped_missed", "blocked_budget", "blocked_paused", "blocked_policy", "failed")),
            name="ck_trigger_firings_outcome"),
        sa.UniqueConstraint("trigger_id", "event_id", name="uq_trigger_firings_trigger_event"),
    )
    op.create_index("ix_trigger_firings_trigger_decided", "trigger_firings", ["trigger_id", "decided_at"])
    op.create_index("ix_trigger_firings_event", "trigger_firings", ["event_id"])

    op.create_table(
        "waits",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("step_ref", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text()),
        sa.Column("match", JSONB),
        sa.Column("deadline_at", TS),
        sa.Column("status", sa.Text(), nullable=False, server_default="waiting"),
        sa.Column("satisfied_by_event_id", UUID),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint(_in("status", ("waiting", "satisfied", "expired", "cancelled")), name="ck_waits_status"),
    )
    op.create_index("ix_waits_waiting_type", "waits", ["event_type"], postgresql_where=sa.text("status = 'waiting'"))
    op.create_index("ix_waits_run", "waits", ["run_id"])

    op.create_table(
        "time_index",
        sa.Column("company_id", UUID, primary_key=True),
        sa.Column("ref_kind", sa.Text(), primary_key=True),
        sa.Column("ref_id", UUID, primary_key=True),
        sa.Column("due_at", TS, nullable=False),
        sa.Column("lease_owner", sa.Text()),
        sa.Column("lease_until", TS),
        sa.CheckConstraint(_in("ref_kind", ("trigger", "wait", "connection_refresh", "scratch_cleanup")),
                           name="ck_time_index_ref_kind"),
    )
    op.create_index("ix_time_index_due_at", "time_index", ["due_at"])

    op.create_table(
        "automation_settings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id")),
        sa.Column("limits", JSONB, nullable=False, server_default=EMPTY),
        sa.Column("automation_state", sa.Text(), nullable=False, server_default="running"),
        sa.Column("paused_reason", sa.Text()),
        sa.Column("updated_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint(_in("automation_state", ("running", "paused")), name="ck_automation_settings_state"),
    )
    op.create_index("uq_automation_settings_company", "automation_settings", ["company_id"], unique=True,
                    postgresql_where=sa.text("company_id IS NOT NULL"))
    op.create_index("uq_automation_settings_platform", "automation_settings", [sa.text("(company_id IS NULL)")],
                    unique=True, postgresql_where=sa.text("company_id IS NULL"))

    op.add_column("execution_runs", sa.Column("trigger_id", UUID, nullable=True))
    op.add_column("execution_runs", sa.Column("event_id", UUID, nullable=True))
    op.add_column("execution_runs", sa.Column("correlation_id", UUID, nullable=True))
    op.add_column("execution_runs", sa.Column("chain_depth", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_execution_runs_trigger_id", "execution_runs", ["trigger_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_runs_trigger_id", table_name="execution_runs")
    for column in ("chain_depth", "correlation_id", "event_id", "trigger_id"):
        op.drop_column("execution_runs", column)
    op.drop_table("automation_settings")
    op.drop_table("time_index")
    op.drop_table("waits")
    op.drop_table("trigger_firings")
    op.drop_table("triggers")
    op.drop_table("events")

"""Every host timestamp column is timestamptz; values are read as UTC (DM-12)

Revision ID: dm12_timestamptz
Revises: dm13_jsonb
Create Date: 2026-10-01

Every ``DateTime`` column was ``timestamp without time zone``. UTC was a
convention held up by ``datetime.utcnow`` defaults, and three call sites had
already broken it with local time. ``now()`` written into a naive column
follows the session time zone too. The 111 host columns become
``timestamptz``, with each stored value read as UTC (``AT TIME ZONE 'UTC'``),
which is what the code wrote.

Python keeps seeing naive UTC datetimes. ``src/common/database.py`` pins each
connection's time zone to UTC and converts at the driver, so no caller
changes. The CORTEX tables (``cortex_trees``, ``cortex_nodes``,
``cortex_edges``) belong to the hb-cortex-memory package and stay as they
are. ``kpi_daily_rollup`` reads ``execution_runs.completed_at``, so it is
rebuilt, bucketing days ``AT TIME ZONE 'UTC'``.
"""
from typing import Sequence, Union

from alembic import op

from migrations.kpi_rollup_view import CREATE_VIEW, CREATE_VIEW_UTC, rebuilt

revision: str = "dm12_timestamptz"
down_revision: Union[str, Sequence[str], None] = "dm13_jsonb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = {
    "artifacts": "created_at",
    "billing_config": "created_at updated_at",
    "billing_events": "created_at updated_at",
    "call_content": "created_at",
    "call_logs": "created_at",
    "campaign_assignees": "assigned_at",
    "campaign_calls": "callback_at called_at completed_at created_at lease_expires_at rep_dispositioned_at scheduled_at",
    "campaigns": "completed_at created_at scheduled_end scheduled_start started_at updated_at",
    "companies": "created_at updated_at",
    "contact_uploads": "consumed_at created_at expires_at",
    "conversation_history": "timestamp",
    "credit_holds": "created_at released_at",
    "credit_wallets": "daily_expires_at sub_credits_expire_at updated_at wallet_expires_at",
    "documents": "created_at updated_at",
    "email_connections": "created_at last_connected_at updated_at",
    "execution_runs": "completed_at created_at started_at",
    "execution_trace_events": "created_at ended_at started_at",
    "feature_flags": "created_at updated_at",
    "hierarchical_entities": "created_at deleted_at updated_at",
    "human_approvals": "requested_at responded_at",
    "integration_registry": "created_at updated_at",
    "lead_queue": "created_at processed_at updated_at",
    "llm_interaction_logs": "created_at",
    "mobile_call_attempts": "ai_answered_at ai_ready_at created_at ended_at expires_at lead_answered_at lead_dialed_at merged_at updated_at",
    "mobile_call_events": "device_ts received_at",
    "mobile_campaign_runs": "ended_at started_at",
    "mobile_client_logs": "device_ts received_at",
    "model_task_defaults": "created_at updated_at",
    "payment_transactions": "created_at updated_at",
    "phone_numbers": "assigned_at claimed_at created_at updated_at",
    "refresh_tokens": "created_at expires_at",
    "social_connections": "created_at last_used_at token_expires_at updated_at",
    "source_trust_scores": "updated_at",
    "subscription_tiers": "created_at updated_at",
    "subscriptions": "cancelled_at created_at next_billing_date updated_at",
    "tool_interaction_logs": "created_at",
    "tool_registry_entries": "created_at updated_at",
    "usage_logs": "timestamp",
    "user_devices": "created_at last_seen_at updated_at verification_expires_at verified_at",
    "users": "created_at updated_at",
    "voice_sessions": "created_at ended_at started_at",
    "whatsapp_sessions": "created_at last_message_at session_window_expires started_at",
}


def _alter(to: str) -> None:
    for table, names in COLUMNS.items():
        changes = ", ".join(f"ALTER COLUMN {c} TYPE {to} USING {c} AT TIME ZONE 'UTC'" for c in names.split())
        op.execute(f"ALTER TABLE {table} {changes}")


def upgrade() -> None:
    with rebuilt(CREATE_VIEW_UTC):
        _alter("timestamptz")


def downgrade() -> None:
    with rebuilt(CREATE_VIEW):
        _alter("timestamp")

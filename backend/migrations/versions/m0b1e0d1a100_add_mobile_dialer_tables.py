"""add_mobile_dialer_tables

Revision ID: m0b1e0d1a100
Revises: z9b0c1d2e3f4
Create Date: 2026-09-17

Mobile dialer app (docs/mobile-dialer-app): user_devices, contact_uploads,
campaign_assignees, mobile_campaign_runs, mobile_call_attempts,
mobile_call_events; campaigns.execution_mode/contact_upload_id; campaign_calls
lease columns.

The DDL lives in db-scripts/mobile_dialer_001.sql (idempotent) so the same
statements can be applied with psql on databases whose alembic_version is not
on this repo's history.
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op


revision: str = 'm0b1e0d1a100'
down_revision: Union[str, Sequence[str], None] = 'z9b0c1d2e3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_FILE = Path(__file__).resolve().parents[2] / "db-scripts" / "mobile_dialer_001.sql"


def upgrade() -> None:
    sql = SQL_FILE.read_text()
    # Alembic already runs inside a transaction.
    sql = sql.replace("BEGIN;", "").replace("COMMIT;", "")
    op.execute(sql)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS mobile_call_events;
        DROP TABLE IF EXISTS mobile_call_attempts;
        DROP TABLE IF EXISTS mobile_campaign_runs;
        DROP TABLE IF EXISTS campaign_assignees;
        DROP TABLE IF EXISTS contact_uploads;
        DROP TABLE IF EXISTS user_devices;
        DROP INDEX IF EXISTS ix_campaign_calls_lease;
        ALTER TABLE campaign_calls DROP COLUMN IF EXISTS lease_expires_at;
        ALTER TABLE campaign_calls DROP COLUMN IF EXISTS leased_by_device_id;
        ALTER TABLE campaign_calls DROP COLUMN IF EXISTS leased_by_user_id;
        ALTER TABLE campaigns DROP COLUMN IF EXISTS contact_upload_id;
        ALTER TABLE campaigns DROP COLUMN IF EXISTS execution_mode;
    """)

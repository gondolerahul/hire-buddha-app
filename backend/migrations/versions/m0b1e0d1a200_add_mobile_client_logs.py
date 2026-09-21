"""add_mobile_client_logs

Revision ID: m0b1e0d1a200
Revises: m0b1e0d1a100
Create Date: 2026-09-21

Diagnostic logs shipped by the Android dialer app. DDL lives in
db-scripts/mobile_dialer_002_logs.sql so it can also be applied with psql on
databases whose alembic_version is not on this repo's history.
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op


revision: str = 'm0b1e0d1a200'
down_revision: Union[str, Sequence[str], None] = 'm0b1e0d1a100'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_FILE = Path(__file__).resolve().parents[2] / "db-scripts" / "mobile_dialer_002_logs.sql"


def upgrade() -> None:
    sql = SQL_FILE.read_text().replace("BEGIN;", "").replace("COMMIT;", "")
    op.execute(sql)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mobile_client_logs;")

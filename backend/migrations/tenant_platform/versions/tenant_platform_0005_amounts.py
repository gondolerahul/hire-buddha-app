"""exact amounts on the tenant plane (Phase 15 T1-5)

Revision ID: tenant_platform_0005_amounts
Revises: tenant_platform_0004_kpi_refresh
Create Date: 2026-10-23

A run's cost was ``NUMERIC(10,4)`` and settlement charged it: every run was
rounded to 4 decimals before it was billed. Runs, model and tool interaction
rows, trace spans, call and chat sessions and call logs now keep amounts at
``NUMERIC(24,10)``. ``kpi_daily_rollup`` reads ``execution_runs.total_cost_usd``,
so it is dropped and rebuilt around the change (``kpi_rollup_view.rebuilt``).

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.kpi_rollup_view import CREATE_VIEW_UTC, rebuilt


# revision identifiers, used by Alembic.
revision: str = 'tenant_platform_0005_amounts'
down_revision: Union[str, Sequence[str], None] = 'tenant_platform_0004_kpi_refresh'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXACT = sa.Numeric(precision=24, scale=10)

# table → [(column, type before, nullable)]. tests/integration/test_migration_trees.py reads a
# revision's COLUMNS to build a database as the models made it before the change.
COLUMNS = {
    'execution_runs': [('total_cost_usd', sa.Numeric(10, 4), True), ('billed_amount', sa.Numeric(14, 6), True)],
    'llm_interaction_logs': [('cost_usd', sa.Numeric(10, 6), True)],
    'execution_trace_events': [('cost_usd', sa.Numeric(12, 6), True)],
    'voice_sessions': [('total_cost_usd', sa.Numeric(10, 4), False)],
    'whatsapp_sessions': [('total_cost_usd', sa.Numeric(10, 4), False)],
    'call_logs': [('call_cost_usd', sa.Numeric(10, 6), True)],
}


def upgrade() -> None:
    """Upgrade schema."""
    with rebuilt(CREATE_VIEW_UTC):
        for table, columns in COLUMNS.items():
            for column, before, nullable in columns:
                op.alter_column(table, column, type_=EXACT, existing_type=before, existing_nullable=nullable)


def downgrade() -> None:
    """Downgrade schema."""
    with rebuilt(CREATE_VIEW_UTC):
        for table, columns in COLUMNS.items():
            for column, before, nullable in columns:
                op.alter_column(table, column, type_=before, existing_type=EXACT, existing_nullable=nullable)

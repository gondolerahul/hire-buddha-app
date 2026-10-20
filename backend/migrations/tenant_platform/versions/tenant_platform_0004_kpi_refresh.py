"""the KPI rollup refreshed by its owner's function

Revision ID: tenant_platform_0004_kpi_refresh
Revises: tenant_platform_0003_apps
Create Date: 2026-10-20

PostgreSQL 16 lets only a materialized view's owner refresh it, and the
workers (hb_runtime) do not own kpi_daily_rollup: the migrator does on the
control server, the DDL role in a tenant database (Phase 14 M2). The hourly
kpi_rollup_refresh failed on Azure with "must be owner". This function runs
as its owner (SECURITY DEFINER, its search_path fixed when it is made: the
tree's schema) and only hb_runtime (and the owner) may call it.

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'tenant_platform_0004_kpi_refresh'
down_revision: Union[str, Sequence[str], None] = 'tenant_platform_0003_apps'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
CREATE OR REPLACE FUNCTION refresh_kpi_daily_rollup(concurrent boolean DEFAULT true) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path FROM CURRENT AS $$
BEGIN
  IF concurrent THEN
    REFRESH MATERIALIZED VIEW CONCURRENTLY kpi_daily_rollup;
  ELSE
    REFRESH MATERIALIZED VIEW kpi_daily_rollup;
  END IF;
END
$$""")
    op.execute("REVOKE ALL ON FUNCTION refresh_kpi_daily_rollup(boolean) FROM PUBLIC")
    op.execute("""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hb_runtime') THEN
    GRANT EXECUTE ON FUNCTION refresh_kpi_daily_rollup(boolean) TO hb_runtime;
  END IF;
END
$$""")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP FUNCTION IF EXISTS refresh_kpi_daily_rollup(boolean)")

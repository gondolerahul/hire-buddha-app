"""Phase 11 Track 9 — KPI daily rollup materialised view.

Pre-aggregates per-(day, company, primary_tag) counts and cost into
``kpi_daily_rollup`` so the Track 9 dashboards (Grafana / Metabase /
admin endpoints) can serve aggregates without touching ``execution_runs``
directly. Refreshed hourly by ``core/arq_jobs.kpi_rollup_refresh``.

The unique index is what allows ``REFRESH MATERIALIZED VIEW
CONCURRENTLY`` — the index covers the natural key.

Revision ID: p11t09_kpi_rollup
Revises: p11t08_usage_attr
Create Date: 2026-05-27
"""
from alembic import op


revision = "p11t09_kpi_rollup"
down_revision = "p11t08_usage_attr"
branch_labels = None
depends_on = None


_CREATE_VIEW_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS kpi_daily_rollup AS
SELECT
    date_trunc('day', er.completed_at) AS day,
    er.company_id,
    COALESCE(
        (e.tags::jsonb)->>0,
        'untagged'
    ) AS primary_tag,
    COUNT(*) AS runs_total,
    SUM(CASE WHEN er.status = 'COMPLETED' THEN 1 ELSE 0 END) AS runs_completed,
    SUM(CASE WHEN er.status = 'FAILED'    THEN 1 ELSE 0 END) AS runs_failed,
    SUM(CASE WHEN er.status = 'PAUSED'    THEN 1 ELSE 0 END) AS runs_paused,
    COALESCE(SUM(er.total_cost_usd), 0)::numeric(18, 6) AS cost_usd,
    COALESCE(SUM(er.total_tokens), 0) AS tokens
FROM execution_runs er
JOIN hierarchical_entities e ON e.id = er.entity_id
WHERE er.completed_at IS NOT NULL
GROUP BY 1, 2, 3
"""

_CREATE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS kpi_daily_rollup_uniq
    ON kpi_daily_rollup(day, company_id, primary_tag)
"""

_DROP_INDEX_SQL = "DROP INDEX IF EXISTS kpi_daily_rollup_uniq"
_DROP_VIEW_SQL = "DROP MATERIALIZED VIEW IF EXISTS kpi_daily_rollup"


def upgrade() -> None:
    op.execute(_CREATE_VIEW_SQL)
    op.execute(_CREATE_INDEX_SQL)


def downgrade() -> None:
    op.execute(_DROP_INDEX_SQL)
    op.execute(_DROP_VIEW_SQL)

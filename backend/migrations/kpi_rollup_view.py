"""``kpi_daily_rollup``: drop and rebuild it around a column type change.

Postgres refuses ``ALTER COLUMN … TYPE`` on a column a view reads, and the
materialised view reads ``execution_runs`` and ``hierarchical_entities.tags``.
A revision that changes those types wraps its work in :func:`rebuilt`. The
definition is the one ``p11t09_kpi_rollup`` created; rebuilding repopulates
it, as the hourly refresh would.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from alembic import op

CREATE_VIEW = """
CREATE MATERIALIZED VIEW kpi_daily_rollup AS
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
CREATE_INDEX = "CREATE UNIQUE INDEX kpi_daily_rollup_uniq ON kpi_daily_rollup(day, company_id, primary_tag)"


@contextmanager
def rebuilt() -> Iterator[None]:
    """Drop the view, let the caller alter its tables, then create it again."""
    op.execute("DROP MATERIALIZED VIEW IF EXISTS kpi_daily_rollup")
    yield
    op.execute(CREATE_VIEW)
    op.execute(CREATE_INDEX)

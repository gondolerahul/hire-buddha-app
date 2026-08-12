"""Phase 11 Track 14 — kpi_daily_rollup materialised view refresh.

The Track 9 deliverable is a materialised view + an hourly Arq cron
(``kpi_rollup_refresh``). The dashboard endpoint (``GET
/ai/phase11/admin/kpi/runs``) reads from this view. These tests prove:

  1. ``REFRESH MATERIALIZED VIEW CONCURRENTLY kpi_daily_rollup`` works.
  2. The view exposes the columns the dashboard query expects.
  3. The arq job returns a structured success result.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.needs_db


async def _view_exists(db, name: str) -> bool:
    row = (await db.execute(
        text(
            "SELECT 1 FROM pg_matviews WHERE matviewname = :n"
        ),
        {"n": name},
    )).first()
    return row is not None


async def test_kpi_daily_rollup_view_exists(db) -> None:
    assert await _view_exists(db, "kpi_daily_rollup"), \
        "kpi_daily_rollup materialised view missing — p11t09 not applied"


async def test_kpi_daily_rollup_has_expected_columns(db) -> None:
    # information_schema doesn't expose materialised-view columns; use
    # pg_attribute joined against pg_class instead.
    rows = (await db.execute(
        text(
            """
            SELECT a.attname AS column_name
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            WHERE c.relname = 'kpi_daily_rollup'
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """
        )
    )).all()
    cols = {r.column_name for r in rows}
    expected = {
        "day", "company_id",
        "runs_total", "runs_completed", "runs_failed", "runs_paused",
    }
    missing = expected - cols
    assert not missing, f"kpi_daily_rollup missing columns: {missing}"


async def test_dashboard_query_returns_clean_shape(db) -> None:
    """The exact query the dashboard endpoint runs; must execute even
    when the view is empty (fresh DB)."""
    rows = (await db.execute(
        text(
            """
            SELECT day,
                   SUM(runs_total)     AS runs_total,
                   SUM(runs_completed) AS runs_completed,
                   SUM(runs_failed)    AS runs_failed,
                   SUM(runs_paused)    AS runs_paused,
                   COALESCE(
                     SUM(runs_completed)::float / NULLIF(SUM(runs_total), 0),
                     0
                   ) AS goal_hit_rate
            FROM kpi_daily_rollup
            WHERE day >= now() - interval '7 days'
            GROUP BY day
            ORDER BY day
            """
        )
    )).all()
    # rows may be empty on a fresh DB; just assert no exception fired.
    for r in rows:
        assert hasattr(r, "day")
        assert hasattr(r, "runs_total")


async def test_refresh_view_succeeds(db) -> None:
    """Run the exact statement the arq cron uses."""
    # Commit anything outstanding because REFRESH... CONCURRENTLY can't
    # run inside the test's outer SAVEPOINT.
    await db.execute(text(
        "REFRESH MATERIALIZED VIEW CONCURRENTLY kpi_daily_rollup"
    ))


async def test_arq_kpi_rollup_refresh_returns_success(db) -> None:
    """End-to-end run of the cron coroutine. It opens its own session
    so the test session doesn't need to commit."""
    from src.ai.core.arq_jobs import kpi_rollup_refresh
    result = await kpi_rollup_refresh(ctx={})
    assert isinstance(result, dict)
    # Either the concurrent or the plain mode is acceptable.
    assert result.get("refreshed") is True
    assert result.get("mode") in {"concurrent", "plain"}

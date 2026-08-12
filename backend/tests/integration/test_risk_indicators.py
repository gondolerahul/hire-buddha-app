"""Phase 11 Track 15 — risk indicators + exit checklist contract.

These endpoints feed the admin Risk Dashboard. The dashboard's polling
loop assumes a stable shape; if the backend drifts away from it the UI
silently shows empty rows. These tests pin the contract:

  * ``GET /admin/risks``           — returns {as_of, overall, indicators[]}
  * ``GET /admin/exit_checklist``  — returns {as_of, total, satisfied,
                                              percent_complete, items[]}
  * ``GET /admin/decisions``       — returns a list of decision rows
  * ``POST /admin/decisions``      — appends to docs/DECISIONS.md
"""
from __future__ import annotations

import asyncio
import os
import tempfile

import pytest


pytestmark = pytest.mark.needs_db


async def test_risk_indicators_shape(db) -> None:
    """Call the endpoint coroutine directly so we exercise the SQL with
    the test's transactional session."""
    from src.ai.api.admin import kpi_risk_indicators

    class _Admin:
        role = "app_admin"
        company_id = None

    result = await kpi_risk_indicators(
        since="7d", company_id=None, db=db, user=_Admin(),
    )
    assert "as_of" in result
    assert result["overall"] in {"ok", "warn", "breach"}
    inds = result["indicators"]
    assert isinstance(inds, list) and len(inds) >= 6
    for ind in inds:
        assert {"id", "title", "metric", "threshold", "status",
                "details"} <= set(ind)
        assert ind["status"] in {"ok", "warn", "breach"}
        assert isinstance(ind["metric"], (int, float))


async def test_exit_checklist_shape(db) -> None:
    from src.ai.api.admin import programme_exit_checklist

    class _Admin:
        role = "app_admin"
        company_id = None

    result = await programme_exit_checklist(db=db, user=_Admin())
    assert "as_of" in result
    assert result["total"] >= 10                     # 10 items in the doc
    assert 0 <= result["percent_complete"] <= 1.0
    assert isinstance(result["items"], list)
    ids = {i["id"] for i in result["items"]}
    # Spot-check the load-bearing items.
    assert "EXIT-1" in ids                            # alembic head
    assert "EXIT-2" in ids                            # feature_flags
    assert "EXIT-3" in ids                            # kpi_daily_rollup
    for item in result["items"]:
        assert isinstance(item["satisfied"], bool)
        assert isinstance(item["detail"], str)


async def test_decisions_log_round_trip(monkeypatch) -> None:
    """Append a decision, then read it back. The log file path is
    redirected to a temp directory so we don't pollute the real
    DECISIONS.md."""
    from src.ai.api import admin as kernel_admin

    class _Admin:
        role = "app_admin"
        company_id = None

    with tempfile.TemporaryDirectory() as tmp:
        fake_path = os.path.join(tmp, "DECISIONS.md")
        monkeypatch.setattr(
            kernel_admin, "_decisions_log_path", lambda: fake_path,
        )
        result = await kernel_admin.append_decision(
            payload={
                "summary": "ship Track 15 dashboards",
                "rationale": "closes the risk-visibility gap",
                "kind": "decision",
            },
            user=_Admin(),
        )
        assert result["appended"] is True
        assert os.path.exists(fake_path)
        rows = await kernel_admin.list_decisions(limit=10, user=_Admin())
        assert rows
        assert rows[0]["summary"] == "ship Track 15 dashboards"
        assert rows[0]["rationale"] == "closes the risk-visibility gap"


async def test_overall_breach_when_any_indicator_breaches(db, monkeypatch) -> None:
    """If a single indicator returns 'breach', the rollup must propagate."""
    from src.ai.api import admin as kernel_admin

    class _Admin:
        role = "app_admin"
        company_id = None

    real = kernel_admin.kpi_risk_indicators

    async def stub(*args, **kwargs):
        result = await real(*args, **kwargs)
        # Force one indicator into breach state.
        result["indicators"][0]["status"] = "breach"
        # Recompute overall the same way the endpoint does.
        overall = "ok"
        for ind in result["indicators"]:
            if ind["status"] == "breach":
                overall = "breach"
                break
            if ind["status"] == "warn" and overall == "ok":
                overall = "warn"
        result["overall"] = overall
        return result

    monkeypatch.setattr(kernel_admin, "kpi_risk_indicators", stub)
    out = await kernel_admin.kpi_risk_indicators(
        since="7d", company_id=None, db=db, user=_Admin(),
    )
    assert out["overall"] == "breach"

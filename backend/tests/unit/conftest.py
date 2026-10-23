"""Unit-tier fixtures.

Unit tests run without a database, on fake sessions. Since Phase 15 T3-3 every
usage row is rated with its company's billing formula as it is written, and
the formula is read from ``billing_formulas``; a fake session cannot answer.
Unit tests therefore price with the identity formula (billed = cost) — the
resolution and rating themselves are tested against Postgres in
``tests/integration/test_billing_formulas.py``. A unit test that needs another
formula patches ``src.billing.formulas.formula_for`` itself.
"""
from __future__ import annotations

import pytest

from src.billing import formulas


@pytest.fixture(autouse=True)
def _identity_billing_formula(monkeypatch):
    async def _formula_for(db, company_id, *, at=None):
        return formulas.IDENTITY

    async def _formula_for_run(db, company_id, run_id):
        return formulas.IDENTITY

    monkeypatch.setattr(formulas, "formula_for", _formula_for)
    monkeypatch.setattr(formulas, "formula_for_run", _formula_for_run)
    # Modules that imported the resolver by name when they were loaded.
    for module in ("src.billing.rating", "src.ai.governance.governance_service"):
        monkeypatch.setattr(f"{module}.formula_for_run", _formula_for_run, raising=False)

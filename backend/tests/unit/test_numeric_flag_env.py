"""GH-13: a numeric flag can be set from the environment, as a boolean one can.

``get_float`` resolved entity → company → global ``value_json`` → the code
default: no ``AI_FLAG_<KEY>`` tier, so a numeric knob (``bandit.epsilon``,
``planner.n_candidates``) could not be set without a database row. The env
tier sits between the global row and the default, as it does for booleans.
"""
from __future__ import annotations

import logging
from uuid import uuid4

import pytest

from src.ai.core.feature_flags import NUMERIC_DEFAULTS, FeatureFlags


class _RowsDB:
    """``value_json`` per (company, entity) scope, as the table would answer."""

    def __init__(self, rows):
        self.rows = rows

    async def execute(self, statement, params):
        sql = str(statement)
        if "entity_id = :e" in sql:
            key = (params["c"], params["e"])
        elif "company_id = :c" in sql:
            key = (params["c"], None)
        else:
            key = (None, None)
        value = self.rows.get(key)
        return type("R", (), {"first": lambda self: None if value is None else (value,)})()


@pytest.mark.asyncio
async def test_the_environment_sets_a_numeric_flag(monkeypatch):
    monkeypatch.setenv("AI_FLAG_BANDIT_EPSILON", "0.25")
    flags = FeatureFlags(db=None)
    assert await flags.get_float("bandit.epsilon") == 0.25
    assert await flags.resolve_float("bandit.epsilon") == (0.25, "env")


@pytest.mark.asyncio
async def test_a_database_row_still_wins(monkeypatch):
    monkeypatch.setenv("AI_FLAG_PLANNER_N_CANDIDATES", "5")
    company = uuid4()
    flags = FeatureFlags(db=_RowsDB({(str(company), None): 2, (None, None): 4}))
    assert await flags.resolve_float("planner.n_candidates", company_id=company) == (2.0, "company")
    assert await flags.resolve_float("planner.n_candidates", company_id=uuid4()) == (4.0, "global")


@pytest.mark.asyncio
async def test_without_a_row_or_env_the_default(monkeypatch):
    monkeypatch.delenv("AI_FLAG_BANDIT_EPSILON", raising=False)
    flags = FeatureFlags(db=_RowsDB({}))
    assert await flags.resolve_float("bandit.epsilon", company_id=uuid4()) == (
        NUMERIC_DEFAULTS["bandit.epsilon"], "default")
    assert await flags.resolve_float("not.declared", default=7) == (7.0, "caller_default")


@pytest.mark.asyncio
async def test_a_value_that_is_not_a_number_is_ignored_and_said(monkeypatch, caplog):
    monkeypatch.setenv("AI_FLAG_BANDIT_EPSILON", "lots")
    with caplog.at_level(logging.WARNING):
        assert await FeatureFlags(db=None).get_float("bandit.epsilon") == NUMERIC_DEFAULTS["bandit.epsilon"]
    assert "AI_FLAG_BANDIT_EPSILON" in caplog.text

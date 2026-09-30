"""A missing feature_flags table is reported once at startup (DM-03).

Lookups fall back to env vars and code defaults when the table is absent — by
design — which made a database without the table indistinguishable from one
where every flag is at its default. The API now logs it when it starts.
"""
from __future__ import annotations

import logging

import pytest

from src.ai.core import feature_flags


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _Session:
    def __init__(self, present):
        self.present = present

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        return _Result(self.present)


@pytest.mark.asyncio
@pytest.mark.parametrize("present", [True, False])
async def test_startup_check(monkeypatch, caplog, present):
    import src.common.database as database

    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Session(present))
    with caplog.at_level(logging.WARNING, logger=feature_flags.__name__):
        assert await feature_flags.warn_if_table_missing() is present
    assert ("feature_flags table is missing" in caplog.text) is (not present)


def test_the_table_has_a_model():
    from src.common.orm_models import import_all_models

    assert any("feature_flags" in m.tables for m in import_all_models())

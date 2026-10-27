"""The purge walk on a split control database (docs/phase15/13 §6 step 13).

A control database made after the split (Azure prod) has no tenant-plane tables, so the walk must
not follow a cross-plane reference into one: the first deletes on prod failed on ``cortex_trees``.
"""
from __future__ import annotations

import pytest


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _Conn:
    """Only control tables: ``companies`` and ``users``."""

    async def execute(self, statement):
        from src.offboarding import purge

        sql = str(statement)
        if sql == purge._FOREIGN_KEYS_SQL:
            return _Result([("users", "companies", ["company_id"], ["id"], "a")])
        if sql == purge._TABLES_SQL:
            return _Result(["companies", "users"])
        return _Result(["users"])                  # company-scoped tables


@pytest.mark.asyncio
async def test_references_into_absent_tables_are_not_walked():
    from src.common.tenancy.bases import cross_plane_references
    from src.offboarding.purge import _graph

    assert any(ref.table == "cortex_trees" for ref in cross_plane_references())
    foreign_keys, company_scoped = await _graph(_Conn())
    children = {child for refs in foreign_keys.values() for child, *_ in refs}
    assert children == {"users"} and company_scoped == {"users"}

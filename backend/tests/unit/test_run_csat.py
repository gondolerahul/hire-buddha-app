"""Run CSAT capture — Phase 12 `07` §6 (P-O2).

Hermetic: a fake AsyncSession stands in for the DB. Locks in score validation,
the not-finished guard, and that a valid rating is persisted.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.ai.service import AIService


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeDB:
    def __init__(self, run):
        self._run = run
        self.committed = False

    async def execute(self, stmt):  # noqa: ANN001
        return _Result(self._run)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):  # noqa: ANN001
        pass


def _run(status="COMPLETED", company_id=None):
    return SimpleNamespace(id=uuid4(), company_id=company_id or uuid4(),
                           status=status, csat_score=None, csat_comment=None)


@pytest.mark.asyncio
async def test_invalid_score_rejected() -> None:
    svc = AIService(_FakeDB(_run()))
    with pytest.raises(HTTPException) as ei:
        await svc.record_csat(uuid4(), uuid4(), score=5)
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_unfinished_run_rejected() -> None:
    cid = uuid4()
    run = _run(status="RUNNING", company_id=cid)
    svc = AIService(_FakeDB(run))
    with pytest.raises(HTTPException) as ei:
        await svc.record_csat(run.id, cid, score=1)
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_missing_run_404() -> None:
    svc = AIService(_FakeDB(None))
    with pytest.raises(HTTPException) as ei:
        await svc.record_csat(uuid4(), uuid4(), score=1)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_valid_rating_persisted() -> None:
    cid = uuid4()
    run = _run(status="COMPLETED", company_id=cid)
    db = _FakeDB(run)
    svc = AIService(db)
    out = await svc.record_csat(run.id, cid, score=-1, comment="missed the ask")
    assert out.csat_score == -1
    assert out.csat_comment == "missed the ask"
    assert db.committed

"""A burst of runs over the company's quota is a 429 (GH-03, HD17).

Postgres, rolled back, and the local Redis the quota counts in (a fresh
company each time, so the window is its own).
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from tests.harness.infra import infra_unavailable
from tests.integration.test_run_credit_guard import _company

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
async def test_a_burst_over_the_quota_is_refused_with_429(db, monkeypatch):
    from src.ai.orm import ExecutionRun, HierarchicalEntity
    from src.ai.schemas.execution import ExecutionRunCreate
    from src.ai.service import AIService

    async def _no_queue(*_a, **_k):
        return None

    monkeypatch.setattr("src.ai.service.enqueue_job", _no_queue)
    monkeypatch.setattr("src.common.config.settings.RUNS_STARTED_PER_MINUTE", 2)
    try:
        from src.common.redis_client import shared_redis
        await shared_redis().ping()
    except Exception:
        infra_unavailable("Redis is not reachable")

    company = await _company(db, "100")
    entity = HierarchicalEntity(company_id=company, type="AGENT", status="ACTIVE",
                                name=f"gh03-{uuid.uuid4().hex[:6]}")
    db.add(entity)
    await db.flush()
    service = AIService(db)
    start = ExecutionRunCreate(entity_id=entity.id, input_data={"input": "go"})

    await service.trigger_execution(start, company)
    await service.trigger_execution(start, company)
    with pytest.raises(HTTPException) as refused:
        await service.trigger_execution(start, company)
    assert refused.value.status_code == 429 and refused.value.headers["Retry-After"] == "60"
    runs = (await db.execute(select(func.count()).select_from(ExecutionRun)
                             .where(ExecutionRun.company_id == company))).scalar()
    assert runs == 2

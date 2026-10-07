"""A run's input is checked against the entity's input schema before the run
exists (P8.1 — EP-04).

``io_contract.input_schema`` drew the run form and was checked by nothing: a
run with the wrong input was created, planned and paid for, then failed at the
step that needed the missing value. Now ``trigger_execution`` answers 422 and
no run row is written. Names the run page never asks for — a step's id or
name, ``step_N``, platform keys — are not required. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

pytestmark = pytest.mark.needs_db

SCHEMA = {"type": "object",
          "properties": {"topic": {"type": "string"}, "pages": {"type": "integer"},
                         "tone": {"type": "string", "enum": ["formal", "casual"]},
                         "research": {"type": "string"}, "step_2": {"type": "string"}},
          "required": ["topic", "research", "step_2", "company_id"]}


class _Reached(Exception):
    """The credit check, the step after the input check: the input passed."""


async def _entity(db, company_id):
    from src.ai.orm.entity import HierarchicalEntity
    entity = HierarchicalEntity(
        company_id=company_id, type="AGENT", name=f"p81-{uuid.uuid4().hex[:6]}",
        io_contract={"input_schema": SCHEMA},
        planning={"static_plan": {"enabled": True, "steps": [
            {"step_id": "s1", "name": "research", "type": "ACTION", "target": {"prompt_template": "{{topic}}"}}]}})
    db.add(entity)
    await db.flush()
    return entity


async def _trigger(db, company_id, entity, input_data):
    from src.ai.schemas.execution import ExecutionRunCreate
    from src.ai.service import AIService
    return await AIService(db).trigger_execution(ExecutionRunCreate(entity_id=entity.id, input_data=input_data),
                                                 company_id)


async def _runs(db, entity) -> int:
    from src.ai.orm import ExecutionRun
    return (await db.execute(select(func.count()).select_from(ExecutionRun)
                             .where(ExecutionRun.entity_id == entity.id))).scalar_one()


@pytest.mark.asyncio
async def test_input_that_does_not_fit_is_refused_before_the_run_exists(db, test_company_id):
    entity = await _entity(db, test_company_id)
    with pytest.raises(HTTPException) as exc:
        await _trigger(db, test_company_id, entity, {"input": "go", "pages": "ten", "tone": "angry"})
    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert "'topic' is required" in detail
    assert "'pages' must be integer" in detail and "'tone' must be one of" in detail
    # A step's name, a step_N reference and a platform key are never the user's to give.
    assert "research" not in detail and "step_2" not in detail and "company_id" not in detail
    assert await _runs(db, entity) == 0


@pytest.mark.asyncio
async def test_input_that_fits_goes_on(db, test_company_id, monkeypatch):
    from src.billing.credit_service import CreditService

    async def _reached(*_a, **_k):
        raise _Reached()

    monkeypatch.setattr(CreditService, "require_credits", _reached)
    entity = await _entity(db, test_company_id)
    with pytest.raises(_Reached):
        await _trigger(db, test_company_id, entity, {"input": "go", "topic": "tides", "pages": 3, "tone": "formal"})


def test_the_check_ignores_entities_without_a_schema_and_unknown_keywords():
    from types import SimpleNamespace
    from src.ai.governance.input_contract import input_problems
    assert input_problems(SimpleNamespace(io_contract=None, planning=None), {"x": 1}) == []
    loose = SimpleNamespace(io_contract={"input_schema": {"properties": {"n": {"type": "number", "minimum": 5}}}},
                            planning=None)
    assert input_problems(loose, {"n": 1}) == []           # minimum is not in the checked subset
    assert input_problems(loose, {"n": True}) == ["'n' must be number, not bool"]

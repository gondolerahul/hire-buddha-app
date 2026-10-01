"""A retry resumes the failed run: its tree and its finished steps (EP-29).

``retry_execution`` looked for ``__cortex_tree_id__`` in the failed run's
context, which nothing wrote, and copied ``context_state`` "so completed steps
are skipped", which nothing read — so a retry opened a fresh tree and re-ran
every step. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.needs_db

PLAN = {"steps": [
    {"step_id": "step_1_aa", "name": "search", "type": "THOUGHT"},
    {"step_id": "step_2_bb", "name": "write", "type": "THOUGHT",
     "target": {"input_dependencies": ["step_1_aa"]}},
]}


@pytest.fixture
def no_enqueue(monkeypatch):
    async def _enqueue(name, *args, **kwargs):  # noqa: ARG001
        return None

    monkeypatch.setattr("src.ai.service.enqueue_job", _enqueue)


@pytest.mark.asyncio
async def test_a_retry_carries_the_tree_the_plan_and_the_finished_steps(db, test_company_id, no_enqueue):
    from src.ai.core.step_results import REUSE_OUTPUTS_KEY
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun
    from src.ai.service import AIService

    entity = HierarchicalEntity(company_id=test_company_id, type="AGENT", name=f"ep29-{uuid.uuid4().hex[:6]}")
    db.add(entity)
    await db.flush()
    tree_id = str(uuid.uuid4())
    failed = ExecutionRun(
        company_id=test_company_id, entity_id=entity.id, status="FAILED",
        input_data={"input": "brief on agent memory"}, dynamic_plan=PLAN,
        context_state={"__cortex_tree_id__": tree_id},
        result_data={"output": "", "steps": [
            {"step_id": "step_1_aa", "step": "search", "output": "five sources"},
            {"step_id": "step_2_bb", "step": "write", "output": "", "error": "tool failed"},
        ]},
    )
    db.add(failed)
    await db.flush()

    retry = await AIService(db).retry_execution(failed.id, test_company_id, None)
    assert retry.input_data["cortex_tree_id"] == tree_id
    assert retry.input_data[REUSE_OUTPUTS_KEY] == {"step_1_aa": "five sources"}
    assert retry.dynamic_plan == PLAN

"""Critic calibration is keyed like the bandit and read by the critic (P7.10 —
PC-22).

The weekly calibrator grouped health records by ``entity_type:<type>`` /
``run:<mode>`` — keys nothing else used, while the bandit keys by the task
classifier's ``task_class`` — so the two could never be joined. Its write
probed ``IntelligenceTreeService`` for ``upsert_calibration_rule`` /
``record_rule``, which do not exist, and only logged; nothing read a result
anyway. Now each health record carries the run's task class, the calibrator
groups by it and writes ``Calibration: <task_class>`` beside the bandit's
table, and the post critic reads it. Real Postgres, rolled back.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.ai.models import ExecutionRun, HierarchicalEntity
from src.common.orm_models import import_all_models

import_all_models()

pytestmark = pytest.mark.needs_db


@pytest.fixture
async def world(db):
    from src.auth.models import Company
    c = Company(name=f"p710-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    ent = HierarchicalEntity(company_id=c.id, type="AGENT", status="ACTIVE", name="writer")
    db.add(ent)
    await db.flush()
    return SimpleNamespace(company=c.id, entity=ent.id)


async def _health_records(db, world, *, task_class, n, verdict, status):
    """``n`` runs of the entity with ``status``, each with one health record."""
    from src.ai.memory.cortex_models import CortexNode, CortexNodeType
    from src.ai.memory.intelligence_tree_service import IntelligenceTreeService
    tree = await IntelligenceTreeService(db, world.company).get_or_create_intelligence_tree(world.entity)
    for _ in range(n):
        run = ExecutionRun(entity_id=world.entity, company_id=world.company, status=status, input_data={})
        db.add(run)
        await db.flush()
        db.add(CortexNode(tree_id=tree.id, title="🩺", node_type=CortexNodeType.HEALTH_RECORD,
                          execution_run_id=run.id, created_at=datetime.utcnow(),
                          content=json.dumps({"post_critic_verdict": verdict, "task_class": task_class,
                                              "post_critic_tags": []})))
    await db.flush()


@pytest.mark.asyncio
async def test_calibration_groups_by_task_class_and_the_critic_reads_it(db, world):
    from src.ai.planning.critic_calibration import CriticCalibrator, calibration_note

    # 30 PASS verdicts on "research_topic", 12 of them in runs that failed.
    await _health_records(db, world, task_class="research_topic", n=18, verdict="PASS", status="COMPLETED")
    await _health_records(db, world, task_class="research_topic", n=12, verdict="PASS", status="FAILED")
    results = await CriticCalibrator(db, world.company).run()

    [res] = [r for r in results if r.entity_id == world.entity]
    assert (res.task_class, res.samples) == ("research_topic", 30)
    assert res.false_pass_rate == pytest.approx(0.4)

    note = await calibration_note(db, world.company, world.entity, "research_topic")
    assert "40% of your PASS verdicts" in note and "be stricter" in note
    assert await calibration_note(db, world.company, world.entity, "general") == ""


@pytest.mark.asyncio
async def test_the_post_critic_is_told_its_calibration():
    from unittest.mock import AsyncMock
    from src.ai.core.agent_state import AgentState, Budget, Observation
    from src.ai.planning.critic_pipeline import RealCriticPipeline
    from src.ai.schemas.enums import EntityType

    llm = AsyncMock()
    llm.call_llm.return_value = SimpleNamespace(output='{"verdict": "PASS"}', cost_usd=0, prompt_tokens=1,
                                                completion_tokens=1, model_name="m", provider="p")
    pipe = RealCriticPipeline(db=None, llm_router=llm, cortex_service=None,
                              config={"calibration_note": "Calibration: 40% … be stricter."})
    state = AgentState(run_id=uuid.uuid4(), entity_id=uuid.uuid4(), company_id=uuid.uuid4(),
                       entity_type=EntityType.AGENT, budget=Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000))
    await pipe.post_action(state, Observation(iteration=1, outcome="success", novelty_score=0.5,
                                              goal_delta_estimate=0.1, output="x"))
    assert "Calibration: 40% … be stricter." in llm.call_llm.await_args.kwargs["user_prompt"]


@pytest.mark.asyncio
async def test_a_failed_write_does_not_propagate(db, world, monkeypatch):
    import src.ai.planning.plan_style_bandit as psb
    from src.ai.planning.critic_calibration import CalibrationResult, CriticCalibrator

    async def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(psb, "upsert_strategy_node", _boom)
    await CriticCalibrator(db, world.company)._persist_intel_rule(
        CalibrationResult(entity_id=world.entity, task_class="x", samples=30))

"""What failed before reaches the next run; the unwired trust learner is gone
(P7.11 — PC-12, PC-11, D20).

``FailurePatternService`` mined an entity's recent failed runs into warnings
meant for the prompt, and nothing called it. ``TrustLearner`` and its
``source_trust_scores`` table had no writer and no reader. Now the patterns
are read once per run and shown in every step prompt beside memory; the
trust learner and its table are deleted. Real Postgres, rolled back.
"""
from __future__ import annotations

import importlib.util
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from src.ai.models import ExecutionRun, HierarchicalEntity
from src.common.orm_models import import_all_models

import_all_models()

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
async def test_an_entitys_failures_reach_its_next_runs_prompt(db):
    from src.ai.core.agent_state import AgentState, Budget
    from src.ai.core.run_blocks import add_run_blocks
    from src.ai.schemas.enums import EntityType
    from src.ai.step_executor import prompt_context_block
    from src.auth.models import Company

    c = Company(name=f"p711-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    ent = HierarchicalEntity(company_id=c.id, type="AGENT", status="ACTIVE", name="researcher")
    db.add(ent)
    await db.flush()
    for _ in range(3):
        db.add(ExecutionRun(entity_id=ent.id, company_id=c.id, status="FAILED", input_data={},
                            error_message="step 'search': the call timed out after 60s"))
    run = ExecutionRun(entity_id=ent.id, company_id=c.id, status="RUNNING", input_data={"input": "x"})
    db.add(run)
    await db.flush()

    state = AgentState(run_id=run.id, entity_id=ent.id, company_id=c.id, entity_type=EntityType.AGENT,
                       budget=Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000))
    await add_run_blocks(db, state, run.id)

    block = state.failure_patterns_block
    assert "TIMEOUT occurred in 3 of last 3 failed runs" in block
    from src.ai.core.step_signals import signals_from_state, step_signals
    with step_signals(signals_from_state(state)):             # how the loop hands it to a step (AK-21)
        assert block in prompt_context_block({}, state.context_state)


@pytest.mark.asyncio
async def test_the_trust_learner_and_its_table_are_gone(db):
    assert importlib.util.find_spec("src.ai.memory.trust_learning") is None
    exists = (await db.execute(text("select to_regclass('public.source_trust_scores')"))).scalar_one()
    assert exists is None
    from src.ai.core.feature_flags import DEFAULTS
    assert "memory.trust_score_learning" not in DEFAULTS

"""A run reads its pinned version, not the live row (P5.2, EP-10).

The loop, the worker and every executor read ``run.entity`` — the live row —
so an edit made while a run was in flight reached it at its next step. They
now read ``run_entity``: the version the run was pinned to when it was
created. Real Postgres, rolled back.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.ai.core.agent_state import AgentState
from src.ai.core.budget import Budget
from src.ai.core.strategist import Move
from src.ai.governance.entity_versions import run_entity
from src.ai.orm import ExecutionRun, HierarchicalEntity
from src.ai.schemas.enums import EntityType

pytestmark = pytest.mark.needs_db

SRC = Path(__file__).resolve().parents[2] / "src" / "ai"


async def _pinned_then_edited(db):
    from src.auth.models import Company
    c = Company(name=f"p52-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    ent = HierarchicalEntity(company_id=c.id, type="ACTION", status="ACTIVE", name="pinned",
                             goal="old goal", identity={"system_prompt": "old prompt"})
    db.add(ent)
    await db.flush()
    run = ExecutionRun(entity_id=ent.id, company_id=c.id, status="RUNNING", input_data={})
    db.add(run)
    await db.flush()
    ent.goal, ent.identity, ent.status = "new goal", {"system_prompt": "new prompt"}, "DEPRECATED"
    await db.flush()
    run = (await db.execute(
        select(ExecutionRun).options(selectinload(ExecutionRun.entity)).where(ExecutionRun.id == run.id)
    )).scalar_one()
    return ent, run


@pytest.mark.asyncio
async def test_the_run_reads_its_version_and_the_rows_lifecycle(db):
    ent, run = await _pinned_then_edited(db)
    pinned = await run_entity(db, run)
    assert (pinned.goal, pinned.identity["system_prompt"]) == ("old goal", "old prompt")
    assert (pinned.id, pinned.company_id, pinned.status) == (ent.id, ent.company_id, "DEPRECATED")


@pytest.mark.asyncio
async def test_the_pinned_entity_can_never_be_written_back(db):
    ent, run = await _pinned_then_edited(db)
    pinned = await run_entity(db, run)
    pinned.goal = "scribbled"
    pinned.identity["system_prompt"] = "scribbled"
    await db.flush()
    row = (await db.execute(select(HierarchicalEntity.goal, HierarchicalEntity.identity)
                            .where(HierarchicalEntity.id == ent.id))).one()
    assert row.goal == "new goal" and row.identity == {"system_prompt": "new prompt"}
    assert (await run_entity(db, run)).identity["system_prompt"] == "old prompt"   # the cache was not touched


@pytest.mark.asyncio
async def test_a_run_from_before_versions_reads_the_live_row(db):
    ent, run = await _pinned_then_edited(db)
    run.entity_version_id = None
    assert (await run_entity(db, run)).goal == "new goal"


@pytest.mark.asyncio
async def test_an_executor_hands_the_step_engine_the_pinned_entity(db, monkeypatch):
    from src.ai.core.executors.dag import DAGExecutor
    from src.ai.core.step_engine import StepEngine
    seen = {}

    async def _capture(self, run, entity, steps, ctx, results_map=None):
        seen["entity"] = entity
        return []

    monkeypatch.setattr(StepEngine, "_execute_steps_dag", _capture)
    ent, run = await _pinned_then_edited(db)
    state = AgentState(run_id=run.id, entity_id=ent.id, company_id=ent.company_id,
                       entity_type=EntityType.ACTION,
                       budget=Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000))
    move = Move(move_id="m", goal_id=None, executor="DAG",
                plan_fragment=[{"step_id": "s1", "type": "LLM_REASONING"}], rationale="t")

    await DAGExecutor().execute(move, state, db)

    assert seen["entity"].identity["system_prompt"] == "old prompt"


def test_nothing_on_the_run_path_reads_the_live_row():
    """Only the worker's deleted-entity guard may read ``run.entity`` (a lifecycle check)."""
    allowed = {("core/arq_jobs.py", "guard_run.entity is None")}
    offenders = []
    for path in [*sorted((SRC / "core").rglob("*.py")), SRC / "step_executor.py"]:
        rel = path.relative_to(SRC).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r"\b(run|guard_run|run_obj|child_run)\.entity\b(?!_)", line) and "selectinload" not in line:
                if not any(rel == a and frag in line for a, frag in allowed):
                    offenders.append(f"{rel}: {line.strip()}")
    assert offenders == []

"""Phase 11 BUG 2 regression — a routing PROCESS must delegate to its
child AGENTs and actually *produce* a document, not print tool code as text.

This is the end-to-end counterpart to the deterministic unit tests in
``tests/unit/test_planner_service.py``. It drives a real execution of the
seeded doc-factory PROCESS against a live DB + live LLM and asserts that:

  1. at least one ``ToolInteractionLog`` row is written for the run tree
     (root run + spawned child runs) — i.e. the model actually invoked a
     document tool inside a child AGENT instead of emitting code as TEXT; and
  2. at least one artifact file lands on disk under the artifact store.

Because it needs both a Postgres with the doc-factory entity seeded and a
real LLM in the loop, it is **skipped by default**. To run it:

    export DATABASE_URL=postgresql+asyncpg://...
    export DOC_FACTORY_PROCESS_ID=d3413e2a-7141-4d7b-ac48-f5244b68128b
    export DOC_FACTORY_COMPANY_ID=<company uuid owning that entity>
    export RUN_LIVE_DOC_REGRESSION=1            # opt-in (live LLM spend)
    pytest tests/regression/test_doc_factory_routing_regression.py -m regression

Leave ``RUN_LIVE_DOC_REGRESSION`` unset and the test skips cleanly.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import func, select

pytestmark = [pytest.mark.regression, pytest.mark.needs_db, pytest.mark.needs_llm, pytest.mark.slow]


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        pytest.skip(f"{name} not set; live doc-factory regression skipped")
    return val


@pytest.mark.asyncio
async def test_doc_factory_xlsx_request_produces_tool_log_and_artifact():
    if os.environ.get("RUN_LIVE_DOC_REGRESSION") != "1":
        pytest.skip("RUN_LIVE_DOC_REGRESSION!=1; live doc-factory regression skipped")

    process_id = uuid.UUID(_require_env("DOC_FACTORY_PROCESS_ID"))
    company_id = uuid.UUID(_require_env("DOC_FACTORY_COMPANY_ID"))

    from src.common.database import AsyncSessionLocal
    from src.ai.models import ExecutionRun, HierarchicalEntity, ToolInteractionLog
    from src.ai.artifact_models import Artifact
    from src.ai.core.arq_jobs import run_execution_recursive

    # ── Seed a run for the doc-factory PROCESS with an XLSX request ──────────
    async with AsyncSessionLocal() as db:
        entity = (await db.execute(
            select(HierarchicalEntity).where(
                HierarchicalEntity.id == process_id,
                HierarchicalEntity.company_id == company_id,
            )
        )).scalar_one_or_none()
        if entity is None:
            pytest.skip(f"doc-factory entity {process_id} not seeded in this DB")

        run = ExecutionRun(
            id=uuid.uuid4(),
            entity_id=process_id,
            company_id=company_id,
            status="PENDING",
            input_data={
                "input": (
                    "Create an XLSX spreadsheet titled 'Q3 Sales' with columns "
                    "Region, Units, Revenue and three example rows."
                ),
                # Force the new orchestrator so we exercise the BUG 2 path.
                "feature_flags": {"agent_loop.enabled": True},
            },
        )
        db.add(run)
        await db.commit()
        run_id = run.id

    # ── Drive the run in-process (real LLM + tools) ─────────────────────────
    await run_execution_recursive(ctx={}, run_id_str=str(run_id))

    # ── Assert: tool was actually invoked, and an artifact exists ───────────
    async with AsyncSessionLocal() as db:
        # Collect the whole run tree (root + children spawned by routing).
        run_ids = {run_id}
        child_ids = (await db.execute(
            select(ExecutionRun.id).where(ExecutionRun.parent_run_id == run_id)
        )).scalars().all()
        run_ids.update(child_ids)

        tool_count = (await db.execute(
            select(func.count(ToolInteractionLog.id))
            .where(ToolInteractionLog.run_id.in_(run_ids))
        )).scalar_one()

        assert tool_count >= 1, (
            "doc-factory routing produced ZERO ToolInteractionLog rows — the "
            "orchestrator returned tool code as text instead of delegating to a "
            "child AGENT that runs the document tool. run_ids="
            f"{[str(r) for r in run_ids]}"
        )

        # At least one artifact row, and its file must exist on disk.
        artifacts = (await db.execute(
            select(Artifact).where(Artifact.company_id == company_id)
            .order_by(Artifact.created_at.desc()).limit(20)
        )).scalars().all()
        on_disk = [a for a in artifacts if a.file_path and os.path.exists(a.file_path)]
        assert on_disk, "no produced artifact found on disk for the doc-factory run"

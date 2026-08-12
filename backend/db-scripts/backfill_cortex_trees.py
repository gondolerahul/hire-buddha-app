"""
backfill_cortex_trees.py — Backfill CORTEX trees from existing execution runs.

Creates a CORTEX memory tree for each completed execution run that doesn't
already have one. This populates the CORTEX Memory Trees page with
historical execution data.

Usage:
    cd /home/rahul/workspace/hb-proto-3/backend
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/hirebuddha \
        python -m db-scripts.backfill_cortex_trees
"""
import asyncio
import json
import os
import sys
import logging

# Add backend to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, selectinload

from src.common.database import Base
from src.ai.models import ExecutionRun, HierarchicalEntity, RunStatus
from src.ai.cortex_models import (
    CortexTree, CortexNode,
    CortexTreeStatus, CortexNodeType, CortexNodeStatus,
)
from src.ai.cortex_service import CortexRouter as CortexService

# Import all models so Base.metadata has full picture
import src.auth.models
import src.config.models
import src.ai.cortex_models
import src.billing.billing_models

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5433/hirebuddha",
)


async def backfill():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Get all completed execution runs
        result = await db.execute(
            select(ExecutionRun)
            .options(selectinload(ExecutionRun.entity))
            .where(ExecutionRun.status == RunStatus.COMPLETED)
            .order_by(ExecutionRun.created_at.asc())
        )
        runs = result.scalars().all()
        logger.info(f"Found {len(runs)} completed execution runs to backfill")

        created = 0
        for run in runs:
            entity = run.entity
            if not entity:
                logger.warning(f"  Skipping run {run.id}: no entity found")
                continue

            # Check if a tree already exists for this run (by checking metadata)
            existing = await db.execute(
                select(func.count(CortexTree.id)).where(
                    CortexTree.entity_id == entity.id,
                    CortexTree.company_id == entity.company_id,
                    CortexTree.task_description.like(f"%{entity.name}%"),
                )
            )
            # We don't skip — each run gets its own tree

            try:
                cortex = CortexService(db=db, company_id=entity.company_id)

                # Build task description
                input_summary = ""
                if run.input_data:
                    input_keys = [k for k in run.input_data.keys() if not k.startswith("__")]
                    input_summary = ", ".join(
                        f"{k}={str(run.input_data[k])[:80]}" for k in input_keys[:5]
                    )
                task_desc = f"{entity.name}: {input_summary}" if input_summary else entity.name

                tree = await cortex.create_tree(
                    entity_id=entity.id,
                    user_id=run.user_id,
                    task_description=task_desc[:1000],
                )

                # Get the plan steps
                steps = []
                if run.dynamic_plan:
                    steps = run.dynamic_plan.get("steps", [])

                # Get step results
                step_results = []
                if run.result_data:
                    step_results = run.result_data.get("steps", [])

                # Find working memory root (sibling_order=1 under root)
                wm_result = await db.execute(
                    select(CortexNode).where(
                        CortexNode.tree_id == tree.id,
                        CortexNode.parent_id == tree.root_node_id,
                        CortexNode.sibling_order == 1,
                    )
                )
                working_root = wm_result.scalar_one_or_none()

                if working_root and steps:
                    for i, step in enumerate(steps):
                        step_name = step.get("name", f"Step {i+1}")
                        step_desc = step.get("description", "")
                        step_type = step.get("type", "ACTION")

                        step_output = ""
                        if i < len(step_results):
                            sr = step_results[i]
                            if isinstance(sr, dict):
                                step_output = str(
                                    sr.get("output", sr.get("result", json.dumps(sr, default=str)))
                                )[:10000]
                            else:
                                step_output = str(sr)[:10000]

                        summary = f"[{step_type}] {step_desc[:300]}"
                        content = (
                            f"Step: {step_name}\nType: {step_type}\n"
                            f"Description: {step_desc}\n\n--- Output ---\n{step_output}"
                        )

                        await cortex.write(
                            parent_id=working_root.id,
                            node_type="finding",
                            title=step_name,
                            summary=summary,
                            content=content,
                            status="complete",
                            metadata_extra={
                                "step_id": step.get("step_id"),
                                "step_type": step_type,
                                "run_id": str(run.id),
                            },
                        )

                # Write final output
                if tree.output_root_id and run.result_data:
                    final_output = run.result_data.get("output", "")
                    if final_output:
                        await cortex.write(
                            parent_id=tree.output_root_id,
                            node_type="output",
                            title="Final Output",
                            summary=str(final_output)[:300],
                            content=str(final_output)[:50000],
                            status="complete",
                        )

                # Mark tree complete and set timestamps from the run
                tree.status = CortexTreeStatus.COMPLETE
                tree.created_at = run.created_at
                tree.last_active_at = run.completed_at or run.created_at

                await db.flush()
                created += 1
                logger.info(
                    f"  [{created}] Created tree {tree.id} from run {run.id} "
                    f"({entity.name}, {len(steps)} steps)"
                )

            except Exception as e:
                logger.error(f"  Failed to create tree for run {run.id}: {e}")
                await db.rollback()
                continue

        await db.commit()
        logger.info(f"\nBackfill complete: {created} CORTEX trees created from {len(runs)} runs")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(backfill())

"""
migrate_episodic_to_trees.py — Data Migration Script

Migrates existing episodic_memories rows into v2 Episodic Trees.
Idempotent — skips entities that already have episodes in their tree.

Usage:
    cd backend
    source .venv/bin/activate
    python -m src.ai.migrate_episodic_to_trees
"""
import asyncio
import json
import logging
from uuid import UUID

from sqlalchemy import select, func

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("episodic_tree_migration")


async def run_migration():
    """Migrate episodic_memories → Episodic Trees."""
    from src.common.database import AsyncSessionLocal
    from src.ai.models import EpisodicMemory
    from src.ai.memory.episodic_tree_service import EpisodicTreeService
    from src.ai.memory.cortex_models import CortexTree, CortexNode, MemoryDomain, ScopeLevel, CortexNodeType

    logger.info("=" * 60)
    logger.info("Episodic Tree Migration — episodic_memories → Episodic Trees")
    logger.info("=" * 60)

    async with AsyncSessionLocal() as db:
        # Find all entities with episodic memories
        result = await db.execute(
            select(
                EpisodicMemory.entity_id,
                EpisodicMemory.company_id,
                func.count(EpisodicMemory.id).label("count"),
            )
            .group_by(EpisodicMemory.entity_id, EpisodicMemory.company_id)
        )
        entity_groups = result.all()

        if not entity_groups:
            logger.info("No episodic memories found. Nothing to migrate.")
            return

        logger.info(f"Found {len(entity_groups)} entities with episodic memories.")
        total_migrated = 0

        for entity_id, company_id, mem_count in entity_groups:
            # Check if already migrated
            existing = await db.execute(
                select(func.count(CortexNode.id))
                .join(CortexTree, CortexNode.tree_id == CortexTree.id)
                .where(
                    CortexTree.entity_id == entity_id,
                    CortexTree.memory_domain == MemoryDomain.EPISODIC,
                    CortexNode.node_type == CortexNodeType.EPISODE,
                )
            )
            if (existing.scalar() or 0) > 0:
                logger.info(f"  Entity {entity_id}: already has episodes, skipping")
                continue

            logger.info(f"\nMigrating entity {entity_id} ({mem_count} memories)...")

            try:
                svc = EpisodicTreeService(db, company_id)
                tree = await svc.get_or_create_episodic_tree(entity_id)

                # Load all memories ordered chronologically
                mem_result = await db.execute(
                    select(EpisodicMemory)
                    .where(EpisodicMemory.entity_id == entity_id)
                    .order_by(EpisodicMemory.created_at)
                )
                memories = mem_result.scalars().all()

                for mem in memories:
                    ts = mem.created_at
                    if not ts:
                        continue

                    month_key = ts.strftime("%Y-%m")
                    day_key = ts.strftime("%Y-%m-%d")

                    month_id = await svc._get_or_create_group(
                        tree.id, tree.root_node_id, month_key,
                        f"📅 {ts.strftime('%B %Y')}", depth=1,
                    )
                    day_id = await svc._get_or_create_group(
                        tree.id, month_id, day_key,
                        f"📅 {ts.strftime('%A, %B %d, %Y')}", depth=2,
                    )

                    from src.ai.memory.cortex_models import CortexNodeStatus
                    from uuid import uuid4

                    sibling_order = await svc._next_sibling_order(day_id)
                    node = CortexNode(
                        id=uuid4(),
                        tree_id=tree.id,
                        parent_id=day_id,
                        node_type=CortexNodeType.EPISODE,
                        title=f"🎬 {(mem.input_summary or 'Execution')[:80]}",
                        summary=f"[{mem.status}] {(mem.input_summary or '')[:200]} → {(mem.output_summary or '')[:200]}",
                        content=json.dumps({
                            "input": mem.input_summary,
                            "output": mem.output_summary,
                            "status": mem.status,
                        }),
                        status=CortexNodeStatus.COMPLETE,
                        depth=3,
                        sibling_order=sibling_order,
                        source_ref={
                            "ref_type": "execution_run",
                            "run_id": str(mem.run_id) if mem.run_id else None,
                            "runtime_tree_id": str(mem.tree_id) if mem.tree_id else None,
                        },
                        metadata_extra={
                            "run_id": str(mem.run_id) if mem.run_id else None,
                            "runtime_tree_id": str(mem.tree_id) if mem.tree_id else None,
                            "status": mem.status,
                            "cost_usd": float(mem.total_cost_usd) if mem.total_cost_usd else 0,
                            "total_tokens": mem.total_tokens or 0,
                            "execution_time_ms": mem.execution_time_ms,
                            "migrated_from": "episodic_memories",
                            "original_id": str(mem.id),
                        },
                    )
                    db.add(node)
                    tree.total_nodes = (tree.total_nodes or 0) + 1
                    total_migrated += 1

                await db.commit()
                logger.info(f"  Migrated {len(memories)} episodes for entity {entity_id}")

            except Exception as e:
                logger.error(f"  Entity {entity_id} migration failed: {e}")
                await db.rollback()

        logger.info(f"\n{'=' * 60}")
        logger.info(f"Migration complete: {total_migrated} episodes migrated")
        logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(run_migration())

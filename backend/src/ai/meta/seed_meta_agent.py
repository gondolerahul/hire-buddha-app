"""
seed_meta_agent.py — Seeds Meta-Agent V3 template into the database.

V3: Seeds a single AGENT entity for EVERY company account.
The Meta-Agent is no longer architecturally special — it's a standard
AGENT entity with the tiered meta-cognition layer fully enabled.

Usage: cd backend && .venv/bin/python -m src.ai.meta.seed_meta_agent

Flags:
    --force     Purge ALL existing MetaAgent templates/entities before seeding.
                Without this flag, the script skips companies that already have one.
    --company   Only seed for a specific company_id (default: all companies).
"""
import asyncio, sys
from pathlib import Path
from typing import Any, Optional
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


async def _purge_entities(db: Any, entity_ids: list[str]) -> None:
    """
    Delete a set of HierarchicalEntity rows and ALL their FK dependents.

    Traversal order (leaf → root):
      1. cortex_nodes → cortex_trees (via tree_id)
      2. episodic_memories (entity_id + tree_id)
      3. cortex_trees (entity_id)
      4. llm_interaction_logs, tool_interaction_logs, usage_logs, human_approvals (run_id)
      5. execution_runs (child runs first, then parents)
      6. documents / document_chunks (entity_id)
      7. hierarchical_entities (children/clones first, then roots)
    """
    from sqlalchemy import text

    id_list = ",".join(f"'{eid}'" for eid in entity_ids)

    # ── Expand to include children & clones ──
    r = await db.execute(text(f"""
        SELECT id FROM hierarchical_entities
        WHERE id IN ({id_list})
           OR parent_id IN ({id_list})
           OR template_source_id IN ({id_list})
    """))
    all_eids = [str(row[0]) for row in r.fetchall()]
    all_id_list = ",".join(f"'{eid}'" for eid in all_eids)
    print(f"  Found {len(all_eids)} total entities (incl. children/clones)")

    # ── Cortex trees for these entities ──
    r = await db.execute(text(
        f"SELECT id FROM cortex_trees WHERE entity_id IN ({all_id_list})"
    ))
    tree_ids = [str(row[0]) for row in r.fetchall()]
    if tree_ids:
        tree_id_list = ",".join(f"'{tid}'" for tid in tree_ids)
        print(f"  Deleting {len(tree_ids)} cortex trees + nodes …")
        await db.execute(text(f"DELETE FROM cortex_nodes WHERE tree_id IN ({tree_id_list})"))
        # episodic_memories references tree_id too
        await db.execute(text(f"DELETE FROM episodic_memories WHERE tree_id IN ({tree_id_list})"))
        await db.execute(text(f"DELETE FROM cortex_trees WHERE id IN ({tree_id_list})"))

    # ── Episodic memories by entity (catch any not linked to a tree) ──
    await db.execute(text(
        f"DELETE FROM episodic_memories WHERE entity_id IN ({all_id_list})"
    ))

    # ── Execution runs + their dependents ──
    # Collect ALL run IDs (including deeply-nested child runs) via recursive CTE
    r = await db.execute(text(f"""
        WITH RECURSIVE run_tree AS (
            SELECT id FROM execution_runs WHERE entity_id IN ({all_id_list})
            UNION ALL
            SELECT er.id FROM execution_runs er
            JOIN run_tree rt ON er.parent_run_id = rt.id
        )
        SELECT id FROM run_tree
    """))
    run_ids = [str(row[0]) for row in r.fetchall()]

    if run_ids:
        run_id_list = ",".join(f"'{rid}'" for rid in run_ids)
        print(f"  Deleting {len(run_ids)} execution runs + dependents …")
        for tbl in [
            "llm_interaction_logs",
            "tool_interaction_logs",
            "usage_logs",
            "human_approvals",
        ]:
            await db.execute(text(f"DELETE FROM {tbl} WHERE run_id IN ({run_id_list})"))

        # Delete runs bottom-up: children before parents
        await db.execute(text(f"""
            DELETE FROM execution_runs WHERE id IN ({run_id_list})
        """))

    # ── Documents ──
    r = await db.execute(text(
        f"SELECT id FROM documents WHERE entity_id IN ({all_id_list})"
    ))
    doc_ids = [str(row[0]) for row in r.fetchall()]
    if doc_ids:
        doc_id_list = ",".join(f"'{did}'" for did in doc_ids)
        await db.execute(text(f"DELETE FROM document_chunks WHERE document_id IN ({doc_id_list})"))
        await db.execute(text(f"DELETE FROM documents WHERE id IN ({doc_id_list})"))

    # ── Finally, the entities themselves (children/clones first, then roots) ──
    await db.execute(text(
        f"DELETE FROM hierarchical_entities WHERE parent_id IN ({id_list}) AND id NOT IN ({id_list})"
    ))
    await db.execute(text(
        f"DELETE FROM hierarchical_entities WHERE template_source_id IN ({id_list}) AND id NOT IN ({id_list})"
    ))
    await db.execute(text(
        f"DELETE FROM hierarchical_entities WHERE id IN ({id_list})"
    ))


async def seed(force: bool = False, target_company_id: Optional[str] = None) -> None:
    from sqlalchemy import select, text, or_, String
    from src.common.database import AsyncSessionLocal
    from src.ai.models import HierarchicalEntity
    from src.ai.schemas import HierarchicalEntityCreate
    from src.ai.meta.meta_agent_template import generate_meta_agent_template

    async with AsyncSessionLocal() as db:
        # ── 1. Find the primary admin account ──
        if target_company_id:
            r = await db.execute(text(
                f"SELECT id, company_id FROM users WHERE company_id = '{target_company_id}' "
                f"ORDER BY CASE WHEN role = 'app_admin' THEN 0 "
                f"WHEN role = 'admin' THEN 1 ELSE 2 END LIMIT 1"
            ))
        else:
            r = await db.execute(text(
                "SELECT id, company_id FROM users WHERE role='app_admin' LIMIT 1"
            ))
        admin = r.fetchone()
        if not admin:
            print("No admin user found.")
            return

        uid, cid = admin[0], admin[1]
        companies = [(cid,)]
        print(f"Seeding MetaAgent template for admin: uid={uid}, company={cid}")

        # ── 2. For each company, check and seed ──
        seeded_count = 0
        skipped_count = 0

        for (cid,) in companies:
            # Check if MetaAgent already exists for this company
            meta_q = select(HierarchicalEntity).where(
                HierarchicalEntity.company_id == cid,
                or_(
                    HierarchicalEntity.name == "MetaAgent",
                    HierarchicalEntity.tags.cast(String).contains("meta_agent"),
                ),
            )
            result = await db.execute(meta_q)
            existing = result.scalars().all()

            if existing and not force:
                skipped_count += 1
                continue

            if existing and force:
                entity_ids = [str(e.id) for e in existing]
                print(f"  Purging {len(entity_ids)} existing MetaAgent entities …")
                await _purge_entities(db, entity_ids)
                await db.flush()

            # Create the Meta-Agent V3 template
            template = generate_meta_agent_template()
            ein = HierarchicalEntityCreate.model_validate(template)
            data = ein.model_dump(mode="json")
            ma = HierarchicalEntity(**data, company_id=cid, created_by=uid)
            db.add(ma)
            await db.flush()

            seeded_count += 1
            print(f"  ✓ Meta-Agent V3 seeded: id={ma.id}")

        await db.commit()
        print(f"\n{'═' * 50}")
        print(f"Meta-Agent V3 Seeding Complete")
        print(f"  Seeded: {seeded_count} companies")
        print(f"  Skipped: {skipped_count} companies (already have MetaAgent)")
        print(f"  Version: 3.0.0")
        if skipped_count > 0:
            print(f"  Run with --force to re-seed skipped companies")

if __name__ == "__main__":
    force = "--force" in sys.argv
    company = None
    for i, arg in enumerate(sys.argv):
        if arg == "--company" and i + 1 < len(sys.argv):
            company = sys.argv[i + 1]
    asyncio.run(seed(force=force, target_company_id=company))

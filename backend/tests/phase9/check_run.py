"""
Post-Execution CORTEX Memory v2 Verification
Checks if the latest deep-research-process run triggered all memory subsystems.
"""
import asyncio, sys, json

async def main():
    import logging
    logging.getLogger('sqlalchemy').setLevel(logging.ERROR)
    logging.getLogger('asyncpg').setLevel(logging.ERROR)
    
    import src.auth.models, src.config.models, src.ai.models
    from src.common.database import AsyncSessionLocal
    from sqlalchemy import text
    from uuid import UUID

    ENTITY_ID  = UUID('3cbc5ea1-dbc3-4f8a-9074-d8b751408777')
    COMPANY_ID = UUID('699098ce-a31c-42ef-b13b-2780c7decb9d')

    async with AsyncSessionLocal() as db:
        # 1. Latest execution run
        r = await db.execute(text("""
            SELECT id, status, created_at, completed_at, 
                   total_cost_usd, total_tokens
            FROM execution_runs 
            WHERE entity_id = :eid
            ORDER BY created_at DESC LIMIT 1
        """), {"eid": str(ENTITY_ID)})
        run = r.fetchone()
        if not run:
            print("NO execution runs found!", flush=True)
            return
        
        run_id = run[0]
        print(f"=== Latest Execution Run ===", flush=True)
        print(f"  Run ID:    {run_id}", flush=True)
        print(f"  Status:    {run[1]}", flush=True)
        print(f"  Created:   {run[2]}", flush=True)
        print(f"  Completed: {run[3]}", flush=True)
        print(f"  Cost:      ${run[4] or 0}", flush=True)
        print(f"  Tokens:    {run[5] or 0}", flush=True)

        # 2. Child runs
        r2 = await db.execute(text("""
            SELECT er.id, er.status, he.name, er.total_cost_usd, er.total_tokens, er.created_at
            FROM execution_runs er
            JOIN hierarchical_entities he ON he.id = er.entity_id
            WHERE er.parent_run_id = :rid
            ORDER BY er.created_at
        """), {"rid": str(run_id)})
        children = r2.fetchall()
        print(f"\n=== Child Runs ({len(children)}) ===", flush=True)
        for c in children:
            print(f"  {c[2]}: {c[1]} (cost=${c[3] or 0}, tokens={c[4] or 0})", flush=True)

        # 3. V2 CORTEX trees
        print(f"\n=== V2 CORTEX Trees ===", flush=True)
        r4 = await db.execute(text("""
            SELECT memory_domain, scope_level, is_persistent, total_nodes, status
            FROM cortex_trees
            WHERE entity_id = :eid AND memory_domain IS NOT NULL
            ORDER BY memory_domain
        """), {"eid": str(ENTITY_ID)})
        trees = r4.fetchall()
        for t in trees:
            print(f"  {t[0]}: scope={t[1]}, persistent={t[2]}, nodes={t[3]}, status={t[4]}", flush=True)
        if not trees:
            print("  (none)", flush=True)

        # Also check trees created for ALL entities during this run
        all_entity_ids = [str(ENTITY_ID)]
        for c in children:
            all_entity_ids.append(str(c[0]))  # This is run_id, need entity_id
        
        r_all = await db.execute(text("""
            SELECT ct.memory_domain, COUNT(*), SUM(ct.total_nodes)
            FROM cortex_trees ct
            WHERE ct.memory_domain IS NOT NULL
            GROUP BY ct.memory_domain
            ORDER BY ct.memory_domain
        """))
        print(f"\n=== All V2 Trees (system-wide) ===", flush=True)
        for row in r_all.fetchall():
            print(f"  {row[0]}: {row[1]} trees, {row[2]} total nodes", flush=True)

        # 4. Episodic memory dual-write check
        r5 = await db.execute(text("""
            SELECT COUNT(*) FROM cortex_nodes cn
            JOIN cortex_trees ct ON cn.tree_id = ct.id
            WHERE ct.entity_id = :eid AND ct.memory_domain = 'episodic' AND cn.node_type = 'episode'
        """), {"eid": str(ENTITY_ID)})
        v2_eps = r5.scalar()

        r6 = await db.execute(text("""
            SELECT COUNT(*) FROM episodic_memories WHERE entity_id = :eid
        """), {"eid": str(ENTITY_ID)})
        v1_eps = r6.scalar()
        print(f"\n=== Episodic Memory (Dual-Write Check) ===", flush=True)
        print(f"  v1 episodic_memories: {v1_eps}", flush=True)
        print(f"  v2 cortex_nodes(episode): {v2_eps}", flush=True)
        if v1_eps > 0 and v2_eps > 0:
            print(f"  ✅ Dual-write WORKING", flush=True)
        elif v1_eps > 0 and v2_eps == 0:
            print(f"  ⚠️ v1 written but v2 not — check episodic_tree_service", flush=True)
        elif v1_eps == 0:
            print(f"  ⚠️ No episodes written yet (run may still be in progress)", flush=True)

        # 5. Semantic graph
        r7 = await db.execute(text("""
            SELECT edge_type, COUNT(*), AVG(weight)::numeric(5,3) 
            FROM cortex_edges GROUP BY edge_type
        """))
        edges = r7.fetchall()
        print(f"\n=== Semantic Graph Edges ===", flush=True)
        if edges:
            for e in edges:
                print(f"  {e[0]}: {e[1]} edges, avg_weight={e[2]}", flush=True)
            print(f"  ✅ Graph edges present", flush=True)
        else:
            print(f"  (no edges yet)", flush=True)

        # 6. Knowledge tree detail
        r8 = await db.execute(text("""
            SELECT cn.node_type, COUNT(*), SUM(CASE WHEN cn.embedding IS NOT NULL THEN 1 ELSE 0 END)
            FROM cortex_nodes cn
            JOIN cortex_trees ct ON cn.tree_id = ct.id
            WHERE ct.entity_id = :eid AND ct.memory_domain = 'knowledge'
            GROUP BY cn.node_type ORDER BY cn.node_type
        """), {"eid": str(ENTITY_ID)})
        kn = r8.fetchall()
        print(f"\n=== Knowledge Tree Nodes ===", flush=True)
        for k in kn:
            print(f"  {k[0]}: {k[1]} nodes ({k[2]} embedded)", flush=True)
        if not kn:
            print(f"  (empty - no documents ingested)", flush=True)

        # 7. Experience/Intelligence
        for domain in ['experience', 'intelligence']:
            r9 = await db.execute(text("""
                SELECT cn.node_type, COUNT(*)
                FROM cortex_nodes cn
                JOIN cortex_trees ct ON cn.tree_id = ct.id
                WHERE ct.entity_id = :eid AND ct.memory_domain = :dom
                GROUP BY cn.node_type ORDER BY cn.node_type
            """), {"eid": str(ENTITY_ID), "dom": domain})
            nodes = r9.fetchall()
            print(f"\n=== {domain.title()} Tree ===", flush=True)
            for n in nodes:
                print(f"  {n[0]}: {n[1]}", flush=True)
            if not nodes:
                print(f"  (empty - dreaming not run yet)", flush=True)

        # 8. Check CORTEX tree created during THIS run
        print(f"\n=== CORTEX Trees from This Run ===", flush=True)
        r10 = await db.execute(text("""
            SELECT ct.id, ct.entity_id, he.name, ct.memory_domain, ct.total_nodes, ct.status
            FROM cortex_trees ct
            LEFT JOIN hierarchical_entities he ON he.id = ct.entity_id
            WHERE ct.created_at >= :run_start
            ORDER BY ct.created_at
        """), {"run_start": str(run[2])})
        new_trees = r10.fetchall()
        for t in new_trees:
            print(f"  [{t[3] or 'runtime'}] {t[2] or 'unknown'}: {t[4]} nodes ({t[5]})", flush=True)
        if not new_trees:
            print(f"  (no new trees created during this run)", flush=True)

        # 9. Check if memory_service wrote episodic for this run
        print(f"\n=== Run Episodic Check ===", flush=True)
        r11 = await db.execute(text("""
            SELECT em.id, em.summary, em.created_at
            FROM episodic_memories em
            WHERE em.entity_id = :eid
            ORDER BY em.created_at DESC LIMIT 3
        """), {"eid": str(ENTITY_ID)})
        recent_eps = r11.fetchall()
        for ep in recent_eps:
            print(f"  [{ep[2]}] {(ep[1] or '')[:80]}...", flush=True)
        if not recent_eps:
            print(f"  (no episodic memories for this entity yet)", flush=True)

        # 10. Overall summary
        print(f"\n{'='*60}", flush=True)
        print(f"CORTEX MEMORY V2 STATUS SUMMARY", flush=True)
        print(f"{'='*60}", flush=True)
        checks = {
            "Knowledge Tree": len(kn) > 0,
            "Experience Tree": any(True for _ in [await db.execute(text("SELECT 1 FROM cortex_trees WHERE entity_id = :eid AND memory_domain = 'experience'"), {"eid": str(ENTITY_ID)})]),
            "Intelligence Tree": any(True for _ in [await db.execute(text("SELECT 1 FROM cortex_trees WHERE entity_id = :eid AND memory_domain = 'intelligence'"), {"eid": str(ENTITY_ID)})]),
            "Episodic v1": v1_eps > 0,
            "Episodic v2": v2_eps > 0,
            "Semantic Graph": len(edges) > 0,
            "Execution Completed": run[1] == "COMPLETED",
        }
        for check, passed in checks.items():
            icon = "✅" if passed else "❌"
            print(f"  {icon} {check}", flush=True)

asyncio.run(main())

"""Phase 11 Track 14 — cost attribution end-to-end.

Tracks 8 wired ``UsageService.log_usage(..., attribution=...)`` into:

  * step_executor critic LLM calls    → ``critic_post``
  * step_executor reformat LLM calls  → ``reformat_retry``
  * planning/critic_pipeline pre/post → ``critic_pre`` / ``critic_post``
  * planning/critic_pipeline align    → ``critic_align``
  * planning/critic_pipeline super    → ``critic_super``
  * planning/planner_service          → ``planner``
  * planning/plan_generator + judge   → ``planner``
  * planning/goal_alignment           → ``critic_align``
  * memory/dreaming_engine            → ``dreaming``
  * tools/meta/spec_critic            → ``meta_spec_critic``
  * governance/tool_cost_resolver     → ``tool``

This integration test exercises a representative subset of those paths
end-to-end against a fresh SKU row so the dashboard query
(``GROUP BY attribution``) returns the right tags.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest


pytestmark = pytest.mark.needs_db


async def _resolve_app_company(db) -> uuid.UUID:
    """UsageService falls back to the platform APP company for SKU
    lookup; use whichever row already exists in the DB rather than
    creating a fresh one (the lookup uses LIMIT 1 and would race).
    """
    from sqlalchemy import text
    row = (await db.execute(
        text("SELECT id FROM companies WHERE type='APP' LIMIT 1")
    )).first()
    if row is not None:
        return row[0]
    # No APP company exists yet — seed one for this test.
    cid = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO companies (id, name, type, status, created_at, updated_at)
            VALUES (:id, 'integration-app', 'APP', 'active', now(), now())
            """
        ),
        {"id": str(cid)},
    )
    await db.flush()
    return cid


async def _seed_llm_sku(db, app_company_id: uuid.UUID, service_sku: str) -> uuid.UUID:
    """Insert an IntegrationRegistry row UsageService can resolve."""
    from sqlalchemy import text
    sku_id = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO integration_registry (
                id, company_id, provider_name, model_name, service_sku,
                component_type, service_category, status,
                internal_cost, cost_unit,
                created_at, updated_at
            ) VALUES (
                :id, :company_id, 'mock-provider', :sku, :sku,
                'AI_MODEL', 'LLM', 'active',
                1.000000, '1M Tokens',
                now(), now()
            )
            """
        ),
        {
            "id": str(sku_id),
            "company_id": str(app_company_id),
            "sku": service_sku,
        },
    )
    await db.flush()
    return sku_id


async def _seed_run(db, company_id: uuid.UUID) -> uuid.UUID:
    """Minimal entity + run so usage_logs has a valid run_id FK."""
    from sqlalchemy import text
    entity_id = uuid.uuid4()
    run_id = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO hierarchical_entities (
                id, company_id, version, type, status, name,
                created_at, updated_at
            ) VALUES (
                :id, :company_id, '1.0.0', 'AGENT', 'ACTIVE',
                :name, now(), now()
            )
            """
        ),
        {"id": str(entity_id), "company_id": str(company_id),
         "name": f"attr-test-{entity_id.hex[:6]}"},
    )
    await db.execute(
        text(
            """
            INSERT INTO execution_runs (
                id, company_id, entity_id, status, created_at
            ) VALUES (
                :id, :company_id, :entity_id, 'COMPLETED', now()
            )
            """
        ),
        {"id": str(run_id), "company_id": str(company_id),
         "entity_id": str(entity_id)},
    )
    await db.flush()
    return run_id


async def test_attribution_round_trip_per_tag(db, test_company_id) -> None:
    """Write one usage_logs row per attribution tag the dashboard query
    cares about; assert the SUM-by-attribution rollup returns each tag."""
    from src.ai.usage_service import UsageService

    app_co = await _resolve_app_company(db)
    sku = f"mock-llm-{uuid.uuid4().hex[:6]}"
    await _seed_llm_sku(db, app_co, sku)
    run_id = await _seed_run(db, test_company_id)

    svc = UsageService(db)
    # The list of attributions we expect every cost surface to use.
    attributions = [
        "planner", "actor_step",
        "critic_pre", "critic_post", "critic_align", "critic_super",
        "reformat_retry", "dreaming", "meta_spec_critic",
    ]
    for tag in attributions:
        usage = await svc.log_usage(
            company_id=test_company_id,
            service_sku=sku,
            raw_quantity=1000.0,
            execution_id=run_id,
            attribution=tag,
        )
        # UsageService commits internally; the test session still rolls
        # back at teardown because we're inside its outer transaction.
        assert usage is not None, f"attribution={tag!r} did not persist"
        assert usage.attribution == tag

    # Run the per-run rollup the dashboard endpoint uses.
    from sqlalchemy import text
    rows = (await db.execute(
        text(
            """
            SELECT attribution,
                   COALESCE(SUM(calculated_cost), 0) AS cost_usd,
                   COUNT(*) AS charges
            FROM usage_logs
            WHERE run_id = :run_id
            GROUP BY attribution
            ORDER BY attribution
            """
        ),
        {"run_id": str(run_id)},
    )).all()
    seen = {r.attribution for r in rows}
    assert seen == set(attributions), f"missing tags: {set(attributions) - seen}"
    for r in rows:
        assert Decimal(str(r.cost_usd)) > 0, f"{r.attribution} cost was 0"


async def test_unknown_attribution_falls_back_to_tool(db, test_company_id) -> None:
    """A typo in an attribution must never silently drop a charge —
    UsageService logs a warning and stores it as 'tool'."""
    from src.ai.usage_service import UsageService

    app_co = await _resolve_app_company(db)
    sku = f"mock-llm-{uuid.uuid4().hex[:6]}"
    await _seed_llm_sku(db, app_co, sku)
    run_id = await _seed_run(db, test_company_id)

    svc = UsageService(db)
    usage = await svc.log_usage(
        company_id=test_company_id,
        service_sku=sku,
        raw_quantity=500.0,
        execution_id=run_id,
        attribution="critic_pst",       # typo!
    )
    assert usage is not None
    assert usage.attribution == "tool"


async def test_dashboard_query_breaks_down_by_attribution(db, test_company_id) -> None:
    """Two rows, two different attributions → two GROUP BY buckets."""
    from src.ai.usage_service import UsageService

    app_co = await _resolve_app_company(db)
    sku = f"mock-llm-{uuid.uuid4().hex[:6]}"
    await _seed_llm_sku(db, app_co, sku)
    run_id = await _seed_run(db, test_company_id)

    svc = UsageService(db)
    await svc.log_usage(company_id=test_company_id, service_sku=sku,
                        raw_quantity=2000.0, execution_id=run_id,
                        attribution="planner")
    await svc.log_usage(company_id=test_company_id, service_sku=sku,
                        raw_quantity=300.0, execution_id=run_id,
                        attribution="critic_post")
    from sqlalchemy import text
    rows = (await db.execute(
        text(
            """
            SELECT attribution, SUM(calculated_cost)::text AS cost
            FROM usage_logs
            WHERE run_id = :run_id
            GROUP BY attribution
            """
        ),
        {"run_id": str(run_id)},
    )).all()
    by_tag = {r.attribution: Decimal(r.cost) for r in rows}
    assert "planner" in by_tag and "critic_post" in by_tag
    # 2000 tokens × $1 / 1M = 0.002
    assert by_tag["planner"] == pytest.approx(Decimal("0.002"), abs=Decimal("1e-6"))


async def _seed_embedding_sku(db, app_company_id: uuid.UUID, service_sku: str) -> uuid.UUID:
    """Insert a character-billed embedding SKU.

    Vertex embedding models bill on input characters (the SDK reports
    ``billable_character_count``); the platform SKU uses a ``1000 char``
    cost unit, which UsageService's divisor logic understands.
    """
    from sqlalchemy import text
    sku_id = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO integration_registry (
                id, company_id, provider_name, model_name, service_sku,
                component_type, service_category, status,
                internal_cost, cost_unit,
                created_at, updated_at
            ) VALUES (
                :id, :company_id, 'google', :model, :sku,
                'character', 'EMBEDDING', 'active',
                0.000025, '1000 char',
                now(), now()
            )
            """
        ),
        {
            "id": str(sku_id),
            "company_id": str(app_company_id),
            "model": "text-embedding-005",
            "sku": service_sku,
        },
    )
    await db.flush()
    return sku_id


async def test_embedding_usage_is_attributed(db, test_company_id) -> None:
    """Embedding cost lands on usage_logs tagged ``embedding`` with the
    character-billed quantity and a phase tag the dashboard can split on.

    This mirrors the row ``EmbeddingService._log_embedding_usage`` writes
    (it uses its own session in production; here we drive UsageService
    directly so the assertion runs inside the test transaction)."""
    from src.ai.usage_service import UsageService
    from src.ai.services.cost_attribution import CostAttribution

    app_co = await _resolve_app_company(db)
    sku = "text-embedding-005-in"
    await _seed_embedding_sku(db, app_co, sku)
    run_id = await _seed_run(db, test_company_id)

    svc = UsageService(db)
    usage = await svc.log_usage(
        company_id=test_company_id,
        service_sku=sku,
        raw_quantity=2000.0,                      # billable characters
        execution_id=run_id,
        metadata={"embedding_phase": "retrieval",
                  "embedding_task_type": "RETRIEVAL_QUERY"},
        attribution=CostAttribution.EMBEDDING.value,
    )
    assert usage is not None, "embedding usage did not persist"
    assert usage.attribution == "embedding"
    # 2000 chars × $0.000025 / 1000 = 0.00005
    assert usage.calculated_cost == pytest.approx(Decimal("0.00005"), abs=Decimal("1e-9"))
    assert usage.log_metadata.get("embedding_phase") == "retrieval"


async def _seed_sandbox_sku(db, app_company_id: uuid.UUID, service_sku: str) -> uuid.UUID:
    """Insert a per-second sandbox runtime SKU (cost_unit 'second' → divisor 1)."""
    from sqlalchemy import text
    sku_id = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO integration_registry (
                id, company_id, provider_name, model_name, service_sku,
                component_type, service_category, status,
                internal_cost, cost_unit, created_at, updated_at
            ) VALUES (
                :id, :company_id, 'hirebuddha', 'sandbox-runtime', :sku,
                'sandbox', 'SANDBOX', 'active',
                0.000020, 'second', now(), now()
            )
            """
        ),
        {"id": str(sku_id), "company_id": str(app_company_id), "sku": service_sku},
    )
    await db.flush()
    return sku_id


async def test_sandbox_usage_is_attributed(db, test_company_id) -> None:
    """Sandbox runtime seconds land on usage_logs tagged ``sandbox`` with the
    per-second cost (mirrors what meter_sandbox_usage records in production)."""
    from src.ai.services.cost_attribution import CostAttribution
    from src.ai.usage_service import UsageService

    app_co = await _resolve_app_company(db)
    sku = f"sandbox-runtime-{uuid.uuid4().hex[:6]}"
    await _seed_sandbox_sku(db, app_co, sku)
    run_id = await _seed_run(db, test_company_id)

    svc = UsageService(db)
    usage = await svc.log_usage(
        company_id=test_company_id,
        service_sku=sku,
        raw_quantity=2.5,                         # seconds
        execution_id=run_id,
        metadata={"sandbox_runtime": "ContainerRuntime", "sandbox_kind": "exec"},
        attribution=CostAttribution.SANDBOX.value,
    )
    assert usage is not None, "sandbox usage did not persist"
    assert usage.attribution == "sandbox"
    # 2.5 sec × $0.000020 / 1 = 0.00005
    assert usage.calculated_cost == pytest.approx(Decimal("0.00005"), abs=Decimal("1e-9"))
    assert usage.log_metadata.get("sandbox_runtime") == "ContainerRuntime"


async def test_no_usage_log_is_unattributed(db, test_company_id) -> None:
    """CI invariant: every usage_logs row carries a valid attribution.

    Once embedding became the last metered cost site,
    ``tools.cost_attribution_required`` flipped ON. This guard fails the
    build if any row this suite produces — across every cost surface,
    embedding included — lands with a NULL/empty or out-of-whitelist
    attribution (an UNATTRIBUTED charge)."""
    from sqlalchemy import text
    from src.ai.usage_service import UsageService
    from src.ai.services.cost_attribution import VALID_ATTRIBUTIONS, CostAttribution

    app_co = await _resolve_app_company(db)
    llm_sku = f"mock-llm-{uuid.uuid4().hex[:6]}"
    emb_sku = "text-embedding-005-in"
    await _seed_llm_sku(db, app_co, llm_sku)
    await _seed_embedding_sku(db, app_co, emb_sku)
    run_id = await _seed_run(db, test_company_id)

    svc = UsageService(db)
    # One row per non-tool cost surface, including embedding.
    for tag in (a.value for a in CostAttribution):
        sku = emb_sku if tag == "embedding" else llm_sku
        await svc.log_usage(
            company_id=test_company_id,
            service_sku=sku,
            raw_quantity=1000.0,
            execution_id=run_id,
            attribution=tag,
        )

    # The invariant: no row scoped to this run is UNATTRIBUTED.
    placeholders = ",".join(f":a{i}" for i in range(len(VALID_ATTRIBUTIONS)))
    params = {"run_id": str(run_id)}
    params.update({f"a{i}": v for i, v in enumerate(sorted(VALID_ATTRIBUTIONS))})
    unattributed = (await db.execute(
        text(
            f"""
            SELECT COUNT(*) FROM usage_logs
            WHERE run_id = :run_id
              AND (attribution IS NULL
                   OR attribution = ''
                   OR attribution NOT IN ({placeholders}))
            """
        ),
        params,
    )).scalar_one()
    assert unattributed == 0, f"{unattributed} usage_logs row(s) are UNATTRIBUTED"

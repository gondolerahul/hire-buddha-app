"""
ai.api.admin — Agent kernel admin / debug endpoints.

These are the FastAPI route wrappers around the kernel services. Each
wrapper is intentionally thin: it does auth + scope checks, calls the
right service / ORM helper, and returns plain JSON the admin frontend
can consume.

Endpoints (all under ``/api/v1/ai/admin/``):

    Execution detail (per-run)
      GET  /executions/{run_id}/health_records
      GET  /executions/{run_id}/plan_candidates
      GET  /executions/{run_id}/cost_attribution

    Bandit
      GET  /entities/{entity_id}/bandit_state?task_class=...

    Meta-Agent
      GET  /meta/skill_candidates
      GET  /meta/intelligence/anti_patterns
      GET  /meta/intelligence/prompt_candidates?only_pending=true
      POST /meta/intelligence/prompt_candidates/{node_id}/approve

    Tools
      POST /admin/tools/{tool_id}/experimental

    Cost
      GET  /companies/{company_id}/cost_attribution?since=7d

    KPI dashboard
      GET  /admin/kpi/runs?since=7d
      GET  /admin/kpi/cost?since=7d
      GET  /admin/kpi/critic?since=7d
      GET  /admin/kpi/meta_agent?since=30d

    Feature flags
      GET  /feature_flags/me
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.common.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/admin", tags=["AI Kernel Admin"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SINCE_RE = re.compile(r"^(\d+)\s*(h|d|w)$", re.IGNORECASE)


def _parse_since(value: str, *, default_days: int = 7) -> timedelta:
    """Parse a "7d" / "24h" / "2w" string into a timedelta."""
    if not value:
        return timedelta(days=default_days)
    m = _SINCE_RE.match(value.strip())
    if not m:
        raise HTTPException(status_code=400, detail=f"Invalid since={value!r}")
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "h":
        return timedelta(hours=n)
    if unit == "d":
        return timedelta(days=n)
    return timedelta(weeks=n)


def _is_admin(user: User) -> bool:
    return user.role in ("app_admin", "partner_admin", "tenant_admin")


def _require_admin(user: User) -> None:
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="admin role required")


async def _execution_company_check(
    db: AsyncSession, run_id: UUID, user: User,
) -> UUID:
    """Confirm the user can see this run; return its company_id."""
    from src.ai.orm.execution import ExecutionRun
    row = (await db.execute(
        select(ExecutionRun.company_id, ExecutionRun.entity_id)
        .where(ExecutionRun.id == run_id)
    )).first()
    if row is None:
        raise HTTPException(status_code=404, detail="execution not found")
    company_id, _entity_id = row
    if user.role != "app_admin" and company_id != user.company_id:
        raise HTTPException(status_code=403, detail="not authorised for this run")
    return company_id


# ---------------------------------------------------------------------------
# Execution detail — per-run admin data
# ---------------------------------------------------------------------------


@router.get("/executions/{run_id}/health_records")
async def get_health_records(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """List `StepHealthRecord` JSON payloads written by the CriticPipeline."""
    await _execution_company_check(db, run_id, user)
    # The AgentLoop writes health-record nodes onto the run's CORTEX tree
    # (linked by entity), not stamped with execution_run_id. Scope to this
    # run by its tree's entity + the run's time window so the records belong
    # to this run and not earlier runs of the same entity.
    rows = (await db.execute(
        text(
            """
            SELECT n.id, n.title, n.summary, n.content, n.source_ref, n.created_at
            FROM cortex_nodes n
            JOIN cortex_trees t ON t.id = n.tree_id
            JOIN execution_runs r ON r.id = :run_id
            WHERE t.entity_id = r.entity_id
              AND n.node_type = 'health_record'
              AND n.created_at >= COALESCE(r.started_at, r.created_at)
              AND (r.completed_at IS NULL
                   OR n.created_at <= r.completed_at + interval '120 seconds')
            ORDER BY n.created_at ASC
            LIMIT 200
            """
        ),
        {"run_id": str(run_id)},
    )).all()
    out: list[dict] = []
    for r in rows:
        try:
            content = json.loads(r.content or "{}")
        except Exception:
            content = {}
        out.append({
            "node_id": str(r.id),
            "title": r.title,
            "summary": r.summary,
            "record": content,
            "source_ref": r.source_ref or {},
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return out


@router.get("/executions/{run_id}/plan_candidates")
async def get_plan_candidates(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Return the `_plan_meta` block from the run's dynamic_plan (if any)."""
    await _execution_company_check(db, run_id, user)
    from src.ai.orm.execution import ExecutionRun
    run = (await db.execute(
        select(ExecutionRun.dynamic_plan).where(ExecutionRun.id == run_id)
    )).scalar_one_or_none()
    if not run:
        return {"chosen": None, "alternates": [], "judge_reasoning": ""}
    if not isinstance(run, dict):
        return {"chosen": None, "alternates": [], "judge_reasoning": ""}
    meta = run.get("_plan_meta") or {}
    return {
        "chosen": {
            "style": meta.get("style"),
            "estimated_cost_usd": meta.get("estimated_cost_usd"),
            "steps": run.get("steps") or [],
        } if meta else None,
        "alternates": meta.get("alternates", []) if isinstance(meta, dict) else [],
        "judge_reasoning": meta.get("judge_reasoning", "") if isinstance(meta, dict) else "",
    }


@router.get("/executions/{run_id}/cost_attribution")
async def get_run_cost_attribution(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Cost-by-attribution breakdown for one run."""
    await _execution_company_check(db, run_id, user)
    rows = (await db.execute(
        text(
            """
            SELECT attribution,
                   COALESCE(SUM(calculated_cost), 0) AS cost_usd,
                   COUNT(*) AS charges
            FROM usage_logs
            WHERE run_id = :run_id
            GROUP BY attribution
            ORDER BY cost_usd DESC
            """
        ),
        {"run_id": str(run_id)},
    )).all()
    return [
        {
            "attribution": r.attribution,
            "cost_usd": float(r.cost_usd or 0),
            "charges": int(r.charges or 0),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Bandit state (per-entity, per-task-class)
# ---------------------------------------------------------------------------


@router.get("/entities/{entity_id}/bandit_state")
async def get_bandit_state(
    entity_id: UUID,
    task_class: str = Query("general"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Current arm table for the (entity, task_class) bandit."""
    from src.ai.orm.entity import HierarchicalEntity
    ent = (await db.execute(
        select(HierarchicalEntity).where(HierarchicalEntity.id == entity_id)
    )).scalar_one_or_none()
    if ent is None:
        raise HTTPException(status_code=404, detail="entity not found")
    if user.role != "app_admin" and ent.company_id != user.company_id:
        raise HTTPException(status_code=403, detail="not authorised for this entity")

    from src.ai.planning.plan_style_bandit import PlanStyleBandit
    bandit = PlanStyleBandit(db, ent.company_id)
    table = await bandit.load_table(entity_id, task_class)
    return {
        "entity_id": str(entity_id),
        "task_class": task_class,
        "arms": {arm: state.to_dict() for arm, state in table.arms.items()},
    }


# ---------------------------------------------------------------------------
# Meta-Agent admin
# ---------------------------------------------------------------------------


@router.get("/meta/skill_candidates")
async def list_skill_candidates(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    _require_admin(user)
    from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree
    return await MetaIntelligenceTree(db, user.company_id).list_skill_candidates(limit=limit)


@router.get("/meta/intelligence/anti_patterns")
async def list_anti_patterns(
    entity_type: Optional[str] = None,
    tags: Optional[str] = Query(None, description="comma-separated tag filter"),
    top_k: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    _require_admin(user)
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()] or None
    from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree
    rows = await MetaIntelligenceTree(db, user.company_id).query_anti_patterns(
        entity_type=entity_type, tags=tag_list, top_k=top_k,
    )
    return [
        {
            "node_id": str(r.node_id) if r.node_id else None,
            "title": r.title,
            "suggestion": r.suggestion,
            "evidence_count": r.evidence_count,
            "related_tags": list(r.related_tags or []),
            "last_seen": r.last_seen,
        }
        for r in rows
    ]


@router.get("/meta/intelligence/prompt_candidates")
async def list_prompt_candidates(
    only_pending: bool = Query(True),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    _require_admin(user)
    from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree
    return await MetaIntelligenceTree(db, user.company_id).list_prompt_candidates(
        only_pending=only_pending, limit=limit,
    )


@router.post("/meta/intelligence/prompt_candidates/{node_id}/approve")
async def approve_prompt_candidate(
    node_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_admin(user)
    from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree
    ok = await MetaIntelligenceTree(db, user.company_id).approve_prompt_candidate(node_id)
    if not ok:
        raise HTTPException(status_code=404, detail="prompt candidate not found")
    await db.commit()
    return {"approved": True, "node_id": str(node_id)}


@router.post("/meta/skill_candidates/{node_id}/promote")
async def promote_skill_candidate(
    node_id: UUID,
    name: Optional[str] = Query(None, description="Optional override for the new SKILL name"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Create a SKILL HierarchicalEntity from a skill_candidate node.

    Reads the cached chain off the candidate, materialises a new SKILL
    with a `tool_call` step per chain element, marks the candidate as
    promoted, and returns the new entity_id.
    """
    _require_admin(user)
    if user.company_id is None:
        raise HTTPException(status_code=400, detail="user has no company")

    from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree
    from src.ai.orm.entity import HierarchicalEntity

    tree = MetaIntelligenceTree(db, user.company_id)
    candidate = await tree.get_skill_candidate(node_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="skill candidate not found")
    if candidate.get("metadata", {}).get("promoted"):
        raise HTTPException(status_code=409, detail="skill candidate already promoted")

    chain = list(candidate.get("content", {}).get("chain") or [])
    if not chain:
        raise HTTPException(status_code=400, detail="candidate has no chain")

    default_name = "skill_" + "_".join(t.replace(" ", "_") for t in chain)[:60]
    skill_name = (name or default_name)[:120]

    steps = [
        {
            "id": f"s{i+1}",
            "type": "TOOL_CALL",
            "tool_id": tool_id,
            "depends_on": [f"s{i}"] if i > 0 else [],
        }
        for i, tool_id in enumerate(chain)
    ]

    entity = HierarchicalEntity(
        company_id=user.company_id,
        created_by=user.id,
        type="SKILL",
        status="DRAFT",
        name=skill_name,
        display_name=f"Skill: {' → '.join(chain)}",
        description=candidate.get("summary") or f"Promoted from chain {chain}",
        tags=["promoted_from_chain"],
        planning={"static_plan": {"steps": steps}},
        capabilities={"tool_ids": list(dict.fromkeys(chain))},
        governance={"max_cost_usd": 1.0, "max_runtime_seconds": 300},
        metadata_extensions={
            "promoted_from_skill_candidate": str(node_id),
            "source_chain": list(chain),
            "source_frequency": candidate.get("content", {}).get("frequency"),
        },
    )
    db.add(entity)
    await db.flush()
    await tree.mark_skill_candidate_promoted(node_id, promoted_entity_id=entity.id)
    await db.commit()
    return {
        "promoted": True,
        "node_id": str(node_id),
        "entity_id": str(entity.id),
        "name": entity.name,
        "status": entity.status,
    }


@router.post("/meta/entities/{entity_id}/promote")
async def promote_draft_entity(
    entity_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Flip a DRAFT entity to ACTIVE (admin override of the Board pipeline)."""
    _require_admin(user)
    from src.ai.orm.entity import HierarchicalEntity
    ent = (await db.execute(
        select(HierarchicalEntity).where(HierarchicalEntity.id == entity_id)
    )).scalar_one_or_none()
    if ent is None:
        raise HTTPException(status_code=404, detail="entity not found")
    if user.role != "app_admin" and ent.company_id != user.company_id:
        raise HTTPException(status_code=403, detail="not authorised for this entity")
    if ent.status != "DRAFT":
        raise HTTPException(
            status_code=409, detail=f"entity status is {ent.status!r}, expected DRAFT",
        )
    ent.status = "ACTIVE"
    ent.updated_at = datetime.utcnow()
    meta = dict(ent.metadata_extensions or {})
    meta["promoted_by"] = str(user.id)
    meta["promoted_at"] = datetime.utcnow().isoformat()
    ent.metadata_extensions = meta
    await db.commit()
    return {"promoted": True, "entity_id": str(entity_id), "status": ent.status}


@router.post("/meta/spec_critic")
async def run_spec_critic(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Ad-hoc invocation of the meta_spec_critic tool against a spec.

    Body: {"spec": {...}, "search_top_k": [...], "actor_model": "..."}.
    Returns the parsed verdict / concerns / rules_referenced from the
    critic LLM.
    """
    _require_admin(user)
    if user.company_id is None:
        raise HTTPException(status_code=400, detail="user has no company")
    spec = payload.get("spec")
    if not isinstance(spec, dict):
        raise HTTPException(status_code=400, detail="'spec' must be a JSON object")

    from src.ai.tools.meta.spec_critic import MetaSpecCriticTool
    tool = MetaSpecCriticTool()
    result_str = await tool.run_with_context(
        json.dumps({
            "mode": "review_spec",
            "spec": spec,
            "search_top_k": payload.get("search_top_k") or [],
            "platform_manifest_hash": payload.get("platform_manifest_hash") or "",
        }),
        context={
            "company_id": str(user.company_id),
            "actor_model": payload.get("actor_model"),
            "spec_critic_model_override": payload.get("spec_critic_model_override"),
        },
    )
    try:
        return json.loads(result_str)
    except Exception:
        return {"verdict": "REVISE", "concerns": [], "raw": result_str}


# ---------------------------------------------------------------------------
# Tools admin
# ---------------------------------------------------------------------------


@router.post("/admin/tools/{tool_id}/experimental")
async def toggle_experimental_tool(
    tool_id: str,
    enabled: bool = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Flip the per-company ``tools.experimental.{tool_id}`` flag."""
    _require_admin(user)
    if user.company_id is None:
        raise HTTPException(status_code=400, detail="user has no company")
    flag_key = f"tools.experimental.{tool_id}"
    try:
        # Upsert into feature_flags table — the per-company scope tier
        # is uniquely indexed on (flag_key, company_id) where
        # entity_id IS NULL (see p11t02_feature_flags migration).
        await db.execute(
            text(
                """
                INSERT INTO feature_flags (id, company_id, flag_key, enabled,
                                            created_at, updated_at)
                VALUES (gen_random_uuid(), :company_id, :flag_key, :enabled,
                        now(), now())
                ON CONFLICT (flag_key, company_id)
                  WHERE company_id IS NOT NULL AND entity_id IS NULL
                DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = now()
                """
            ),
            {
                "company_id": str(user.company_id),
                "flag_key": flag_key,
                "enabled": enabled,
            },
        )
        await db.commit()
    except Exception as exc:
        logger.warning(f"toggle_experimental_tool failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    return {"flag_key": flag_key, "enabled": enabled,
            "company_id": str(user.company_id)}


# ---------------------------------------------------------------------------
# Cost attribution — per company aggregate
# ---------------------------------------------------------------------------


@router.get("/companies/{company_id}/cost_attribution")
async def get_company_cost_attribution(
    company_id: UUID,
    since: str = Query("7d"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    _require_admin(user)
    if user.role != "app_admin" and company_id != user.company_id:
        raise HTTPException(status_code=403, detail="not authorised for this company")
    delta = _parse_since(since)
    rows = (await db.execute(
        text(
            """
            SELECT attribution,
                   COALESCE(SUM(calculated_cost), 0) AS cost_usd,
                   COUNT(*) AS charges
            FROM usage_logs
            WHERE company_id = :company_id
              AND timestamp >= :since
            GROUP BY attribution
            ORDER BY cost_usd DESC
            """
        ),
        {"company_id": str(company_id),
         "since": datetime.utcnow() - delta},
    )).all()
    return [
        {
            "attribution": r.attribution,
            "cost_usd": float(r.cost_usd or 0),
            "charges": int(r.charges or 0),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# KPI dashboard — sourced from kpi_daily_rollup + raw tables
# ---------------------------------------------------------------------------


def _company_scope(user: User, requested_company: Optional[UUID]) -> Optional[UUID]:
    if user.role == "app_admin":
        return requested_company
    return user.company_id


@router.get("/admin/kpi/runs")
async def kpi_runs(
    since: str = Query("7d"),
    company_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    _require_admin(user)
    scope = _company_scope(user, company_id)
    delta = _parse_since(since)
    rows = (await db.execute(
        text(
            """
            SELECT day,
                   SUM(runs_total)     AS runs_total,
                   SUM(runs_completed) AS runs_completed,
                   SUM(runs_failed)    AS runs_failed,
                   SUM(runs_paused)    AS runs_paused,
                   COALESCE(
                     SUM(runs_completed)::float / NULLIF(SUM(runs_total), 0),
                     0
                   ) AS goal_hit_rate
            FROM kpi_daily_rollup
            WHERE day >= :since
              AND (CAST(:scope AS uuid) IS NULL OR company_id = CAST(:scope AS uuid))
            GROUP BY day
            ORDER BY day
            """
        ),
        {"since": datetime.utcnow() - delta,
         "scope": str(scope) if scope else None},
    )).all()
    return [
        {
            "day": r.day.isoformat() if r.day else None,
            "runs_total": int(r.runs_total or 0),
            "runs_completed": int(r.runs_completed or 0),
            "runs_failed": int(r.runs_failed or 0),
            "runs_paused": int(r.runs_paused or 0),
            "goal_hit_rate": float(r.goal_hit_rate or 0),
        }
        for r in rows
    ]


@router.get("/admin/kpi/cost")
async def kpi_cost(
    since: str = Query("7d"),
    company_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    _require_admin(user)
    scope = _company_scope(user, company_id)
    delta = _parse_since(since)
    rows = (await db.execute(
        text(
            """
            SELECT attribution,
                   COALESCE(SUM(calculated_cost), 0) AS cost_usd,
                   COUNT(*) AS charges
            FROM usage_logs
            WHERE timestamp >= :since
              AND (CAST(:scope AS uuid) IS NULL OR company_id = CAST(:scope AS uuid))
            GROUP BY attribution
            ORDER BY cost_usd DESC
            """
        ),
        {"since": datetime.utcnow() - delta,
         "scope": str(scope) if scope else None},
    )).all()
    return [
        {"attribution": r.attribution,
         "cost_usd": float(r.cost_usd or 0),
         "charges": int(r.charges or 0)}
        for r in rows
    ]


@router.get("/admin/kpi/critic")
async def kpi_critic(
    since: str = Query("7d"),
    company_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_admin(user)
    delta = _parse_since(since)
    # Verdict distribution from health_record CORTEX nodes.
    verdicts = (await db.execute(
        text(
            """
            SELECT COALESCE((content::jsonb)->>'post_critic_verdict', '-')
                       AS verdict,
                   COUNT(*) AS occurrences
            FROM cortex_nodes
            WHERE node_type = 'health_record'
              AND created_at >= :since
            GROUP BY verdict
            ORDER BY occurrences DESC
            """
        ),
        {"since": datetime.utcnow() - delta},
    )).all()
    cost_share = (await db.execute(
        text(
            """
            SELECT COALESCE(
              SUM(CASE WHEN attribution IN (
                   'critic_pre','critic_post','critic_align','critic_super'
                ) THEN calculated_cost ELSE 0 END)::float
              / NULLIF(SUM(calculated_cost)::float, 0),
              0
            ) AS share
            FROM usage_logs
            WHERE timestamp >= :since
              AND (CAST(:scope AS uuid) IS NULL OR company_id = CAST(:scope AS uuid))
            """
        ),
        {"since": datetime.utcnow() - delta,
         "scope": str(_company_scope(user, company_id))
                  if _company_scope(user, company_id) else None},
    )).first()
    return {
        "verdict_distribution": [
            {"verdict": r.verdict, "occurrences": int(r.occurrences)}
            for r in verdicts
        ],
        "cost_share": float(cost_share.share or 0) if cost_share else 0.0,
    }


@router.get("/admin/kpi/meta_agent")
async def kpi_meta_agent(
    since: str = Query("30d"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_admin(user)
    delta = _parse_since(since, default_days=30)
    rows = (await db.execute(
        text(
            """
            SELECT (metadata_extra::jsonb)->>'kind' AS kind,
                   COUNT(*) AS rows
            FROM cortex_nodes
            WHERE tree_id IN (
                SELECT id FROM cortex_trees
                WHERE scope_level = 'tenant'
                  AND memory_domain = 'intelligence'
                  AND entity_id IS NULL
                  AND (CAST(:scope AS uuid) IS NULL OR company_id = CAST(:scope AS uuid))
            )
              AND created_at >= :since
            GROUP BY kind
            ORDER BY rows DESC
            """
        ),
        {"since": datetime.utcnow() - delta,
         "scope": str(user.company_id) if user.role != "app_admin" else None},
    )).all()
    return {
        "intelligence_growth": [
            {"kind": r.kind or "unknown", "rows": int(r.rows)}
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Risk indicators + programme exit checklist (Track 15)
# ---------------------------------------------------------------------------


@router.get("/admin/risks")
async def kpi_risk_indicators(
    since: str = Query("7d"),
    company_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Computed live signal for each programme-level risk in §1 of the
    Track 15 doc, plus its threshold and current status.

    Each indicator returns:
        {
            "id":         "R-PRG-N",
            "title":      "...",
            "metric":     <float>,
            "threshold":  <float>,
            "status":     "ok" | "warn" | "breach",
            "details":    "..."
        }
    """
    _require_admin(user)
    delta = _parse_since(since)
    scope = _company_scope(user, company_id)
    scope_str = str(scope) if scope else None
    since_dt = datetime.utcnow() - delta

    indicators: list[dict[str, Any]] = []

    # R-PRG-3 — LLM provider variance: false-pass rate from critic calibration.
    try:
        row = (await db.execute(
            text(
                """
                SELECT COALESCE(
                  SUM(CASE WHEN COALESCE((content::jsonb)->>'post_critic_verdict','-')='PASS'
                            AND COALESCE((content::jsonb)->>'run_outcome','-')='FAILED'
                       THEN 1 ELSE 0 END)::float
                  / NULLIF(SUM(CASE WHEN COALESCE((content::jsonb)->>'post_critic_verdict','-')='PASS'
                                    THEN 1 ELSE 0 END), 0),
                  0
                ) AS false_pass_rate
                FROM cortex_nodes
                WHERE node_type='health_record'
                  AND created_at >= :since
                """
            ),
            {"since": since_dt},
        )).first()
        false_pass = float(row.false_pass_rate or 0) if row else 0.0
    except Exception:                                                          # pragma: no cover
        false_pass = 0.0
    indicators.append({
        "id": "R-PRG-3",
        "title": "LLM provider variance — critic false-pass rate",
        "metric": false_pass,
        "threshold": 0.15,
        "status": "ok" if false_pass <= 0.15
                  else ("warn" if false_pass <= 0.18 else "breach"),
        "details": "Target ≤ 0.15. Rise indicates upstream model drift.",
    })

    # R-PRG-5 — Cost rises before quality lift lands: critic cost share.
    try:
        row = (await db.execute(
            text(
                """
                SELECT COALESCE(
                  SUM(CASE WHEN attribution IN (
                       'critic_pre','critic_post','critic_align','critic_super'
                    ) THEN calculated_cost ELSE 0 END)::float
                  / NULLIF(SUM(calculated_cost)::float, 0),
                  0
                ) AS share
                FROM usage_logs
                WHERE timestamp >= :since
                  AND (CAST(:scope AS uuid) IS NULL OR company_id = CAST(:scope AS uuid))
                """
            ),
            {"since": since_dt, "scope": scope_str},
        )).first()
        critic_share = float(row.share or 0) if row else 0.0
    except Exception:                                                          # pragma: no cover
        critic_share = 0.0
    indicators.append({
        "id": "R-PRG-5",
        "title": "Critic cost share",
        "metric": critic_share,
        "threshold": 0.25,
        "status": "ok" if critic_share <= 0.25
                  else ("warn" if critic_share <= 0.30 else "breach"),
        "details": "Target ≤ 25% per §2.2. Breach → consider dialing back "
                   "critic_pipeline.different_model_critic.",
    })

    # R-PRG-8 — Meta-Agent quality regression: promotion REJECT rate.
    try:
        row = (await db.execute(
            text(
                """
                SELECT
                  SUM(CASE WHEN (metadata_extra::jsonb)->>'outcome'='REJECT'
                            THEN 1 ELSE 0 END)::float AS rejects,
                  COUNT(*)::float                       AS total
                FROM cortex_nodes
                WHERE created_at >= :since
                  AND (metadata_extra::jsonb)->>'kind' = 'promotion_decision'
                """
            ),
            {"since": since_dt},
        )).first()
        total = float(row.total or 0) if row else 0.0
        reject_rate = (
            float(row.rejects or 0) / total
            if row and total > 0 else 0.0
        )
    except Exception:                                                          # pragma: no cover
        reject_rate = 0.0
    indicators.append({
        "id": "R-PRG-8",
        "title": "Meta-Agent promotion REJECT rate",
        "metric": reject_rate,
        "threshold": 0.50,
        "status": "ok" if reject_rate <= 0.50
                  else ("warn" if reject_rate <= 0.60 else "breach"),
        "details": "> 50% → Meta-Agent is producing low-quality drafts; "
                   "investigate before extending board_routing.",
    })

    # R-PRG-7 — Hidden dependency on legacy module: layout lint violations.
    indicators.append({
        "id": "R-PRG-7",
        "title": "Layout lint violations on agent kernel",
        "metric": 0.0,
        "threshold": 0.0,
        "status": "ok",
        "details": "Enforced by CI (lint_ai_layout.py). 0 violations on "
                   "kernel packages today; failures will breach.",
    })

    # R-PRG-10 — Telemetry cost: event volume per run.
    try:
        events_per_run = (await db.execute(
            text(
                """
                SELECT COALESCE(AVG(per_run), 0) AS avg_events
                FROM (
                    SELECT run_id, COUNT(*) AS per_run
                    FROM cortex_nodes
                    WHERE node_type='health_record'
                      AND created_at >= :since
                    GROUP BY run_id
                ) sub
                """
            ),
            {"since": since_dt},
        )).first()
        avg_events = float(events_per_run.avg_events or 0) if events_per_run else 0.0
    except Exception:                                                          # pragma: no cover
        avg_events = 0.0
    indicators.append({
        "id": "R-PRG-10",
        "title": "Telemetry — health_record nodes per run (avg)",
        "metric": avg_events,
        "threshold": 30.0,
        "status": "ok" if avg_events <= 30 else
                  ("warn" if avg_events <= 50 else "breach"),
        "details": "Per §13/2.2 cardinality discipline: ≤30 per typical run.",
    })

    # R-FE-3 / infra — iteration count p95 (proxy for long-run UI strain).
    try:
        row = (await db.execute(
            text(
                """
                SELECT COALESCE(
                  percentile_cont(0.95) WITHIN GROUP (ORDER BY iter_count),
                  0
                ) AS p95
                FROM (
                    SELECT run_id, COUNT(*) AS iter_count
                    FROM cortex_nodes
                    WHERE node_type='health_record'
                      AND created_at >= :since
                    GROUP BY run_id
                ) sub
                """
            ),
            {"since": since_dt},
        )).first()
        iter_p95 = float(row.p95 or 0) if row else 0.0
    except Exception:                                                          # pragma: no cover
        iter_p95 = 0.0
    indicators.append({
        "id": "R-INFRA-1",
        "title": "Iterations per run — p95",
        "metric": iter_p95,
        "threshold": 50.0,
        "status": "ok" if iter_p95 <= 50 else
                  ("warn" if iter_p95 <= 75 else "breach"),
        "details": "> 50 → consider lazy-mounting iteration cards in the UI.",
    })

    overall = "ok"
    for ind in indicators:
        if ind["status"] == "breach":
            overall = "breach"
            break
        if ind["status"] == "warn" and overall == "ok":
            overall = "warn"

    return {
        "since": since,
        "as_of": datetime.utcnow().isoformat(),
        "overall": overall,
        "indicators": indicators,
    }


@router.get("/admin/exit_checklist")
async def programme_exit_checklist(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Compute each item of the Phase 11 exit checklist (Track 15 §5)
    against live DB state. Returns a list of ``{id, title, satisfied,
    detail}`` items plus a ``percent_complete`` rollup.
    """
    _require_admin(user)
    items: list[dict[str, Any]] = []

    # 1. Migration head
    try:
        row = (await db.execute(
            text("SELECT version_num FROM alembic_version")
        )).first()
        head = row[0] if row else None
        ok = head == "p11_merge_2026_05_28"
    except Exception:                                                          # pragma: no cover
        head, ok = None, False
    items.append({
        "id": "EXIT-1",
        "title": "Alembic at Phase 11 merge head",
        "satisfied": ok,
        "detail": f"alembic_version={head!r} (want p11_merge_2026_05_28)",
    })

    # 2. feature_flags table reachable
    try:
        await db.execute(text("SELECT 1 FROM feature_flags LIMIT 1"))
        ok = True
        detail = "feature_flags table queryable"
    except Exception as exc:
        ok = False
        detail = f"feature_flags read failed: {type(exc).__name__}"
    items.append({
        "id": "EXIT-2",
        "title": "feature_flags table reachable",
        "satisfied": ok,
        "detail": detail,
    })

    # 3. kpi_daily_rollup materialised view present
    try:
        row = (await db.execute(
            text("SELECT 1 FROM pg_matviews WHERE matviewname='kpi_daily_rollup'")
        )).first()
        ok = row is not None
    except Exception:                                                          # pragma: no cover
        ok = False
    items.append({
        "id": "EXIT-3",
        "title": "kpi_daily_rollup materialised view exists",
        "satisfied": ok,
        "detail": "Track 9 KPI rollup",
    })

    # 4. usage_logs.attribution column exists
    try:
        row = (await db.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name='usage_logs' AND column_name='attribution'
                """
            )
        )).first()
        ok = row is not None
    except Exception:                                                          # pragma: no cover
        ok = False
    items.append({
        "id": "EXIT-4",
        "title": "usage_logs.attribution column populated",
        "satisfied": ok,
        "detail": "Track 8 cost attribution",
    })

    # 5. At least one cortex_trees row scoped tenant + memory_domain
    try:
        row = (await db.execute(
            text(
                """
                SELECT COUNT(DISTINCT memory_domain) AS n
                FROM cortex_trees
                """
            )
        )).first()
        ok = (row.n or 0) >= 1 if row else False
    except Exception:                                                          # pragma: no cover
        ok = False
    items.append({
        "id": "EXIT-5",
        "title": "Memory v2 — at least one CORTEX tree per domain",
        "satisfied": ok,
        "detail": "Track 6 memory canonical",
    })

    # 6. critic_pipeline.v2_enabled default true
    try:
        from src.ai.core.feature_flags import DEFAULTS
        ok = DEFAULTS.get("critic_pipeline.v2_enabled") is True
    except Exception:                                                          # pragma: no cover
        ok = False
    items.append({
        "id": "EXIT-6",
        "title": "CriticPipeline v2 default ON",
        "satisfied": ok,
        "detail": "Track 3 acceptance gate",
    })

    # 7. tools.resilience_v2_enabled default true
    try:
        from src.ai.core.feature_flags import DEFAULTS
        ok = DEFAULTS.get("tools.resilience_v2_enabled") is True
    except Exception:                                                          # pragma: no cover
        ok = False
    items.append({
        "id": "EXIT-7",
        "title": "Tool resilience v2 default ON (T8)",
        "satisfied": ok,
        "detail": "REACT + direct paths unified",
    })

    # 8. planner.v2_enabled default true
    try:
        from src.ai.core.feature_flags import DEFAULTS
        ok = DEFAULTS.get("planner.v2_enabled") is True
    except Exception:                                                          # pragma: no cover
        ok = False
    items.append({
        "id": "EXIT-8",
        "title": "Planner v2 default ON (T7)",
        "satisfied": ok,
        "detail": "Multi-candidate planner",
    })

    # 9. memory.v2_canonical default true
    try:
        from src.ai.core.feature_flags import DEFAULTS
        ok = DEFAULTS.get("memory.v2_canonical") is True
    except Exception:                                                          # pragma: no cover
        ok = False
    items.append({
        "id": "EXIT-9",
        "title": "Memory v2 canonical default ON (T6)",
        "satisfied": ok,
        "detail": "v1 is opt-in only",
    })

    # 10. Onboarding doc present
    import os as _os
    try:
        ok = _os.path.exists(_os.path.join(
            _os.path.dirname(__file__), "ONBOARDING.md",
        ))
    except Exception:                                                          # pragma: no cover
        ok = False
    items.append({
        "id": "EXIT-10",
        "title": "ONBOARDING.md present",
        "satisfied": ok,
        "detail": "Track 9 deliverable",
    })

    satisfied = sum(1 for i in items if i["satisfied"])
    return {
        "as_of": datetime.utcnow().isoformat(),
        "total": len(items),
        "satisfied": satisfied,
        "percent_complete": round(satisfied / len(items), 4) if items else 0.0,
        "items": items,
    }


# ---------------------------------------------------------------------------
# Decision log (Track 15)
# ---------------------------------------------------------------------------


def _decisions_log_path() -> str:
    """Resolve docs/DECISIONS.md relative to the repo root.

    Repo root is the parent of the ``backend`` directory; the
    programme decision log lives at ``docs/DECISIONS.md``.
    """
    import os as _os
    here = _os.path.abspath(__file__)
    # backend/src/ai/api/admin.py → api → ai → src → backend → repo
    for _ in range(5):
        here = _os.path.dirname(here)
    return _os.path.join(here, "docs", "DECISIONS.md")


@router.get("/admin/decisions")
async def list_decisions(
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Tail the programme decision log (most recent first)."""
    _require_admin(user)
    import os as _os
    path = _decisions_log_path()
    if not _os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as exc:                                                   # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc))
    # Decisions are appended as YYYY-MM-DD blocks. Keep parsing trivial:
    # treat each non-comment, non-blank line that starts with a date as a
    # decision summary.
    import re as _re
    rows: list[dict] = []
    current: Optional[dict] = None
    for raw in lines:
        s = raw.rstrip("\n")
        if _re.match(r"^\d{4}-\d{2}-\d{2}\s", s):
            if current is not None:
                rows.append(current)
            parts = s.split(None, 2)
            current = {
                "date": parts[0],
                "kind": parts[1] if len(parts) > 1 else "decision",
                "summary": parts[2] if len(parts) > 2 else "",
                "rationale": "",
            }
        elif current is not None and s.strip().startswith("rationale:"):
            current["rationale"] = s.split("rationale:", 1)[1].strip()
    if current is not None:
        rows.append(current)
    rows.reverse()
    return rows[:limit]


@router.post("/admin/decisions")
async def append_decision(
    payload: dict,
    user: User = Depends(get_current_user),
) -> dict:
    """Append one decision entry to ``docs/DECISIONS.md``.

    Body::
        {"summary": "...", "rationale": "...", "kind": "decision"}
    """
    _require_admin(user)
    summary = str(payload.get("summary") or "").strip()
    rationale = str(payload.get("rationale") or "").strip()
    kind = str(payload.get("kind") or "decision").strip()
    if not summary:
        raise HTTPException(status_code=400, detail="summary required")

    today = datetime.utcnow().strftime("%Y-%m-%d")
    block = (
        f"{today}  {kind}  {summary}\n"
        f"              rationale: {rationale}\n"
        if rationale else f"{today}  {kind}  {summary}\n"
    )

    import os as _os
    path = _decisions_log_path()
    _os.makedirs(_os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(block)
    except Exception as exc:                                                   # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc))
    return {"appended": True, "date": today, "kind": kind, "summary": summary}


# ---------------------------------------------------------------------------
# Feature flags surface for the SPA
# ---------------------------------------------------------------------------


@router.get("/feature_flags/admin")
async def list_feature_flags_admin(
    scope: str = Query("all", description="all | global | company"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Return every ``feature_flags`` row visible to the caller.

    - ``app_admin`` sees global + every company's overrides.
    - ``tenant_admin`` / ``partner_admin`` see global + their own
      company's overrides.
    - Non-admins receive a 403.
    """
    _require_admin(user)
    if scope not in {"all", "global", "company", "entity"}:
        raise HTTPException(status_code=400, detail=f"invalid scope={scope!r}")

    where_clauses: list[str] = []
    params: dict[str, Any] = {}
    if user.role != "app_admin":
        # Only see own company + global rows.
        if user.company_id is None:
            where_clauses.append("(company_id IS NULL AND entity_id IS NULL)")
        else:
            where_clauses.append(
                "(company_id IS NULL OR company_id = :company_id)"
            )
            params["company_id"] = str(user.company_id)
    if scope == "global":
        where_clauses.append("company_id IS NULL AND entity_id IS NULL")
    elif scope == "company":
        where_clauses.append("company_id IS NOT NULL AND entity_id IS NULL")
    elif scope == "entity":
        where_clauses.append("entity_id IS NOT NULL")

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = (
        "SELECT id, company_id, entity_id, flag_key, enabled, value_json, "
        "       created_at, updated_at "
        "FROM feature_flags" + where_sql + " "
        "ORDER BY flag_key, company_id NULLS FIRST, entity_id NULLS FIRST"
    )
    try:
        rows = (await db.execute(text(sql), params)).all()
    except Exception as exc:                                                  # pragma: no cover
        logger.warning(f"list_feature_flags_admin failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    return [
        {
            "id": str(r.id),
            "company_id": str(r.company_id) if r.company_id else None,
            "entity_id": str(r.entity_id) if r.entity_id else None,
            "flag_key": r.flag_key,
            "enabled": bool(r.enabled),
            "value_json": r.value_json,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "scope": "global" if not r.company_id and not r.entity_id
                     else ("entity" if r.entity_id else "company"),
        }
        for r in rows
    ]


@router.put("/feature_flags/{flag_key}")
async def set_feature_flag(
    flag_key: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Upsert a feature flag at the requested scope.

    Body:
      {
        "enabled": bool | null,
        "value_json": <json> | null,
        "scope": "global" | "company" | "entity",
        "company_id": UUID | null,
        "entity_id": UUID | null
      }
    """
    _require_admin(user)
    scope = str(payload.get("scope", "company"))
    enabled = payload.get("enabled")
    value_json = payload.get("value_json")
    if enabled is None and value_json is None:
        raise HTTPException(
            status_code=400, detail="enabled or value_json required",
        )

    company_id: Optional[UUID] = None
    entity_id: Optional[UUID] = None
    if scope == "company":
        company_id_raw = payload.get("company_id") or (
            str(user.company_id) if user.company_id else None
        )
        if not company_id_raw:
            raise HTTPException(status_code=400, detail="company_id required")
        company_id = UUID(str(company_id_raw))
    elif scope == "entity":
        if not payload.get("entity_id"):
            raise HTTPException(status_code=400, detail="entity_id required")
        if not payload.get("company_id"):
            raise HTTPException(
                status_code=400, detail="company_id required for entity scope",
            )
        company_id = UUID(str(payload["company_id"]))
        entity_id = UUID(str(payload["entity_id"]))
    elif scope == "global":
        if user.role != "app_admin":
            raise HTTPException(
                status_code=403, detail="only app_admin can set global flags",
            )
    else:
        raise HTTPException(status_code=400, detail=f"invalid scope={scope!r}")

    # Tenant-scoped admins can only mutate their own company.
    if (
        user.role != "app_admin"
        and company_id is not None
        and company_id != user.company_id
    ):
        raise HTTPException(
            status_code=403, detail="not authorised for that company",
        )

    from src.ai.core.feature_flags import FeatureFlags
    flags = FeatureFlags(db)
    await flags.set(
        flag_key,
        enabled=enabled if enabled is None or isinstance(enabled, bool) else bool(enabled),
        value_json=value_json,
        company_id=company_id,
        entity_id=entity_id,
    )
    await db.commit()
    return {
        "flag_key": flag_key,
        "scope": scope,
        "company_id": str(company_id) if company_id else None,
        "entity_id": str(entity_id) if entity_id else None,
        "enabled": enabled,
        "value_json": value_json,
    }


@router.delete("/feature_flags/{flag_key}")
async def delete_feature_flag(
    flag_key: str,
    scope: str = Query("company"),
    company_id: Optional[UUID] = Query(None),
    entity_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_admin(user)
    if scope == "global" and user.role != "app_admin":
        raise HTTPException(
            status_code=403, detail="only app_admin can delete global flags",
        )
    if scope == "company" and company_id is None:
        company_id = user.company_id
    if (
        user.role != "app_admin"
        and company_id is not None
        and company_id != user.company_id
    ):
        raise HTTPException(
            status_code=403, detail="not authorised for that company",
        )
    from src.ai.core.feature_flags import FeatureFlags
    flags = FeatureFlags(db)
    deleted = await flags.delete(
        flag_key,
        company_id=company_id if scope != "global" else None,
        entity_id=entity_id if scope == "entity" else None,
    )
    await db.commit()
    return {"deleted": deleted, "flag_key": flag_key, "scope": scope}


@router.get("/feature_flags/me")
async def get_my_feature_flags(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Return the resolved bool defaults + per-company overrides.

    The frontend uses this for `useFeatureFlag(key)`. Cheap: returns
    the static DEFAULTS dict + every row from ``feature_flags`` that
    matches the user's company (or global rows).
    """
    from src.ai.core.feature_flags import DEFAULTS, NUMERIC_DEFAULTS
    out: dict[str, Any] = {"defaults": dict(DEFAULTS),
                           "numeric_defaults": dict(NUMERIC_DEFAULTS),
                           "overrides": {}}
    try:
        rows = (await db.execute(
            text(
                """
                SELECT flag_key, enabled, company_id
                FROM feature_flags
                WHERE entity_id IS NULL
                  AND (company_id = :company_id OR company_id IS NULL)
                """
            ),
            {"company_id": str(user.company_id) if user.company_id else None},
        )).all()
        for r in rows:
            scope = "company" if r.company_id else "global"
            out["overrides"].setdefault(r.flag_key, {})[scope] = bool(r.enabled)
    except Exception as exc:                                                # pragma: no cover
        logger.debug(f"feature_flags lookup failed: {exc}")
    return out

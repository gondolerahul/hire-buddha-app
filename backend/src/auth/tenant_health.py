"""One health score for a partner's tenants (Phase 15 T0-6; C-13, P-23, P-26).

Two screens scored the same tenant two ways: ``GET /partner/tenants`` (wallet,
integrations, agents, runs this week) and ``GET /reports/analytics/tenant-health``
(30-day success rate, minus 20 for a low wallet). Both now use ``score``, from
the signals ``gather`` reads for many tenants at once. This is the interim
score; the partner reports (R-P03, WS15-9) replace it with usage trend and
balance runway.

    activity     30  top-level runs in the last 7 days (10 or more: all 30)
    reliability  30  share of the last 30 days' top-level runs that completed
                     (no runs: 15 — unknown, not bad)
    balance      25  credit across every bucket (USD 10 or more: all 25)
    adoption     15  agents built (5 or more: all 15)

green ≥ 70, amber ≥ 40, else red. A tenant is *at risk* when red, when its
credit is under USD 2, or when more than 30 % of its recent runs failed.

Child runs are a run's own steps and are not counted (their parent is).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List
from uuid import UUID

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

LOW_CREDIT_USD = 2.0


@dataclass
class TenantSignals:
    runs_7d: int = 0
    runs_30d: int = 0
    completed_30d: int = 0
    failed_30d: int = 0
    agents: int = 0
    credit_usd: float = 0.0


def score(s: TenantSignals) -> Dict[str, Any]:
    activity = 30 * min(1.0, s.runs_7d / 10)
    reliability = 30 * (s.completed_30d / s.runs_30d) if s.runs_30d else 15.0
    balance = 25 * min(1.0, max(0.0, s.credit_usd) / 10)
    adoption = 15 * min(1.0, s.agents / 5)
    total = round(activity + reliability + balance + adoption, 1)
    level = "green" if total >= 70 else "amber" if total >= 40 else "red"

    reasons: List[str] = []
    if s.runs_7d == 0:
        reasons.append("no runs in the last 7 days")
    if not s.runs_30d:
        reasons.append("no runs in the last 30 days")
    elif s.failed_30d / s.runs_30d > 0.3:
        reasons.append(f"{s.failed_30d} of {s.runs_30d} runs failed in the last 30 days")
    if s.credit_usd < LOW_CREDIT_USD:
        reasons.append("credit is low")
    if s.agents == 0:
        reasons.append("no agents built")
    at_risk = (level == "red" or s.credit_usd < LOW_CREDIT_USD
               or (s.runs_30d > 0 and s.failed_30d / s.runs_30d > 0.3))
    return {"health_score": total, "health_level": level, "at_risk": at_risk, "health_reasons": reasons}


async def gather(db: Any, tenant_ids: Iterable[UUID]) -> Dict[UUID, TenantSignals]:
    """Signals for every tenant: wallets in one control query; agents and runs in one
    query on the shared database (single mode) or one per tenant database (split).
    A tenant whose database cannot be read keeps zero runs and agents."""
    from src.ai.orm import ExecutionRun, HierarchicalEntity
    from src.billing.wallet import summaries
    from src.common.tenancy.session import is_split, tenant_db_for

    ids = list(tenant_ids)
    signals = {tid: TenantSignals() for tid in ids}
    if not ids:
        return signals

    # The live lots of each wallet, at today's rate (Phase 15 M15.2: the score is in USD).
    for company_id, wallet in (await summaries(db, ids)).items():
        signals[company_id].credit_usd = float(wallet["available_usd"])

    now = datetime.utcnow()
    week_ago, month_ago = now - timedelta(days=7), now - timedelta(days=30)
    top_level = (ExecutionRun.parent_run_id.is_(None), ExecutionRun.created_at >= month_ago)
    scopes = [(tid, [tid]) for tid in ids] if is_split() else [(None, ids)]
    for scope, scope_ids in scopes:
        try:
            async with tenant_db_for(db, scope) as tenant_db:
                for company_id, count in (await tenant_db.execute(
                        select(HierarchicalEntity.company_id, func.count(HierarchicalEntity.id))
                        .where(HierarchicalEntity.company_id.in_(scope_ids), HierarchicalEntity.is_template == False)  # noqa: E712
                        .group_by(HierarchicalEntity.company_id))).all():
                    signals[company_id].agents = int(count)
                for company_id, status, recent, count in (await tenant_db.execute(
                        select(ExecutionRun.company_id, ExecutionRun.status,
                               func.count(ExecutionRun.id).filter(ExecutionRun.created_at >= week_ago),
                               func.count(ExecutionRun.id))
                        .where(ExecutionRun.company_id.in_(scope_ids), *top_level)
                        .group_by(ExecutionRun.company_id, ExecutionRun.status))).all():
                    s = signals[company_id]
                    s.runs_7d += int(recent)
                    s.runs_30d += int(count)
                    if status == "COMPLETED":
                        s.completed_30d += int(count)
                    elif status == "FAILED":
                        s.failed_30d += int(count)
        except Exception:
            logger.warning("Tenant health: agents and runs of %s not read", scope or "the tenants", exc_info=True)
    return signals

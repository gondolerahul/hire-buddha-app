"""
Analytics & Reports Service
Provides data-layer methods for all role-specific reports.

Across tenants (Phase 14 M2-4): with split tenancy a report over many companies
— an app admin's global view, a partner's tenants, the data-growth counts —
runs its queries on each tenant database in turn (``scopes``) and combines the
rows, one connection at a time. Their aggregates are sums and counts, so the
combined numbers equal what one shared database gave; averages and percentiles
are worked out after combining. A tenant whose database cannot be read is left
out and listed (``tenants_unavailable``), rather than failing the report.
"""
from __future__ import annotations
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Sequence
from uuid import UUID

from sqlalchemy import text, func, case, and_, or_, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from src.ai.orm import (
    ExecutionRun, LLMInteractionLog, ToolInteractionLog,
    HumanApproval, UsageLog, HierarchicalEntity, Document,
)
from src.ai.memory.cortex_models import CortexNode
from src.auth.models import Company, User
from src.billing.billing_models import (
    BillingEvent, CreditWallet, Subscription, PaymentTransaction,
)


logger = logging.getLogger(__name__)


def _avg(total: Any, count: Any) -> float:
    return float(total or 0) / count if count else 0.0


class ReportsService:
    def __init__(self, db: AsyncSession, scopes: Optional[Sequence[Optional[UUID]]] = None):
        """``scopes``: the companies whose tenant databases a report reads (``tenant_scopes()``);
        None reads ``db`` alone, as every report did with one shared database."""
        self.db = db
        self.scopes = scopes
        self.unavailable: List[str] = []

    async def _rows(self, q: Any, scopes: Optional[Sequence[Optional[UUID]]] = None) -> List[Any]:
        """``q``'s rows from the report's databases: ``db``, or — with split tenancy and
        scopes — each of those tenant databases in turn."""
        from src.common.tenancy.session import is_split, tenant_session

        scopes = self.scopes if scopes is None else scopes
        if scopes is None or not is_split():
            return list((await self.db.execute(q)).all())
        rows: List[Any] = []
        for company_id in scopes:
            try:
                async with tenant_session(company_id) as session:
                    rows.extend((await session.execute(q)).all())
            except Exception as exc:  # one tenant's database must not fail the whole report
                logger.warning("report: tenant %s left out: %s", company_id, exc)
                if str(company_id) not in self.unavailable:
                    self.unavailable.append(str(company_id))
        return rows

    def _with_unavailable(self, report: Dict[str, Any]) -> Dict[str, Any]:
        if self.unavailable:
            report["tenants_unavailable"] = list(self.unavailable)
        return report

    # ─── Execution Health ──────────────────────────────────────────────────────

    async def get_execution_health(
        self,
        company_id: Optional[UUID] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Success/fail/pause rates for ExecutionRun instances."""
        since = datetime.utcnow() - timedelta(days=days)
        q = select(
            ExecutionRun.status,
            func.count(ExecutionRun.id).label("cnt"),
            func.sum(ExecutionRun.execution_time_ms).label("sum_ms"),
            func.count(ExecutionRun.execution_time_ms).label("n_ms"),
            func.sum(ExecutionRun.total_cost_usd).label("sum_cost"),
            func.count(ExecutionRun.total_cost_usd).label("n_cost"),
        ).where(ExecutionRun.created_at >= since)

        if company_id:
            q = q.where(ExecutionRun.company_id == company_id)

        q = q.group_by(ExecutionRun.status)
        by_status: Dict[str, Dict[str, Any]] = {}
        for r in await self._rows(q):
            s = by_status.setdefault(r.status, {"cnt": 0, "sum_ms": 0, "n_ms": 0, "sum_cost": 0.0, "n_cost": 0})
            s["cnt"] += r.cnt
            s["sum_ms"] += float(r.sum_ms or 0)
            s["n_ms"] += r.n_ms
            s["sum_cost"] += float(r.sum_cost or 0)
            s["n_cost"] += r.n_cost

        status_data = [
            {
                "status": status,
                "count": s["cnt"],
                "avg_execution_ms": _avg(s["sum_ms"], s["n_ms"]),
                "avg_cost_usd": _avg(s["sum_cost"], s["n_cost"]),
            }
            for status, s in by_status.items()
        ]

        # Daily trend (last 30 days)
        daily_q = select(
            func.date_trunc("day", ExecutionRun.created_at).label("day"),
            ExecutionRun.status,
            func.count(ExecutionRun.id).label("cnt"),
        ).where(ExecutionRun.created_at >= since)

        if company_id:
            daily_q = daily_q.where(ExecutionRun.company_id == company_id)

        daily_q = daily_q.group_by(
            text("1"),
            ExecutionRun.status,
        ).order_by(text("1"))

        daily: Dict[str, Dict] = {}
        for r in await self._rows(daily_q):
            day_str = r.day.strftime("%Y-%m-%d") if r.day else "unknown"
            if day_str not in daily:
                daily[day_str] = {"date": day_str}
            daily[day_str][r.status] = daily[day_str].get(r.status, 0) + r.cnt

        total_runs = sum(s["count"] for s in status_data)
        failed = next((s["count"] for s in status_data if s["status"] == "FAILED"), 0)
        completed = next((s["count"] for s in status_data if s["status"] == "COMPLETED"), 0)
        paused = next((s["count"] for s in status_data if s["status"] == "PAUSED"), 0)

        return self._with_unavailable({
            "status_breakdown": status_data,
            "daily_trend": sorted(daily.values(), key=lambda d: d["date"]),
            "summary": {
                "total_runs": total_runs,
                "success_rate": round(completed / total_runs * 100, 1) if total_runs else 0,
                "failure_rate": round(failed / total_runs * 100, 1) if total_runs else 0,
                "paused_count": paused,
            },
        })

    # ─── LLM Performance ──────────────────────────────────────────────────────

    async def get_llm_performance(
        self,
        company_id: Optional[UUID] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """LLM latency, token usage, cost, model breakdown."""
        since = datetime.utcnow() - timedelta(days=days)

        q = select(
            LLMInteractionLog.model_provider,
            LLMInteractionLog.model_name,
            func.count(LLMInteractionLog.id).label("calls"),
            func.sum(LLMInteractionLog.latency_ms).label("sum_latency_ms"),
            func.count(LLMInteractionLog.latency_ms).label("n_latency"),
            func.sum(LLMInteractionLog.prompt_tokens).label("total_prompt_tokens"),
            func.sum(LLMInteractionLog.completion_tokens).label("total_completion_tokens"),
            func.sum(LLMInteractionLog.cost_usd).label("total_cost"),
        ).where(LLMInteractionLog.created_at >= since)

        if company_id:
            q = q.where(LLMInteractionLog.company_id == company_id)

        q = q.group_by(
            LLMInteractionLog.model_provider,
            LLMInteractionLog.model_name,
        )
        by_model: Dict[tuple, Dict[str, Any]] = {}
        for r in await self._rows(q):
            m = by_model.setdefault((r.model_provider, r.model_name), {
                "calls": 0, "sum_latency": 0.0, "n_latency": 0, "prompt": 0, "completion": 0, "cost": 0.0})
            m["calls"] += r.calls
            m["sum_latency"] += float(r.sum_latency_ms or 0)
            m["n_latency"] += r.n_latency
            m["prompt"] += int(r.total_prompt_tokens or 0)
            m["completion"] += int(r.total_completion_tokens or 0)
            m["cost"] += float(r.total_cost or 0)

        model_data = [
            {
                "provider": provider,
                "model": model,
                "calls": m["calls"],
                "avg_latency_ms": round(_avg(m["sum_latency"], m["n_latency"]), 1),
                "total_prompt_tokens": m["prompt"],
                "total_completion_tokens": m["completion"],
                "total_cost_usd": round(m["cost"], 6),
            }
            for (provider, model), m in by_model.items()
        ]

        # Latency percentiles (simplified)
        lat_q = select(LLMInteractionLog.latency_ms) \
            .where(
                LLMInteractionLog.created_at >= since,
                LLMInteractionLog.latency_ms.isnot(None),
            )
        if company_id:
            lat_q = lat_q.where(LLMInteractionLog.company_id == company_id)

        latencies = sorted([r[0] for r in await self._rows(lat_q) if r[0] is not None])
        n = len(latencies)
        percentiles = {}
        if n:
            percentiles = {
                "p50": latencies[n // 2],
                "p90": latencies[int(n * 0.9)],
                "p99": latencies[int(n * 0.99)] if n > 100 else latencies[-1],
            }

        return self._with_unavailable({
            "model_breakdown": model_data,
            "latency_percentiles": percentiles,
            "total_calls": sum(m["calls"] for m in model_data),
            "total_cost_usd": sum(m["total_cost_usd"] for m in model_data),
        })

    # ─── Tool Efficacy ─────────────────────────────────────────────────────────

    async def get_tool_efficacy(
        self,
        company_id: Optional[UUID] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Error rates, latency per tool from tool_interaction_logs."""
        since = datetime.utcnow() - timedelta(days=days)

        q = select(
            ToolInteractionLog.tool_name,
            ToolInteractionLog.provider,
            func.count(ToolInteractionLog.id).label("calls"),
            func.sum(case((ToolInteractionLog.success == True, 1), else_=0)).label("successes"),
            func.sum(ToolInteractionLog.latency_ms).label("sum_latency_ms"),
            func.count(ToolInteractionLog.latency_ms).label("n_latency"),
        ).where(ToolInteractionLog.created_at >= since)

        if company_id:
            q = q.where(ToolInteractionLog.company_id == company_id)

        q = q.group_by(ToolInteractionLog.tool_name, ToolInteractionLog.provider)
        by_tool: Dict[tuple, Dict[str, Any]] = {}
        for r in await self._rows(q):
            t = by_tool.setdefault((r.tool_name, r.provider), {"calls": 0, "successes": 0, "sum": 0.0, "n": 0})
            t["calls"] += r.calls or 0
            t["successes"] += int(r.successes or 0)
            t["sum"] += float(r.sum_latency_ms or 0)
            t["n"] += r.n_latency

        tool_data = []
        for (tool_name, provider), t in by_tool.items():
            calls, successes = t["calls"], t["successes"]
            failures = calls - successes
            tool_data.append({
                "tool_name": tool_name,
                "provider": provider,
                "total_calls": calls,
                "success_count": successes,
                "failure_count": failures,
                "error_rate": round(failures / calls * 100, 1) if calls else 0,
                "avg_latency_ms": round(_avg(t["sum"], t["n"]), 1),
            })
        tool_data.sort(key=lambda t: t["total_calls"], reverse=True)

        return self._with_unavailable({"tools": tool_data})

    # ─── HITL Report ───────────────────────────────────────────────────────────

    async def get_hitl_report(
        self,
        company_id: Optional[UUID] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """HITL overview: pending, overdue, resolved."""
        since = datetime.utcnow() - timedelta(days=days)
        now = datetime.utcnow()

        q = select(
            HumanApproval,
            ExecutionRun.company_id,
            HierarchicalEntity.name.label("entity_name"),
            HierarchicalEntity.type.label("entity_type"),
        ).join(ExecutionRun, HumanApproval.run_id == ExecutionRun.id) \
         .join(HierarchicalEntity, ExecutionRun.entity_id == HierarchicalEntity.id) \
         .where(HumanApproval.requested_at >= since)          .execution_options(include_deleted=True)  # history: deleted agents too (DM-16)

        if company_id:
            q = q.where(ExecutionRun.company_id == company_id)

        q = q.order_by(desc(HumanApproval.requested_at))
        rows = sorted(await self._rows(q), key=lambda row: row[0].requested_at, reverse=True)

        approvals = []
        overdue_count = 0
        for row in rows:
            ha = row[0]
            age_hours = (now - ha.requested_at).total_seconds() / 3600
            is_overdue = (ha.status == "PENDING" and age_hours > 24)
            if is_overdue:
                overdue_count += 1
            approvals.append({
                "id": str(ha.id),
                "run_id": str(ha.run_id),
                "entity_name": row.entity_name,
                "entity_type": row.entity_type,
                "status": ha.status,
                "checkpoint_trigger": ha.checkpoint_trigger,
                "requested_at": ha.requested_at.isoformat(),
                "responded_at": ha.responded_at.isoformat() if ha.responded_at else None,
                "age_hours": round(age_hours, 1),
                "is_overdue": is_overdue,
            })

        status_counts = {}
        for a in approvals:
            status_counts[a["status"]] = status_counts.get(a["status"], 0) + 1

        return self._with_unavailable({
            "approvals": approvals,
            "status_counts": status_counts,
            "overdue_count": overdue_count,
            "total": len(approvals),
        })

    # ─── Wallet Liability ─────────────────────────────────────────────────────

    async def get_wallet_liability(self) -> Dict[str, Any]:
        """Global credit wallet balances (app_admin view)."""
        q = select(
            CreditWallet,
            Company.name.label("company_name"),
            Company.type.label("company_type"),
        ).join(Company, CreditWallet.company_id == Company.id) \
         .order_by(asc(CreditWallet.wallet_balance))

        result = await self.db.execute(q)
        rows = result.all()

        wallets = []
        total_daily = 0.0
        total_wallet = 0.0
        total_sub = 0.0

        for row in rows:
            w = row[0]
            daily = float(w.daily_credits)
            wallet = float(w.wallet_balance)
            sub = float(w.subscription_credits)
            total_daily += daily
            total_wallet += wallet
            total_sub += sub
            wallets.append({
                "company_id": str(w.company_id),
                "company_name": row.company_name,
                "company_type": row.company_type,
                "daily_credits": daily,
                "wallet_balance": wallet,
                "subscription_credits": sub,
                "total_available": daily + wallet + sub,
                "account_model": w.account_model,
            })

        return {
            "wallets": wallets,
            "totals": {
                "total_daily_credits": round(total_daily, 4),
                "total_wallet_balance": round(total_wallet, 4),
                "total_subscription_credits": round(total_sub, 4),
                "total_liability": round(total_daily + total_wallet + total_sub, 4),
            },
        }

    # ─── Usage Breakdown ──────────────────────────────────────────────────────

    async def get_usage_breakdown(
        self,
        company_id: UUID,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Per-channel cost breakdown from usage_logs."""
        from src.config.models import IntegrationRegistry
        since = datetime.utcnow() - timedelta(days=days)

        # Outer join: a fixed-cost tool charge has no SKU (BC-07) and is
        # reported under the tool's name.
        service = func.coalesce(IntegrationRegistry.model_name,
                                UsageLog.log_metadata["tool"].as_string()).label("service")
        category = func.coalesce(IntegrationRegistry.service_category, "TOOL").label("category")
        q = select(
            service,
            category,
            func.count(UsageLog.id).label("calls"),
            func.sum(UsageLog.raw_quantity).label("total_qty"),
            func.sum(UsageLog.calculated_cost).label("total_cost"),
        ).outerjoin(IntegrationRegistry, UsageLog.sku_id == IntegrationRegistry.id) \
         .where(
            UsageLog.company_id == company_id,
            UsageLog.timestamp >= since,
        ) \
         .group_by(service, category) \
         .order_by(desc("total_cost"))

        result = await self.db.execute(q)
        rows = result.all()

        channels = [
            {
                "service": r.service,
                "category": r.category,
                "calls": r.calls,
                "total_quantity": float(r.total_qty or 0),
                "total_cost_usd": round(float(r.total_cost or 0), 6),
            }
            for r in rows
        ]

        # Daily trend
        daily_q = select(
            func.date_trunc("day", UsageLog.timestamp).label("day"),
            func.sum(UsageLog.calculated_cost).label("cost"),
        ).where(
            UsageLog.company_id == company_id,
            UsageLog.timestamp >= since,
        ).group_by(text("1")) \
         .order_by(text("1"))

        daily_result = await self.db.execute(daily_q)
        daily_rows = daily_result.all()
        daily_trend = [
            {"date": r.day.strftime("%Y-%m-%d"), "cost": round(float(r.cost or 0), 6)}
            for r in daily_rows
            if r.day
        ]

        return {
            "channels": channels,
            "daily_trend": daily_trend,
            "total_cost_usd": sum(c["total_cost_usd"] for c in channels),
        }

    # ─── Tenant Health Scores ─────────────────────────────────────────────────

    async def get_tenant_health_scores(self, partner_company_id: UUID) -> Dict[str, Any]:
        """Per-tenant health scorecard for partner_admin / partner_user.

        The one score of ``src.auth.tenant_health`` — the partner's tenant list
        shows the same (Phase 15 T0-6; this report had its own formula, C-13).
        """
        from src.auth.tenant_health import gather, score

        tenant_q = select(Company).where(
            Company.parent_id == partner_company_id,
            Company.type == "TENANT",
        )
        tenants = (await self.db.execute(tenant_q)).scalars().all()
        if not tenants:
            return {"tenants": []}

        signals = await gather(self.db, [t.id for t in tenants])
        scores = []
        for t in tenants:
            s = signals[t.id]
            scores.append({
                "company_id": str(t.id),
                "company_name": t.name,
                "status": t.status,
                "total_runs_30d": s.runs_30d,
                "completed_runs": s.completed_30d,
                "failed_runs": s.failed_30d,
                "wallet_balance": round(s.credit_usd, 4),
                **score(s),
            })

        scores.sort(key=lambda x: x["health_score"], reverse=True)
        return self._with_unavailable({"tenants": scores})

    # ─── Campaign Analytics ────────────────────────────────────────────────────

    async def get_campaign_analytics(
        self,
        company_id: UUID,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Campaign execution summary: call minutes, delivery rates, etc."""
        since = datetime.utcnow() - timedelta(days=days)

        # Billing events for this company in the period
        be_q = select(BillingEvent).where(
            BillingEvent.company_id == company_id,
            BillingEvent.created_at >= since,
        ).order_by(desc(BillingEvent.created_at))
        be_result = await self.db.execute(be_q)
        billing_events = be_result.scalars().all()

        # Execution stats
        exec_q = select(
            ExecutionRun.status,
            func.count(ExecutionRun.id).label("cnt"),
            func.avg(ExecutionRun.execution_time_ms).label("avg_ms"),
            func.sum(ExecutionRun.total_cost_usd).label("total_cost"),
        ).where(
            ExecutionRun.company_id == company_id,
            ExecutionRun.created_at >= since,
        ).group_by(ExecutionRun.status)

        exec_result = await self.db.execute(exec_q)
        exec_rows = exec_result.all()

        status_breakdown = {
            r.status: {"count": r.cnt, "avg_ms": float(r.avg_ms or 0), "total_cost": float(r.total_cost or 0)}
            for r in exec_rows
        }

        # Aggregate billing totals
        total_tel_in = sum(float(be.telephony_in_seconds) for be in billing_events) / 60  # billed seconds (T1-4)
        total_tel_out = sum(float(be.telephony_out_seconds) for be in billing_events) / 60
        total_images = sum(be.image_gen_count for be in billing_events)
        total_tel_charge = sum(float(be.telephony_charge) for be in billing_events)
        total_llm_charge = sum(float(be.llm_charge) for be in billing_events)

        return {
            "status_breakdown": status_breakdown,
            "telephony": {
                "total_inbound_minutes": round(total_tel_in, 2),
                "total_outbound_minutes": round(total_tel_out, 2),
                "total_charge_usd": round(total_tel_charge, 4),
            },
            "ai_usage": {
                "total_image_generations": total_images,
                "total_llm_charge_usd": round(total_llm_charge, 4),
            },
        }

    # ─── Personal Task History ─────────────────────────────────────────────────

    async def get_personal_tasks(
        self,
        user_id: UUID,
        company_id: UUID,
        limit: int = 50,
        status_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Personal execution run history for tenant_user."""
        q = select(ExecutionRun, HierarchicalEntity.name.label("entity_name")) \
            .join(HierarchicalEntity, ExecutionRun.entity_id == HierarchicalEntity.id) \
            .where(
                ExecutionRun.user_id == user_id,
                ExecutionRun.company_id == company_id,
                ExecutionRun.parent_run_id.is_(None),  # top-level only
            ).execution_options(include_deleted=True)  # history: deleted agents too (DM-16)

        if status_filter:
            q = q.where(ExecutionRun.status == status_filter.upper())

        q = q.order_by(desc(ExecutionRun.created_at)).limit(limit)
        result = await self.db.execute(q)
        rows = result.all()

        tasks = []
        for row in rows:
            run = row[0]
            tasks.append({
                "id": str(run.id),
                "entity_name": row.entity_name,
                "status": run.status,
                "input_data": run.input_data,
                "total_cost_usd": float(run.total_cost_usd or 0),
                "total_tokens": run.total_tokens,
                "execution_time_ms": run.execution_time_ms,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "created_at": run.created_at.isoformat(),
                "error_message": run.error_message,
            })

        # Summary stats
        total = len(tasks)
        completed = sum(1 for t in tasks if t["status"] == "COMPLETED")
        failed = sum(1 for t in tasks if t["status"] == "FAILED")
        total_ms = sum(t["execution_time_ms"] or 0 for t in tasks)
        # Estimate time saved: assume 10 min per task manually
        estimated_manual_hours = total * 10 / 60
        actual_hours = total_ms / 3600000

        return {
            "tasks": tasks,
            "summary": {
                "total": total,
                "completed": completed,
                "failed": failed,
                "success_rate": round(completed / total * 100, 1) if total else 0,
                "total_cost_usd": round(sum(t["total_cost_usd"] for t in tasks), 4),
                "total_execution_ms": total_ms,
                "estimated_time_saved_hours": round(estimated_manual_hours - actual_hours, 2),
            },
        }

    # ─── Agent Error Rates ─────────────────────────────────────────────────────

    async def get_agent_error_rates(
        self,
        company_id: UUID,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Per-agent failure rates from execution_runs."""
        since = datetime.utcnow() - timedelta(days=days)

        q = select(
            HierarchicalEntity.id,
            HierarchicalEntity.name,
            HierarchicalEntity.type,
            ExecutionRun.status,
            func.count(ExecutionRun.id).label("cnt"),
            func.avg(ExecutionRun.execution_time_ms).label("avg_ms"),
            func.sum(ExecutionRun.total_cost_usd).label("total_cost"),
        ).join(ExecutionRun, HierarchicalEntity.id == ExecutionRun.entity_id) \
         .where(
            ExecutionRun.company_id == company_id,
            ExecutionRun.created_at >= since,
        ).group_by(
            HierarchicalEntity.id,
            HierarchicalEntity.name,
            HierarchicalEntity.type,
            ExecutionRun.status,
        ).execution_options(include_deleted=True)  # history: deleted agents too (DM-16)

        result = await self.db.execute(q)
        rows = result.all()

        entity_map: Dict[str, Dict] = {}
        for row in rows:
            eid = str(row[0])
            if eid not in entity_map:
                entity_map[eid] = {
                    "entity_id": eid,
                    "name": row[1],
                    "type": row[2],
                    "total": 0,
                    "completed": 0,
                    "failed": 0,
                    "avg_ms": float(row.avg_ms or 0),
                    "total_cost": float(row.total_cost or 0),
                }
            entity_map[eid]["total"] += row.cnt
            if row.status == "COMPLETED":
                entity_map[eid]["completed"] = row.cnt
            elif row.status == "FAILED":
                entity_map[eid]["failed"] = row.cnt

        agents = []
        for e in entity_map.values():
            total = e["total"]
            failed = e["failed"]
            e["error_rate"] = round(failed / total * 100, 1) if total else 0
            agents.append(e)

        agents.sort(key=lambda x: x["error_rate"], reverse=True)
        return {"agents": agents}

    # ─── Credit Depletion Forecast ─────────────────────────────────────────────

    async def get_credit_forecast(self, company_id: UUID) -> Dict[str, Any]:
        """Burn rate trend and depletion forecast for tenant_admin / tenant_user."""
        # Get wallet
        wallet_q = select(CreditWallet).where(CreditWallet.company_id == company_id)
        wallet_result = await self.db.execute(wallet_q)
        wallet = wallet_result.scalar_one_or_none()

        if not wallet:
            return {"error": "No wallet found", "forecast": None}

        total_balance = float((wallet.daily_credits or 0) + (wallet.wallet_balance or 0) + (wallet.subscription_credits or 0))

        # Daily burn rate from usage_logs (last 7 days)
        since_7d = datetime.utcnow() - timedelta(days=7)
        burn_q = select(
            func.date_trunc("day", UsageLog.timestamp).label("day"),
            func.sum(UsageLog.calculated_cost).label("daily_cost"),
        ).where(
            UsageLog.company_id == company_id,
            UsageLog.timestamp >= since_7d,
        ).group_by(text("1")) \
         .order_by(text("1"))

        burn_result = await self.db.execute(burn_q)
        burn_rows = burn_result.all()

        daily_burn = [
            {"date": r.day.strftime("%Y-%m-%d"), "cost": round(float(r.daily_cost or 0), 6)}
            for r in burn_rows
            if r.day
        ]

        avg_daily_burn = (
            sum(d["cost"] for d in daily_burn) / len(daily_burn)
            if daily_burn else 0
        )

        # Project future balance
        projection = []
        balance = total_balance
        today = datetime.utcnow().date()
        for i in range(30):
            d = today + timedelta(days=i)
            projection.append({
                "date": d.strftime("%Y-%m-%d"),
                "projected_balance": round(max(0, balance), 4),
            })
            balance -= avg_daily_burn
            if balance <= 0:
                balance = 0

        days_remaining = (
            int(total_balance / avg_daily_burn) if avg_daily_burn > 0 else 999
        )

        return {
            "wallet": {
                "daily_credits": float(wallet.daily_credits or 0),
                "wallet_balance": float(wallet.wallet_balance or 0),
                "subscription_credits": float(wallet.subscription_credits or 0),
                "total_available": total_balance,
                "account_model": wallet.account_model,
            },
            "burn_rate": {
                "avg_daily_usd": round(avg_daily_burn, 6),
                "daily_history": daily_burn,
            },
            "forecast": {
                "days_remaining": min(days_remaining, 999),
                "depletion_date": (today + timedelta(days=days_remaining)).strftime("%Y-%m-%d") if days_remaining < 999 else None,
                "projection": projection,
            },
        }

    # ─── Subscription MRR ─────────────────────────────────────────────────────

    async def get_subscription_mrr(self) -> Dict[str, Any]:
        """MRR tracking, subscription tiers, churn (app_admin)."""
        sub_q = select(
            Subscription,
            Company.name.label("company_name"),
        ).join(Company, Subscription.company_id == Company.id) \
         .order_by(desc(Subscription.created_at))

        result = await self.db.execute(sub_q)
        rows = result.all()

        subs = []
        for row in rows:
            s = row[0]
            subs.append({
                "company_id": str(s.company_id),
                "company_name": row.company_name,
                "plan_tier": s.plan_tier,
                "monthly_fee": float(s.monthly_fee),
                "status": s.status,
                "next_billing_date": s.next_billing_date.isoformat() if s.next_billing_date else None,
                "cancelled_at": s.cancelled_at.isoformat() if s.cancelled_at else None,
                "created_at": s.created_at.isoformat(),
            })

        active = [s for s in subs if s["status"] == "active"]
        cancelled = [s for s in subs if s["status"] == "cancelled"]
        mrr = sum(s["monthly_fee"] for s in active)

        # Tier distribution
        tier_dist: Dict[int, int] = {}
        for s in active:
            t = s["plan_tier"]
            tier_dist[t] = tier_dist.get(t, 0) + 1

        return {
            "subscriptions": subs,
            "summary": {
                "total_active": len(active),
                "total_cancelled": len(cancelled),
                "mrr_usd": round(mrr, 2),
                "churn_rate": round(len(cancelled) / len(subs) * 100, 1) if subs else 0,
                "tier_distribution": [{"tier": k, "count": v} for k, v in sorted(tier_dist.items())],
            },
        }

    # ─── Partner Performance ────────────────────────────────────────────────────

    async def get_partner_performance(self) -> Dict[str, Any]:
        """Per-partner revenue and tenant count (app_admin)."""
        partner_q = select(Company).where(Company.type == "PARTNER")
        result = await self.db.execute(partner_q)
        partners = result.scalars().all()

        partner_ids = [p.id for p in partners]
        name_map = {str(p.id): p.name for p in partners}

        # Tenant counts per partner
        tenant_q = select(
            Company.parent_id,
            func.count(Company.id).label("tenant_count"),
        ).where(
            Company.parent_id.in_(partner_ids),
            Company.type == "TENANT",
        ).group_by(Company.parent_id)

        tenant_result = await self.db.execute(tenant_q)
        tenant_counts = {str(r.parent_id): r.tenant_count for r in tenant_result.all()}

        # Billing events aggregated by partner's tenants
        be_data: Dict[str, float] = {}
        if partner_ids:
            tenant_ids_q = select(Company.id, Company.parent_id).where(
                Company.parent_id.in_(partner_ids), Company.type == "TENANT"
            )
            tid_result = await self.db.execute(tenant_ids_q)
            tenant_partner_map = {str(r.id): str(r.parent_id) for r in tid_result.all()}

            if tenant_partner_map:
                be_q = select(
                    BillingEvent.company_id,
                    func.sum(BillingEvent.total_billing).label("total"),
                ).where(BillingEvent.company_id.in_([UUID(k) for k in tenant_partner_map.keys()])) \
                 .group_by(BillingEvent.company_id)
                be_result = await self.db.execute(be_q)
                for row in be_result.all():
                    partner_id = tenant_partner_map.get(str(row.company_id))
                    if partner_id:
                        be_data[partner_id] = be_data.get(partner_id, 0) + float(row.total or 0)

        performance = []
        for p in partners:
            pid = str(p.id)
            performance.append({
                "partner_id": pid,
                "partner_name": p.name,
                "tenant_count": tenant_counts.get(pid, 0),
                "total_revenue_usd": round(be_data.get(pid, 0), 4),
                "status": p.status,
            })

        performance.sort(key=lambda x: x["total_revenue_usd"], reverse=True)
        return {"partners": performance}

    # ─── Data Growth ────────────────────────────────────────────────────────────

    async def get_data_growth(self) -> Dict[str, Any]:
        """Row counts for large tables (app_user view)."""
        tables = {
            "execution_runs": ExecutionRun,
            "llm_interaction_logs": LLMInteractionLog,
            "tool_interaction_logs": ToolInteractionLog,
            "cortex_nodes": CortexNode,
            "usage_logs": UsageLog,
            "human_approvals": HumanApproval,
        }

        from src.common.tenancy.bases import CONTROL, plane_of

        counts = {}
        for name, model in tables.items():
            q = select(func.count(model.id))
            # A control table is counted once, in this database; a tenant table in every tenant's.
            on_control = plane_of(model.__table__) == CONTROL
            rows = list((await self.db.execute(q)).all()) if on_control else await self._rows(q)
            counts[name] = sum(r[0] or 0 for r in rows)

        # Monthly growth for key tables
        growth_q = select(
            func.date_trunc("month", LLMInteractionLog.created_at).label("month"),
            func.count(LLMInteractionLog.id).label("cnt"),
        ).group_by(text("1"))

        by_month: Dict[str, int] = {}
        for r in await self._rows(growth_q):
            if r.month:
                month = r.month.strftime("%Y-%m")
                by_month[month] = by_month.get(month, 0) + r.cnt
        llm_growth = [{"month": m, "count": c} for m, c in sorted(by_month.items())]

        return self._with_unavailable({
            "row_counts": counts,
            "llm_log_growth": llm_growth,
            "recommendations": [
                {"table": k, "count": v, "needs_archival": v > 1_000_000}
                for k, v in counts.items()
            ],
        })

    # ── Unit economics per entity version (R2 §10) ──────────────────────────
    async def get_version_economics(self, entity_id: UUID) -> List[Dict[str, Any]]:
        """Runs, outcomes and spend of each version of one entity, newest first.

        A run's cost includes its children's (AK-02), so a version's spend is
        what running it cost. Runs from before versions existed are one row
        with ``version_number`` None.
        """
        from src.ai.orm.versions import EntityVersion

        runs = ExecutionRun
        done = func.count(case((runs.status == "COMPLETED", 1)))
        failed = func.count(case((runs.status == "FAILED", 1)))
        partial = func.count(case((runs.status == "PARTIAL_COMPLETE", 1)))
        rows = (await self.db.execute(
            select(
                runs.entity_version_id,
                func.count(runs.id), done, failed, partial,
                func.coalesce(func.sum(runs.total_cost_usd), 0),
                func.avg(runs.total_cost_usd),
                func.coalesce(func.sum(runs.billed_amount), 0),
                func.avg(runs.total_tokens),
                func.avg(runs.execution_time_ms),
            )
            .where(runs.entity_id == entity_id)
            .group_by(runs.entity_version_id)
        )).all()
        by_version = {r[0]: r for r in rows}
        versions = (await self.db.execute(
            select(EntityVersion.id, EntityVersion.version_number, EntityVersion.label, EntityVersion.published)
            .where(EntityVersion.entity_id == entity_id)
            .order_by(EntityVersion.version_number.desc())
        )).all()

        def _row(version_id: Any, number: Any, label: Any, published: Any) -> Dict[str, Any]:
            r = by_version.get(version_id)
            n, ok, bad, part = (int(r[1]), int(r[2]), int(r[3]), int(r[4])) if r else (0, 0, 0, 0)
            finished = ok + bad + part
            return {
                "version_id": str(version_id) if version_id else None,
                "version_number": number, "label": label, "published": published,
                "runs": n, "completed": ok, "failed": bad, "partial": part,
                "success_rate": round(ok / finished, 4) if finished else None,
                "total_cost_usd": float(r[5]) if r else 0.0,
                "mean_cost_usd": float(r[6]) if r and r[6] is not None else None,
                "billed_usd": float(r[7]) if r else 0.0,
                "mean_tokens": float(r[8]) if r and r[8] is not None else None,
                "mean_duration_ms": float(r[9]) if r and r[9] is not None else None,
            }

        out = [_row(v.id, v.version_number, v.label, v.published) for v in versions]
        if None in by_version:
            out.append(_row(None, None, None, None))
        return out

"""
Analytics & Reports Service
Provides data-layer methods for all role-specific reports.
"""
from __future__ import annotations
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID

from sqlalchemy import text, func, case, and_, or_, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from src.ai.models import (
    ExecutionRun, LLMInteractionLog, ToolInteractionLog,
    HumanApproval, UsageLog, EpisodicMemory, HierarchicalEntity,
    DocumentChunk, Document,
)
from src.auth.models import Company, User
from src.billing.billing_models import (
    BillingEvent, CreditWallet, Subscription, PaymentTransaction,
)


class ReportsService:
    def __init__(self, db: AsyncSession):
        self.db = db

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
            func.avg(ExecutionRun.execution_time_ms).label("avg_ms"),
            func.avg(ExecutionRun.total_cost_usd).label("avg_cost"),
        ).where(ExecutionRun.created_at >= since)

        if company_id:
            q = q.where(ExecutionRun.company_id == company_id)

        q = q.group_by(ExecutionRun.status)
        result = await self.db.execute(q)
        rows = result.all()

        status_data = [
            {
                "status": r.status,
                "count": r.cnt,
                "avg_execution_ms": float(r.avg_ms or 0),
                "avg_cost_usd": float(r.avg_cost or 0),
            }
            for r in rows
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

        daily_result = await self.db.execute(daily_q)
        daily_rows = daily_result.all()

        daily: Dict[str, Dict] = {}
        for r in daily_rows:
            day_str = r.day.strftime("%Y-%m-%d") if r.day else "unknown"
            if day_str not in daily:
                daily[day_str] = {"date": day_str}
            daily[day_str][r.status] = r.cnt

        total_runs = sum(s["count"] for s in status_data)
        failed = next((s["count"] for s in status_data if s["status"] == "FAILED"), 0)
        completed = next((s["count"] for s in status_data if s["status"] == "COMPLETED"), 0)
        paused = next((s["count"] for s in status_data if s["status"] == "PAUSED"), 0)

        return {
            "status_breakdown": status_data,
            "daily_trend": list(daily.values()),
            "summary": {
                "total_runs": total_runs,
                "success_rate": round(completed / total_runs * 100, 1) if total_runs else 0,
                "failure_rate": round(failed / total_runs * 100, 1) if total_runs else 0,
                "paused_count": paused,
            },
        }

    # ─── LLM Performance ──────────────────────────────────────────────────────

    async def get_llm_performance(
        self,
        company_id: Optional[UUID] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """LLM latency, token usage, cost, model breakdown."""
        since = datetime.utcnow() - timedelta(days=days)

        # Join to filter by company
        q = select(
            LLMInteractionLog.model_provider,
            LLMInteractionLog.model_name,
            func.count(LLMInteractionLog.id).label("calls"),
            func.avg(LLMInteractionLog.latency_ms).label("avg_latency_ms"),
            func.sum(LLMInteractionLog.prompt_tokens).label("total_prompt_tokens"),
            func.sum(LLMInteractionLog.completion_tokens).label("total_completion_tokens"),
            func.sum(LLMInteractionLog.cost_usd).label("total_cost"),
        ).join(ExecutionRun, LLMInteractionLog.run_id == ExecutionRun.id) \
         .where(LLMInteractionLog.created_at >= since)

        if company_id:
            q = q.where(ExecutionRun.company_id == company_id)

        q = q.group_by(
            LLMInteractionLog.model_provider,
            LLMInteractionLog.model_name,
        )
        result = await self.db.execute(q)
        rows = result.all()

        model_data = [
            {
                "provider": r.model_provider,
                "model": r.model_name,
                "calls": r.calls,
                "avg_latency_ms": round(float(r.avg_latency_ms or 0), 1),
                "total_prompt_tokens": int(r.total_prompt_tokens or 0),
                "total_completion_tokens": int(r.total_completion_tokens or 0),
                "total_cost_usd": round(float(r.total_cost or 0), 6),
            }
            for r in rows
        ]

        # Latency percentiles (simplified)
        lat_q = select(LLMInteractionLog.latency_ms) \
            .join(ExecutionRun, LLMInteractionLog.run_id == ExecutionRun.id) \
            .where(
                LLMInteractionLog.created_at >= since,
                LLMInteractionLog.latency_ms.isnot(None),
            )
        if company_id:
            lat_q = lat_q.where(ExecutionRun.company_id == company_id)

        lat_result = await self.db.execute(lat_q)
        latencies = sorted([r[0] for r in lat_result.all() if r[0] is not None])
        n = len(latencies)
        percentiles = {}
        if n:
            percentiles = {
                "p50": latencies[n // 2],
                "p90": latencies[int(n * 0.9)],
                "p99": latencies[int(n * 0.99)] if n > 100 else latencies[-1],
            }

        return {
            "model_breakdown": model_data,
            "latency_percentiles": percentiles,
            "total_calls": sum(m["calls"] for m in model_data),
            "total_cost_usd": sum(m["total_cost_usd"] for m in model_data),
        }

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
            func.avg(ToolInteractionLog.latency_ms).label("avg_latency_ms"),
        ).join(ExecutionRun, ToolInteractionLog.run_id == ExecutionRun.id) \
         .where(ToolInteractionLog.created_at >= since)

        if company_id:
            q = q.where(ExecutionRun.company_id == company_id)

        q = q.group_by(ToolInteractionLog.tool_name, ToolInteractionLog.provider) \
             .order_by(desc("calls"))

        result = await self.db.execute(q)
        rows = result.all()

        tool_data = []
        for r in rows:
            calls = r.calls or 0
            successes = int(r.successes or 0)
            failures = calls - successes
            tool_data.append({
                "tool_name": r.tool_name,
                "provider": r.provider,
                "total_calls": calls,
                "success_count": successes,
                "failure_count": failures,
                "error_rate": round(failures / calls * 100, 1) if calls else 0,
                "avg_latency_ms": round(float(r.avg_latency_ms or 0), 1),
            })

        return {"tools": tool_data}

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
         .where(HumanApproval.requested_at >= since)

        if company_id:
            q = q.where(ExecutionRun.company_id == company_id)

        q = q.order_by(desc(HumanApproval.requested_at))
        result = await self.db.execute(q)
        rows = result.all()

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

        return {
            "approvals": approvals,
            "status_counts": status_counts,
            "overdue_count": overdue_count,
            "total": len(approvals),
        }

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

        q = select(
            IntegrationRegistry.model_name,
            IntegrationRegistry.service_category,
            func.count(UsageLog.id).label("calls"),
            func.sum(UsageLog.raw_quantity).label("total_qty"),
            func.sum(UsageLog.calculated_cost).label("total_cost"),
        ).join(IntegrationRegistry, UsageLog.sku_id == IntegrationRegistry.id) \
         .where(
            UsageLog.company_id == company_id,
            UsageLog.timestamp >= since,
        ) \
         .group_by(IntegrationRegistry.model_name, IntegrationRegistry.service_category) \
         .order_by(desc("total_cost"))

        result = await self.db.execute(q)
        rows = result.all()

        channels = [
            {
                "service": r.model_name,
                "category": r.service_category,
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
        """Per-tenant health scorecard for partner_admin / partner_user."""
        # Get all tenants under this partner
        tenant_q = select(Company).where(
            Company.parent_id == partner_company_id,
            Company.type == "TENANT",
        )
        result = await self.db.execute(tenant_q)
        tenants = result.scalars().all()

        tenant_ids = [t.id for t in tenants]
        tenant_map = {str(t.id): t.name for t in tenants}

        if not tenant_ids:
            return {"tenants": []}

        # Execution stats per tenant
        exec_q = select(
            ExecutionRun.company_id,
            ExecutionRun.status,
            func.count(ExecutionRun.id).label("cnt"),
        ).where(
            ExecutionRun.company_id.in_(tenant_ids),
            ExecutionRun.created_at >= datetime.utcnow() - timedelta(days=30),
        ).group_by(ExecutionRun.company_id, ExecutionRun.status)

        exec_result = await self.db.execute(exec_q)
        exec_rows = exec_result.all()

        exec_by_tenant: Dict[str, Dict] = {}
        for row in exec_rows:
            tid = str(row.company_id)
            if tid not in exec_by_tenant:
                exec_by_tenant[tid] = {}
            exec_by_tenant[tid][row.status] = row.cnt

        # Wallet per tenant
        wallet_q = select(CreditWallet).where(CreditWallet.company_id.in_(tenant_ids))
        wallet_result = await self.db.execute(wallet_q)
        wallets = {str(w.company_id): w for w in wallet_result.scalars().all()}

        scores = []
        for t in tenants:
            tid = str(t.id)
            tstatus = exec_by_tenant.get(tid, {})
            total_runs = sum(tstatus.values())
            completed = tstatus.get("COMPLETED", 0)
            failed = tstatus.get("FAILED", 0)
            w = wallets.get(tid)
            wallet_total = float((w.daily_credits or 0) + (w.wallet_balance or 0) + (w.subscription_credits or 0)) if w else 0

            health_score = 100.0
            if total_runs > 0:
                health_score = round(completed / total_runs * 100, 1)
            if wallet_total < 1.0:
                health_score = max(0, health_score - 20)

            scores.append({
                "company_id": tid,
                "company_name": t.name,
                "status": t.status,
                "total_runs_30d": total_runs,
                "completed_runs": completed,
                "failed_runs": failed,
                "wallet_balance": round(wallet_total, 4),
                "health_score": health_score,
                "at_risk": wallet_total < 2.0 or (total_runs > 0 and failed / total_runs > 0.3),
            })

        scores.sort(key=lambda x: x["health_score"], reverse=True)
        return {"tenants": scores}

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
        total_tel_in = sum(float(be.telephony_in_minutes) for be in billing_events)
        total_tel_out = sum(float(be.telephony_out_minutes) for be in billing_events)
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
            )

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
        )

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
            "document_chunks": DocumentChunk,
            "usage_logs": UsageLog,
            "human_approvals": HumanApproval,
        }

        counts = {}
        for name, model in tables.items():
            q = select(func.count(model.id))
            result = await self.db.execute(q)
            counts[name] = result.scalar() or 0

        # Monthly growth for key tables
        growth_q = select(
            func.date_trunc("month", LLMInteractionLog.created_at).label("month"),
            func.count(LLMInteractionLog.id).label("cnt"),
        ).group_by(text("1")) \
         .order_by(text("1"))

        growth_result = await self.db.execute(growth_q)
        llm_growth = [
            {"month": r.month.strftime("%Y-%m"), "count": r.cnt}
            for r in growth_result.all()
            if r.month
        ]

        return {
            "row_counts": counts,
            "llm_log_growth": llm_growth,
            "recommendations": [
                {"table": k, "count": v, "needs_archival": v > 1_000_000}
                for k, v in counts.items()
            ],
        }

"""Platform Console reports R-A01…R-A23 (Phase 15 T9-5; 07 §7.1). Staff only; amounts in the display currency.

Staff functions decide who sees which (07 §4.2): finance the money reports,
sales the pipeline and partner ones, ops the operational ones, support the
operational and customer ones; app_admin all.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List

from sqlalchemy import and_, func, or_, select

from src.reports.facts import CATEGORY_LABEL, ZERO, by_category_day, d, lines, month, months_between, names, pct, wallet_states
from src.reports.framework import Chart, Column, Context, Filter, Report, Tile, report

C = ("console",)
FIN, SALES, OPS, SUPPORT = ("finance",), ("sales",), ("ops",), ("support",)


def _money_tile(ctx: Context, label: str, usd: Any, **kw: Any) -> Tile:
    return Tile(label, ctx.money(usd), "money", **kw)


@report(id="R-A01", title="Platform overview", description="Billed, cash, margin, MRR, companies, partner share, "
        "daily-credit cost", workspaces=C, group="Overview")
async def platform_overview(ctx: Context) -> Report:
    from src.auth.models import Company
    from src.billing.billing_models import BillingLine as L, PaymentTransaction as P, Subscription, WalletEntry
    from src.partners.models import PartnerAssignment

    [total] = await lines(ctx)
    cash = (await ctx.db.execute(select(P.currency, func.sum(func.coalesce(P.net_amount, P.amount))).where(
        P.status == "success", P.created_at >= ctx.start_dt, P.created_at < ctx.end_dt, ctx.scoped(P.company_id))
        .group_by(P.currency))).all()
    from src.reports.facts import usd_of
    cash_usd = sum([await usd_of(ctx.db, amount, ccy) for ccy, amount in cash], ZERO)
    subs = (await ctx.db.execute(select(Subscription.currency, func.sum(func.coalesce(Subscription.amount_ccy,
                                                                                      Subscription.monthly_fee)))
                                 .where(Subscription.status.in_(("active", "past_due")), ctx.scoped(Subscription.company_id))
                                 .group_by(Subscription.currency))).all()
    mrr_usd = sum([await usd_of(ctx.db, amount, ccy) for ccy, amount in subs], ZERO)
    active = (await ctx.db.execute(select(func.count(func.distinct(L.company_id))).where(
        L.period_day >= ctx.start, L.period_day < ctx.end, ctx.scoped(L.company_id)))).scalar() or 0
    attributed = select(PartnerAssignment.tenant_id).where(PartnerAssignment.until.is_(None))
    [partner] = await lines(ctx, where=[L.company_id.in_(attributed)])
    daily_rows = (await ctx.db.execute(select(WalletEntry.currency, func.sum(WalletEntry.amount)).where(
        WalletEntry.kind == "deduct", WalletEntry.created_at >= ctx.start_dt, WalletEntry.created_at < ctx.end_dt,
        WalletEntry.lot_id.in_(select_lots("daily")), ctx.scoped(WalletEntry.company_id))
        .group_by(WalletEntry.currency))).all()
    daily_usd = sum([await usd_of(ctx.db, abs(d(amount)), ccy) for ccy, amount in daily_rows], ZERO)
    companies = (await ctx.db.execute(select(func.count()).select_from(Company).where(Company.type == "TENANT"))).scalar()
    margin = d(total.billed_usd) - d(total.cost_usd)
    data, series = [], [{"key": "billed", "label": "Billed"}, {"key": "cost", "label": "Cost"}]
    for m in months_between(ctx.start, ctx.end):
        data.append({"month": m, "billed": ZERO, "cost": ZERO})
    rows = await lines(ctx, func.to_char(L.period_day, "YYYY-MM"))
    by_month = {r[0]: r for r in rows}
    for point in data:
        r = by_month.get(point["month"])
        if r is not None:
            point["billed"], point["cost"] = ctx.money(r.billed_usd), ctx.money(r.cost_usd)
    return Report(
        tiles=[_money_tile(ctx, "Billed", total.billed_usd), _money_tile(ctx, "Cash collected", cash_usd),
               Tile("Gross margin", pct(margin, total.billed_usd), "percent", cost=True),
               _money_tile(ctx, "MRR", mrr_usd), _money_tile(ctx, "ARR", mrr_usd * 12),
               Tile("Companies billed", active, hint=f"of {companies}"),
               Tile("Partner-sourced share", pct(partner.billed_usd, total.billed_usd), "percent"),
               _money_tile(ctx, "Daily credit used", daily_usd, hint="free credit spent: its cost to the platform")],
        chart=Chart("bar", "month", series, data, cost_keys=("cost",)))


def select_lots(kind: str) -> Any:
    from src.billing.billing_models import WalletLot
    return select(WalletLot.id).where(WalletLot.kind == kind)


@report(id="R-A02", title="Revenue & margin", description="Billed, cost and margin by category and company",
        workspaces=C, staff_functions=FIN, group="Finance",
        filters=(Filter("category", "Category", "choice", tuple(CATEGORY_LABEL), CATEGORY_LABEL),))
async def revenue_margin(ctx: Context) -> Report:
    from src.billing.billing_models import BillingLine as L

    where = [L.category == ctx.filters["category"]] if ctx.filters.get("category") else []
    data, series = await by_category_day(ctx, where)
    rows = await lines(ctx, L.company_id, where=where)
    named = await names(ctx.db, [r.company_id for r in rows])
    table = sorted(({"company_id": r.company_id, "company": named.get(r.company_id, "—"),
                     "billed": ctx.money(r.billed_usd), "cost": ctx.money(r.cost_usd),
                     "margin": ctx.money(d(r.billed_usd) - d(r.cost_usd)),
                     "margin_pct": pct(d(r.billed_usd) - d(r.cost_usd), r.billed_usd)} for r in rows),
                   key=lambda r: r["billed"], reverse=True)
    billed = sum((r["billed"] for r in table), ZERO)
    cost = sum((r["cost"] for r in table), ZERO)
    return Report(
        tiles=[Tile("Billed", billed, "money"), Tile("Cost", cost, "money", cost=True),
               Tile("Margin", billed - cost, "money", cost=True), Tile("Margin %", pct(billed - cost, billed), "percent", cost=True)],
        chart=Chart("stacked", "day", series, data),
        columns=[Column("company", "Company", "link"), Column("billed", "Billed", "money"),
                 Column("cost", "Cost", "money", cost=True), Column("margin", "Margin", "money", cost=True),
                 Column("margin_pct", "Margin %", "percent", cost=True)],
        rows=table, drill={"company": "/console/companies/{company_id}"})


@report(id="R-A03", title="Cost of goods & provider reconciliation", description="Cost and billed by SKU and provider",
        workspaces=C, staff_functions=FIN, group="Finance")
async def cogs(ctx: Context) -> Report:
    from src.ai.orm.usage import UsageLog as U
    from src.config.models import IntegrationRegistry as R

    rows = (await ctx.db.execute(select(R.service_sku, R.provider_name, func.count(U.id), func.sum(U.raw_quantity),
                                        func.sum(U.calculated_cost), func.sum(U.billed_usd))
                                 .join(R, R.id == U.sku_id, isouter=True)
                                 .where(U.timestamp >= ctx.start_dt, U.timestamp < ctx.end_dt, ctx.scoped(U.company_id))
                                 .group_by(R.service_sku, R.provider_name))).all()
    table = sorted(({"sku": sku or "(no SKU)", "provider": provider or "—", "rows": n, "quantity": d(q),
                     "cost": ctx.money(cost), "billed": ctx.money(billed),
                     "margin_pct": pct(d(billed) - d(cost), billed)} for sku, provider, n, q, cost, billed in rows),
                   key=lambda r: r["cost"], reverse=True)
    return Report(
        tiles=[Tile("Cost", sum((r["cost"] for r in table), ZERO), "money", cost=True),
               Tile("SKUs used", len(table))],
        columns=[Column("sku", "SKU"), Column("provider", "Provider"), Column("rows", "Rows", "number"),
                 Column("quantity", "Quantity", "number"), Column("cost", "Cost", "money", cost=True),
                 Column("billed", "Billed", "money"), Column("margin_pct", "Margin %", "percent", cost=True)],
        rows=table,
        notes=["Calls are billed per second; providers charge in their own increments (K-2). Compare a provider's "
               "invoice with its cost here."])


@report(id="R-A04", title="Subscriptions & MRR", description="New, churned and net MRR; plan mix",
        workspaces=C, staff_functions=FIN, group="Finance")
async def mrr(ctx: Context) -> Report:
    from src.billing.billing_models import Plan, Subscription as S
    from src.reports.facts import usd_of

    subs = (await ctx.db.execute(select(S).where(ctx.scoped(S.company_id)))).scalars().all()
    plans = dict((await ctx.db.execute(select(Plan.id, Plan.name))).all())
    new = churned = live = ZERO
    mix: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"subscriptions": 0, "mrr": ZERO})
    waterfall: Dict[str, Dict[str, Any]] = {m: {"month": m, "new": ZERO, "churned": ZERO}
                                            for m in months_between(ctx.start, ctx.end)}
    for s in subs:
        usd = await usd_of(ctx.db, s.amount_ccy if s.amount_ccy is not None else s.monthly_fee, s.currency or "USD")
        value = ctx.money(usd)
        if ctx.start_dt <= s.created_at < ctx.end_dt and s.status != "pending_payment":
            new += value
            if month(s.created_at) in waterfall:
                waterfall[month(s.created_at)]["new"] += value
        if s.cancelled_at and ctx.start_dt <= s.cancelled_at < ctx.end_dt:
            churned += value
            if month(s.cancelled_at) in waterfall:
                waterfall[month(s.cancelled_at)]["churned"] += value
        if s.status in ("active", "past_due"):
            live += value
            name = plans.get(s.plan_id, f"Level {s.plan_tier}")
            mix[name]["subscriptions"] += 1
            mix[name]["mrr"] += value
    return Report(
        tiles=[Tile("MRR", live, "money"), Tile("New MRR", new, "money"), Tile("Churned MRR", churned, "money"),
               Tile("Net new MRR", new - churned, "money")],
        chart=Chart("bar", "month", [{"key": "new", "label": "New"}, {"key": "churned", "label": "Churned"}],
                    list(waterfall.values())),
        columns=[Column("plan", "Plan"), Column("subscriptions", "Live subscriptions", "number"), Column("mrr", "MRR", "money")],
        rows=[{"plan": k, **v} for k, v in sorted(mix.items(), key=lambda kv: kv[1]["mrr"], reverse=True)])


@report(id="R-A05", title="Wallet liability & breakage", description="Prepaid balance by kind and expiry; expired value",
        workspaces=C, staff_functions=FIN, group="Finance", period=True)
async def liability(ctx: Context) -> Report:
    from src.billing.billing_models import WalletEntry, WalletLot
    from src.reports.facts import usd_of

    now = datetime.utcnow()
    lots = (await ctx.db.execute(select(WalletLot).where(WalletLot.remaining > 0, ctx.scoped(WalletLot.company_id),
                                                         or_(WalletLot.expires_at.is_(None), WalletLot.expires_at > now))
                                 )).scalars().all()
    buckets = ("0–7 days", "8–30 days", "31–90 days", "over 90 days", "no expiry")
    table: Dict[str, Dict[str, Any]] = {}
    total = ZERO
    for lot in lots:
        usd = await usd_of(ctx.db, lot.remaining, lot.currency)
        value = ctx.money(usd)
        days = (lot.expires_at - now).days if lot.expires_at else None
        bucket = buckets[4] if days is None else buckets[0] if days <= 7 else buckets[1] if days <= 30 else \
            buckets[2] if days <= 90 else buckets[3]
        row = table.setdefault(lot.kind, {"kind": lot.kind, **{b: ZERO for b in buckets}, "total": ZERO})
        row[bucket] += value
        row["total"] += value
        total += value
    expired = (await ctx.db.execute(select(WalletEntry.currency, func.sum(WalletEntry.amount)).where(
        WalletEntry.kind == "expire", WalletEntry.created_at >= ctx.start_dt, WalletEntry.created_at < ctx.end_dt,
        ctx.scoped(WalletEntry.company_id)).group_by(WalletEntry.currency))).all()
    breakage = sum([ctx.money(await usd_of(ctx.db, abs(d(a)), c)) for c, a in expired], ZERO)
    paid_kinds = {"topup", "subscription"}
    return Report(
        tiles=[Tile("Prepaid balance", total, "money"),
               Tile("Of it paid for", sum((r["total"] for k, r in table.items() if k in paid_kinds), ZERO), "money"),
               Tile("Expired in the period (breakage)", breakage, "money")],
        chart=Chart("stacked", "kind", [{"key": b, "label": b} for b in buckets], list(table.values())),
        columns=[Column("kind", "Kind"), *[Column(b, b, "money") for b in buckets], Column("total", "Total", "money")],
        rows=sorted(table.values(), key=lambda r: r["total"], reverse=True))


@report(id="R-A06", title="Receivables & negative balances", description="Debt by company, ageing, states",
        workspaces=C, staff_functions=FIN, group="Finance", period=False)
async def receivables(ctx: Context) -> Report:
    from src.billing.billing_models import CreditWallet as W
    from src.reports.facts import usd_of

    wallets = (await ctx.db.execute(select(W).where(or_(W.debt > 0, W.state != "ok"), ctx.scoped(W.company_id))
                                    )).scalars().all()
    named = await names(ctx.db, [w.company_id for w in wallets])
    now = datetime.utcnow()
    ageing = {"0–7 days": ZERO, "8–30 days": ZERO, "over 30 days": ZERO}
    rows = []
    for w in wallets:
        owed = ctx.money(await usd_of(ctx.db, w.debt, w.currency))
        days = (now - w.in_debt_since).days if w.in_debt_since else 0
        bucket = "0–7 days" if days <= 7 else "8–30 days" if days <= 30 else "over 30 days"
        ageing[bucket] += owed
        rows.append({"company_id": w.company_id, "company": named.get(w.company_id), "state": w.state,
                     "owed": owed, "owed_own": f"{w.currency} {d(w.debt):,.2f}", "days": days})
    return Report(
        tiles=[Tile("Owed", sum(ageing.values(), ZERO), "money"), Tile("Companies in debt", len(rows)),
               Tile("Suspended", sum(1 for r in rows if r["state"] == "suspended"))],
        chart=Chart("bar", "bucket", [{"key": "owed", "label": "Owed"}],
                    [{"bucket": k, "owed": v} for k, v in ageing.items()]),
        columns=[Column("company", "Company", "link"), Column("state", "State"), Column("owed", "Owed", "money"),
                 Column("owed_own", "In its currency"), Column("days", "Days in debt", "number")],
        rows=sorted(rows, key=lambda r: r["owed"], reverse=True), drill={"company": "/console/companies/{company_id}"})


@report(id="R-A07", title="Daily credit programme", description="Free credit granted and used, by policy; conversion",
        workspaces=C, group="Commercial")
async def daily_programme(ctx: Context) -> Report:
    from src.billing.billing_models import DailyCreditPolicy, PaymentTransaction as P, WalletLot as L
    from src.reports.facts import usd_of

    rows = (await ctx.db.execute(select(L.policy_id, L.currency, func.count(L.id), func.sum(L.original),
                                        func.sum(L.original - L.remaining), func.count(func.distinct(L.company_id)))
                                 .where(L.kind == "daily", L.granted_at >= ctx.start_dt, L.granted_at < ctx.end_dt,
                                        ctx.scoped(L.company_id))
                                 .group_by(L.policy_id, L.currency))).all()
    policies = dict((await ctx.db.execute(select(DailyCreditPolicy.id, DailyCreditPolicy.name))).all())
    table = []
    for policy_id, ccy, n, granted, used, companies in rows:
        table.append({"policy": policies.get(policy_id, "custom / override"), "companies": companies, "grants": n,
                      "granted": ctx.money(await usd_of(ctx.db, granted, ccy)),
                      "used": ctx.money(await usd_of(ctx.db, used, ccy))})
    trial = select(L.company_id).where(L.kind == "daily", L.granted_at >= ctx.start_dt, L.granted_at < ctx.end_dt)
    converted = (await ctx.db.execute(select(func.count(func.distinct(P.company_id))).where(
        P.status == "success", P.company_id.in_(trial)))).scalar() or 0
    trialled = (await ctx.db.execute(select(func.count(func.distinct(L.company_id))).where(
        L.kind == "daily", L.granted_at >= ctx.start_dt, L.granted_at < ctx.end_dt, ctx.scoped(L.company_id)))).scalar() or 0
    return Report(
        tiles=[Tile("Free credit granted", sum((r["granted"] for r in table), ZERO), "money"),
               Tile("Used", sum((r["used"] for r in table), ZERO), "money"),
               Tile("Companies on daily credit", trialled), Tile("Paid since", converted, hint=f"{pct(converted, trialled)} %")],
        columns=[Column("policy", "Policy"), Column("companies", "Companies", "number"), Column("grants", "Grants", "number"),
                 Column("granted", "Granted", "money"), Column("used", "Used", "money")],
        rows=table)


@report(id="R-A08", title="Acquisition funnel", description="Sign-ups → first agent → first run → first recharge → plan",
        workspaces=C, staff_functions=SALES, group="Growth")
async def funnel(ctx: Context) -> Report:
    from src.ai.orm.entity import HierarchicalEntity as E
    from src.ai.orm.execution import ExecutionRun as R
    from src.auth.models import Company
    from src.billing.billing_models import PaymentTransaction as P, Subscription as S
    from src.partners.models import PartnerAssignment

    signed = list((await ctx.db.execute(select(Company.id).where(
        Company.type == "TENANT", Company.created_at >= ctx.start_dt, Company.created_at < ctx.end_dt,
        ctx.scoped(Company.id)))).scalars().all())
    ids = set(signed)
    agents = {r[0] for r in await ctx.tenant_rows(select(func.distinct(E.company_id)).where(E.company_id.in_(ids)))} if ids else set()
    runs = {r[0] for r in await ctx.tenant_rows(select(func.distinct(R.company_id)).where(R.company_id.in_(ids)))} if ids else set()
    paid = set((await ctx.db.execute(select(func.distinct(P.company_id)).where(
        P.status == "success", P.company_id.in_(ids)))).scalars().all()) if ids else set()
    subscribed = set((await ctx.db.execute(select(func.distinct(S.company_id)).where(
        S.status.in_(("active", "past_due", "cancelled")), S.company_id.in_(ids)))).scalars().all()) if ids else set()
    via_partner = set((await ctx.db.execute(select(PartnerAssignment.tenant_id).where(
        PartnerAssignment.tenant_id.in_(ids)))).scalars().all()) if ids else set()
    steps = [("Signed up", ids), ("Made an AI employee", agents & ids), ("Ran it", runs & ids),
             ("Recharged", paid & ids), ("Subscribed", subscribed & ids)]
    return Report(
        tiles=[Tile("Sign-ups", len(ids)), Tile("Through a partner", len(via_partner)),
               Tile("Recharged", len(paid & ids), hint=f"{pct(len(paid & ids), len(ids))} %")],
        chart=Chart("bar", "step", [{"key": "companies", "label": "Companies"}],
                    [{"step": s, "companies": len(c)} for s, c in steps]),
        columns=[Column("step", "Step"), Column("companies", "Companies", "number"), Column("of_signups", "% of sign-ups", "percent")],
        rows=[{"step": s, "companies": len(c), "of_signups": pct(len(c), len(ids))} for s, c in steps])


@report(id="R-A09", title="Partner performance", description="Per partner: customers, sourced revenue, commissions, "
        "fees, network", workspaces=C, staff_functions=SALES, group="Partners", period=True)
async def partner_performance(ctx: Context) -> Report:
    from src.billing.billing_models import BillingLine as L
    from src.partners.models import OneTimeCharge, PartnerAssignment as A, PartnerLedgerEntry as E, PartnerProfile

    profiles = (await ctx.db.execute(select(PartnerProfile))).scalars().all()
    named = await names(ctx.db, [p.company_id for p in profiles])
    assignments = (await ctx.db.execute(select(A.partner_id, A.tenant_id).where(A.until.is_(None)))).all()
    tenants: Dict[Any, List[Any]] = defaultdict(list)
    for partner_id, tenant_id in assignments:
        tenants[partner_id].append(tenant_id)
    sourced = {r.company_id: r for r in await lines(ctx, L.company_id, where=[L.company_id.in_([t for _, t in assignments])])}
    earned = dict((await ctx.db.execute(select(E.partner_id, func.sum(E.amount_usd)).where(
        E.kind.in_(("commission", "override", "fee_share", "clawback")), E.status != "reversed",
        E.created_at >= ctx.start_dt, E.created_at < ctx.end_dt).group_by(E.partner_id))).all())
    fees = dict((await ctx.db.execute(select(OneTimeCharge.partner_id, func.sum(OneTimeCharge.amount_usd)).where(
        OneTimeCharge.status == "paid", OneTimeCharge.paid_at >= ctx.start_dt, OneTimeCharge.paid_at < ctx.end_dt)
        .group_by(OneTimeCharge.partner_id))).all())
    network = defaultdict(int)
    for p in profiles:
        if p.recruiter_partner_id:
            network[p.recruiter_partner_id] += 1
    rows = []
    for p in profiles:
        billed_usd = sum((d(sourced[t].billed_usd) for t in tenants[p.company_id] if t in sourced), ZERO)
        rows.append({"partner_id": p.company_id, "partner": named.get(p.company_id), "type": p.partner_type,
                     "status": p.status, "depth": p.depth, "customers": len(tenants[p.company_id]),
                     "sourced": ctx.money(billed_usd), "earned": ctx.money(earned.get(p.company_id)),
                     "fees": ctx.money(fees.get(p.company_id)), "network": network[p.company_id],
                     "fee_paid_until": p.fee_paid_until.date() if p.fee_paid_until else None})
    rows.sort(key=lambda r: r["sourced"], reverse=True)
    return Report(
        tiles=[Tile("Partners", len(rows)), Tile("Active", sum(1 for r in rows if r["status"] == "active")),
               Tile("Sourced billed", sum((r["sourced"] for r in rows), ZERO), "money"),
               Tile("Partner earnings", sum((r["earned"] for r in rows), ZERO), "money")],
        columns=[Column("partner", "Partner", "link"), Column("type", "Type"), Column("status", "Status"),
                 Column("depth", "Level", "number"), Column("customers", "Customers", "number"),
                 Column("sourced", "Sourced billed", "money"), Column("earned", "Earned", "money"),
                 Column("fees", "Setup fees", "money"), Column("network", "Recruits", "number"),
                 Column("fee_paid_until", "Fee paid to", "date")],
        rows=rows, drill={"partner": "/console/partners/{partner_id}"})


@report(id="R-A10", title="Commission & payout ledger", description="Accrued, held, payable, paid, clawbacks, TDS "
        "by partner and level; open-ended referral run-rate", workspaces=C, staff_functions=FIN, group="Partners")
async def commission_ledger(ctx: Context) -> Report:
    from src.partners.models import PartnerAssignment as A, PartnerLedgerEntry as E

    rows = (await ctx.db.execute(select(E.partner_id, E.level, E.status, E.kind, func.sum(E.amount_usd)).where(
        E.created_at >= ctx.start_dt, E.created_at < ctx.end_dt).group_by(E.partner_id, E.level, E.status, E.kind)
    )).all()
    named = await names(ctx.db, [r[0] for r in rows])
    table: Dict[tuple, Dict[str, Any]] = {}
    totals: Dict[str, Decimal] = defaultdict(lambda: ZERO)
    for partner_id, level, status, kind, usd in rows:
        key = (partner_id, level)
        row = table.setdefault(key, {"partner": named.get(partner_id), "level": level, "accrued": ZERO, "held": ZERO,
                                     "payable": ZERO, "paid": ZERO, "clawbacks": ZERO, "tds": ZERO})
        value = ctx.money(usd)
        if kind == "clawback":
            row["clawbacks"] += value
        elif kind == "tds":
            row["tds"] += value
        elif kind != "payout" and status in row:
            row[status] += value
        totals[kind if kind in ("clawback", "tds") else status] += value
    referred = select(A.tenant_id).where(A.relationship == "referred", A.until.is_(None), A.commission_until.is_(None))
    since = datetime.utcnow() - timedelta(days=90)
    run_rate = (await ctx.db.execute(select(func.coalesce(func.sum(E.amount_usd), 0)).where(
        E.tenant_id.in_(referred), E.level == 0, E.created_at >= since, E.status != "reversed"))).scalar()
    return Report(
        tiles=[Tile("Accrued", totals["accrued"], "money"), Tile("Held", totals["held"], "money"),
               Tile("Payable", totals["payable"], "money"), Tile("Paid", totals["paid"], "money"),
               Tile("Open-ended referral run-rate (a year)", ctx.money(d(run_rate) * 4), "money",
                    hint="the last 90 days × 4 (O-8)")],
        columns=[Column("partner", "Partner"), Column("level", "Level", "number"), Column("accrued", "Accrued", "money"),
                 Column("held", "Held", "money"), Column("payable", "Payable", "money"), Column("paid", "Paid", "money"),
                 Column("clawbacks", "Clawbacks", "money"), Column("tds", "TDS", "money")],
        rows=sorted(table.values(), key=lambda r: (r["partner"] or "", r["level"])))


@report(id="R-A11", title="Setup & customisation fees", description="Raised, paid, outstanding; split by recipient",
        workspaces=C, staff_functions=FIN, group="Partners")
async def setup_fees(ctx: Context) -> Report:
    from src.partners.models import OneTimeCharge as O, PartnerLedgerEntry as E

    rows = (await ctx.db.execute(select(O.fee_kind, O.status, func.count(O.id), func.sum(O.amount_usd)).where(
        O.created_at >= ctx.start_dt, O.created_at < ctx.end_dt, ctx.scoped(O.tenant_id)).group_by(O.fee_kind, O.status)
    )).all()
    shares = (await ctx.db.execute(select(E.level, func.sum(E.amount_usd)).where(
        E.kind == "fee_share", E.created_at >= ctx.start_dt, E.created_at < ctx.end_dt).group_by(E.level))).all()
    paid = sum((d(v) for _k, s, _n, v in rows if s == "paid"), ZERO)
    to_partners = sum((d(v) for _l, v in shares), ZERO)
    return Report(
        tiles=[Tile("Raised", ctx.money(sum((d(v) for *_x, v in rows), ZERO)), "money"), Tile("Paid", ctx.money(paid), "money"),
               Tile("Outstanding", ctx.money(sum((d(v) for _k, s, _n, v in rows if s == "sent"), ZERO)), "money"),
               Tile("To partners", ctx.money(to_partners), "money"), Tile("To HireBuddha", ctx.money(paid - to_partners), "money")],
        columns=[Column("fee_kind", "Fee"), Column("status", "Status"), Column("count", "Charges", "number"),
                 Column("amount", "Amount", "money")],
        rows=[{"fee_kind": k, "status": s, "count": n, "amount": ctx.money(v)} for k, s, n, v in rows])


@report(id="R-A12", title="Partnership fees", description="Due, paid, overdue, renewals in 30 days, lapsed",
        workspaces=C, staff_functions=FIN, group="Partners", period=False)
async def partnership_fees(ctx: Context) -> Report:
    from src.partners.models import PartnerProfile as PP

    now = datetime.utcnow()
    profiles = (await ctx.db.execute(select(PP))).scalars().all()
    named = await names(ctx.db, [p.company_id for p in profiles])
    rows = [{"partner_id": p.company_id, "partner": named.get(p.company_id), "type": p.partner_type,
             "status": p.status, "paid_until": p.fee_paid_until.date() if p.fee_paid_until else None,
             "days_left": (p.fee_paid_until - now).days if p.fee_paid_until else None} for p in profiles]
    return Report(
        tiles=[Tile("Renewals in 30 days", sum(1 for r in rows if r["days_left"] is not None and 0 <= r["days_left"] <= 30)),
               Tile("Overdue", sum(1 for r in rows if r["days_left"] is not None and r["days_left"] < 0)),
               Tile("Lapsed", sum(1 for r in rows if r["status"] == "lapsed")),
               Tile("Suspended", sum(1 for r in rows if r["status"] == "suspended"))],
        columns=[Column("partner", "Partner", "link"), Column("type", "Type"), Column("status", "Status"),
                 Column("paid_until", "Paid until", "date"), Column("days_left", "Days left", "number")],
        rows=sorted(rows, key=lambda r: (r["days_left"] is None, r["days_left"] or 0)),
        drill={"partner": "/console/partners/{partner_id}"})


@report(id="R-A13", title="Lead pipeline", description="Leads by status, conversion, time to convert, by partner",
        workspaces=C, staff_functions=SALES, group="Partners")
async def lead_pipeline(ctx: Context) -> Report:
    from src.partners.models import PartnerLead as LD

    leads = (await ctx.db.execute(select(LD).where(LD.created_at >= ctx.start_dt, LD.created_at < ctx.end_dt))).scalars().all()
    named = await names(ctx.db, [lead.partner_id for lead in leads])
    by_partner: Dict[Any, Dict[str, Any]] = {}
    statuses = ("registered", "accepted", "in_progress", "converted", "lost", "expired")
    for lead in leads:
        row = by_partner.setdefault(lead.partner_id, {"partner": named.get(lead.partner_id), **{s: 0 for s in statuses},
                                                      "total": 0, "days_to_convert": []})
        row[lead.status] += 1
        row["total"] += 1
        if lead.status == "converted":
            row["days_to_convert"].append((lead.updated_at - lead.created_at).days)
    rows = []
    for row in by_partner.values():
        days = row.pop("days_to_convert")
        rows.append({**row, "conversion": pct(row["converted"], row["total"]),
                     "avg_days": round(sum(days) / len(days), 1) if days else None})
    total = len(leads)
    converted = sum(1 for lead in leads if lead.status == "converted")
    return Report(
        tiles=[Tile("Leads", total), Tile("Converted", converted, hint=f"{pct(converted, total)} %"),
               Tile("Open", sum(1 for lead in leads if lead.status in ("registered", "accepted", "in_progress")))],
        chart=Chart("bar", "status", [{"key": "leads", "label": "Leads"}],
                    [{"status": s, "leads": sum(1 for lead in leads if lead.status == s)} for s in statuses]),
        columns=[Column("partner", "Partner"), *[Column(s, s.replace("_", " ").capitalize(), "number") for s in statuses],
                 Column("conversion", "Conversion", "percent"), Column("avg_days", "Days to convert", "number")],
        rows=rows)


@report(id="R-A14", title="GST / tax", description="Taxable value, CGST, SGST, IGST, zero-rated by month and state "
        "(GSTR-1)", workspaces=C, staff_functions=FIN, group="Finance")
async def gst(ctx: Context) -> Report:
    from src.billing.billing_models import CreditNote, Invoice as I

    issued_month = func.to_char(I.issued_at, "YYYY-MM")
    rows = (await ctx.db.execute(select(issued_month, I.place_of_supply, I.regime, I.currency,
                                        func.count(I.id), func.sum(I.net), func.sum(I.cgst), func.sum(I.sgst),
                                        func.sum(I.igst), func.count(I.customer["gstin"].astext))
                                 .where(I.issued_at >= ctx.start_dt, I.issued_at < ctx.end_dt, ctx.scoped(I.company_id))
                                 .group_by(issued_month, I.place_of_supply, I.regime, I.currency))).all()
    notes = (await ctx.db.execute(select(func.count(CreditNote.id), func.coalesce(func.sum(CreditNote.tax), 0)).where(
        CreditNote.issued_at >= ctx.start_dt, CreditNote.issued_at < ctx.end_dt))).one()
    table = [{"month": m, "state": state or ("export" if regime == "export" else "—"), "regime": regime, "currency": ccy,
              "invoices": n, "b2b": b2b, "taxable": d(net), "cgst": d(cg), "sgst": d(sg), "igst": d(ig)}
             for m, state, regime, ccy, n, net, cg, sg, ig, b2b in rows]
    inr = [r for r in table if r["currency"] == "INR"]
    return Report(
        tiles=[Tile("Invoices", sum(r["invoices"] for r in table)),
               Tile("Taxable value (INR)", sum((r["taxable"] for r in inr), ZERO), "number"),
               Tile("GST (INR)", sum((r["cgst"] + r["sgst"] + r["igst"] for r in inr), ZERO), "number"),
               Tile("Credit notes", notes[0], hint=f"GST reversed {d(notes[1]):,.2f}")],
        columns=[Column("month", "Month"), Column("state", "Place of supply"), Column("regime", "Regime"),
                 Column("currency", "Currency"), Column("invoices", "Invoices", "number"), Column("b2b", "B2B", "number"),
                 Column("taxable", "Taxable", "number"), Column("cgst", "CGST", "number"), Column("sgst", "SGST", "number"),
                 Column("igst", "IGST", "number")],
        rows=table, notes=["Amounts are in each invoice's own currency (GST is on INR invoices; exports are zero-rated)."])


@report(id="R-A15", title="FX impact", description="Revenue at locked rates vs today's; rate history",
        workspaces=C, staff_functions=FIN, group="Finance")
async def fx_impact(ctx: Context) -> Report:
    from src.billing.billing_models import BillingLine as L, FxRate
    from src.billing.currency import current_rate, to_usd

    rows = await lines(ctx, L.currency)
    table = []
    for r in rows:
        rate = await current_rate(ctx.db, r.currency)
        at_today = to_usd(d(r.billed_ccy), rate)
        table.append({"currency": r.currency, "billed_own": d(r.billed_ccy), "usd_locked": d(r.billed_usd),
                      "usd_today": at_today, "difference": at_today - d(r.billed_usd)})
    history = (await ctx.db.execute(select(FxRate).where(FxRate.effective_from >= ctx.start_dt - timedelta(days=365))
                                    .order_by(FxRate.effective_from))).scalars().all()
    return Report(
        tiles=[Tile("Difference at today's rates (USD)", sum((r["difference"] for r in table), ZERO), "number")],
        chart=Chart("line", "date", [{"key": "units_per_usd", "label": "Units per USD"}],
                    [{"date": f.effective_from.date(), "currency": f.currency, "units_per_usd": d(f.units_per_usd)}
                     for f in history]),
        columns=[Column("currency", "Currency"), Column("billed_own", "Billed (own currency)", "number"),
                 Column("usd_locked", "USD at the locked rates", "number"), Column("usd_today", "USD at today's rate", "number"),
                 Column("difference", "Difference (USD)", "number")],
        rows=table)


@report(id="R-A16", title="Phone numbers & rent", description="Numbers by status, rent billed, held numbers, provider cost",
        workspaces=C, staff_functions=OPS, group="Operations")
async def numbers(ctx: Context) -> Report:
    from src.billing.billing_models import BillingLine as L, NumberRental
    from src.voice.phone_pool_models import PhoneNumber

    counts = dict((await ctx.db.execute(select(PhoneNumber.status, func.count()).group_by(PhoneNumber.status))).all())
    held = (await ctx.db.execute(select(func.count()).select_from(NumberRental).where(NumberRental.status == "held"))).scalar()
    provider = (await ctx.db.execute(select(func.coalesce(func.sum(PhoneNumber.provider_monthly_cost_usd), 0)).where(
        PhoneNumber.company_id.isnot(None)))).scalar()
    rows = await lines(ctx, L.company_id, where=[L.category == "phone_numbers"])
    named = await names(ctx.db, [r.company_id for r in rows])
    return Report(
        tiles=[Tile("Numbers", sum(counts.values())), Tile("Claimed or assigned", counts.get("claimed", 0) + counts.get("assigned", 0)),
               Tile("Held for balance", held), Tile("Rent billed", ctx.money(sum((d(r.billed_usd) for r in rows), ZERO)), "money"),
               Tile("Provider cost a month", ctx.money(provider), "money", cost=True)],
        chart=Chart("bar", "status", [{"key": "numbers", "label": "Numbers"}],
                    [{"status": k, "numbers": v} for k, v in counts.items()]),
        columns=[Column("company", "Company", "link"), Column("rent", "Rent billed", "money")],
        rows=[{"company_id": r.company_id, "company": named.get(r.company_id), "rent": ctx.money(r.billed_usd)} for r in rows],
        drill={"company": "/console/companies/{company_id}"})


@report(id="R-A17", title="Hosting & database", description="Hosting and database billed vs cost by company",
        workspaces=C, staff_functions=OPS, group="Operations")
async def hosting(ctx: Context) -> Report:
    from src.billing.billing_models import BillingLine as L

    rows = await lines(ctx, L.company_id, L.category, where=[L.category.in_(("hosting", "database"))])
    named = await names(ctx.db, [r.company_id for r in rows])
    table: Dict[Any, Dict[str, Any]] = {}
    for r in rows:
        row = table.setdefault(r.company_id, {"company_id": r.company_id, "company": named.get(r.company_id),
                                              "hosting": ZERO, "database": ZERO, "cost": ZERO})
        row[r.category] += ctx.money(r.billed_usd)
        row["cost"] += ctx.money(r.cost_usd)
    return Report(
        tiles=[Tile("Hosting billed", sum((r["hosting"] for r in table.values()), ZERO), "money"),
               Tile("Database billed", sum((r["database"] for r in table.values()), ZERO), "money"),
               Tile("Cost", sum((r["cost"] for r in table.values()), ZERO), "money", cost=True)],
        columns=[Column("company", "Company", "link"), Column("hosting", "Hosting", "money"),
                 Column("database", "Database", "money"), Column("cost", "Cost", "money", cost=True)],
        rows=sorted(table.values(), key=lambda r: r["hosting"] + r["database"], reverse=True),
        drill={"company": "/console/companies/{company_id}"},
        notes=["Apps stopped for balance are listed on each company's page (Apps & hosting)."])


@report(id="R-A18", title="Feature adoption", description="Companies using each category, by plan", workspaces=C,
        staff_functions=SALES, group="Growth")
async def adoption(ctx: Context) -> Report:
    from src.billing.billing_models import BillingLine as L
    from src.billing.plans import plan_of

    rows = await lines(ctx, L.company_id, L.category)
    plan_names: Dict[Any, str] = {}
    for company_id in {r.company_id for r in rows}:
        plan = await plan_of(ctx.db, company_id)
        plan_names[company_id] = plan.name if plan else "Pay-as-you-go"
    matrix: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        row = matrix.setdefault(plan_names[r.company_id], {"plan": plan_names[r.company_id]})
        row[r.category] = row.get(r.category, 0) + 1
    categories = sorted({r.category for r in rows})
    return Report(
        tiles=[Tile("Companies using the platform", len(plan_names))],
        columns=[Column("plan", "Plan"), *[Column(c, CATEGORY_LABEL.get(c, c), "number") for c in categories]],
        rows=list(matrix.values()),
        notes=["Each cell: companies on that plan billed in that category in the period."])


@report(id="R-A19", title="Execution health", description="Run success, LLM performance, tool efficacy",
        workspaces=C, staff_functions=OPS, group="Operations")
async def execution_health(ctx: Context) -> Report:
    from src.ai.reports_service import ReportsService
    from src.common.tenancy.session import tenant_scopes

    days = max((ctx.end - ctx.start).days, 1)
    service = ReportsService(ctx.db, scopes=await tenant_scopes())
    health = await service.get_execution_health(company_id=ctx.company_id, days=days)
    tools = await service.get_tool_efficacy(company_id=ctx.company_id, days=days)
    summary = health["summary"]
    return Report(
        tiles=[Tile("Runs", summary["total_runs"]), Tile("Success", summary["success_rate"], "percent"),
               Tile("Failure", summary["failure_rate"], "percent"), Tile("Paused", summary["paused_count"])],
        chart=Chart("stacked", "date", [{"key": k, "label": k.capitalize()} for k in ("COMPLETED", "FAILED", "PAUSED")],
                    health["daily_trend"]),
        columns=[Column("tool_name", "Tool"), Column("provider", "Provider"), Column("total_calls", "Calls", "number"),
                 Column("error_rate", "Errors", "percent"), Column("avg_latency_ms", "Latency (ms)", "number")],
        rows=tools["tools"])


@report(id="R-A20", title="HITL oversight", description="Approvals pending and overdue", workspaces=C,
        staff_functions=OPS + SUPPORT, group="Operations")
async def hitl(ctx: Context) -> Report:
    from src.ai.reports_service import ReportsService
    from src.common.tenancy.session import tenant_scopes

    data = await ReportsService(ctx.db, scopes=await tenant_scopes()).get_hitl_report(
        company_id=ctx.company_id, days=max((ctx.end - ctx.start).days, 1))
    return Report(
        tiles=[Tile(k.capitalize(), v) for k, v in data["status_counts"].items()] + [Tile("Overdue", data["overdue_count"], tone="warning")],
        columns=[Column("entity_name", "AI employee"), Column("status", "Status"), Column("checkpoint_trigger", "Why"),
                 Column("requested_at", "Requested", "date"), Column("age_hours", "Age (h)", "number")],
        rows=data["approvals"])


@report(id="R-A21", title="Billing exceptions", description="Unsettled rows by age, unpriced usage, shadow differences",
        workspaces=C, staff_functions=OPS + FIN, group="Operations", period=False)
async def billing_exceptions(ctx: Context) -> Report:
    from src.ai.orm.usage import UsageLog as U
    from src.billing.billing_models import BillingShadowDiff as S

    now = datetime.utcnow()
    unsettled = (await ctx.db.execute(select(
        func.count().filter(U.timestamp >= now - timedelta(hours=1)),
        func.count().filter(and_(U.timestamp < now - timedelta(hours=1), U.timestamp >= now - timedelta(days=1))),
        func.count().filter(U.timestamp < now - timedelta(days=1))).where(U.settlement_id.is_(None),
                                                                          ctx.scoped(U.company_id)))).one()
    unpriced = (await ctx.db.execute(select(func.count()).select_from(U).where(
        U.billed_usd.is_(None), ctx.scoped(U.company_id)))).scalar()
    no_sku = (await ctx.db.execute(select(func.count()).select_from(U).where(
        U.sku_id.is_(None), U.timestamp >= now - timedelta(days=30), ctx.scoped(U.company_id)))).scalar()
    diffs = (await ctx.db.execute(select(S.company_id, func.count(), func.sum(S.diff_usd)).where(
        S.created_at >= now - timedelta(days=30), func.abs(S.diff_usd) > Decimal("0.01")).group_by(S.company_id))).all()
    named = await names(ctx.db, [r[0] for r in diffs])
    return Report(
        tiles=[Tile("Unsettled < 1 h", unsettled[0]), Tile("Unsettled 1–24 h", unsettled[1], tone="warning"),
               Tile("Unsettled > 1 day", unsettled[2], tone="negative" if unsettled[2] else "neutral"),
               Tile("Unrated rows", unpriced, tone="warning" if unpriced else "neutral"),
               Tile("Rows without a SKU (30 days)", no_sku)],
        columns=[Column("company", "Company"), Column("runs", "Shadow differences (30 days)", "number"),
                 Column("diff", "Difference (USD)", "number", cost=True)],
        rows=[{"company": named.get(c), "runs": n, "diff": d(s)} for c, n, s in diffs])


@report(id="R-A22", title="Data growth", description="Table sizes and archival readiness", workspaces=C,
        staff_functions=OPS, group="Operations", period=False)
async def data_growth(ctx: Context) -> Report:
    from src.ai.reports_service import ReportsService
    from src.common.tenancy.session import tenant_scopes

    data = await ReportsService(ctx.db, scopes=await tenant_scopes()).get_data_growth()
    return Report(
        tiles=[Tile("Tables needing archival", sum(1 for r in data["recommendations"] if r["needs_archival"]))],
        chart=Chart("line", "month", [{"key": "count", "label": "LLM log rows"}], data["llm_log_growth"]),
        columns=[Column("table", "Table"), Column("count", "Rows", "number"), Column("needs_archival", "Archive")],
        rows=data["recommendations"])


@report(id="R-A23", title="Commercial change audit", description="FX, prices, plans, policies and rules changes",
        workspaces=C, roles=("app_admin",), group="Overview")
async def change_audit(ctx: Context) -> Report:
    from src.auth.models import User
    from src.common.admin_audit import AdminAuditLog as AL

    kinds = ("fx_rate", "price_item", "plan", "plan_entitlements", "billing_formula", "platform_setting", "setting",
             "daily_credit_policy", "commission_rule", "fee_rule", "company_entitlement", "partner_status",
             "partner_application", "feature_flag", "company_lock", "payment", "partner_statement")
    rows = (await ctx.db.execute(select(AL).where(AL.at >= ctx.start_dt, AL.at < ctx.end_dt,
                                                  or_(AL.object_type.in_(kinds), AL.object_type.like("%setting%")))
                                 .order_by(AL.at.desc()).limit(500))).scalars().all()
    users = dict((await ctx.db.execute(select(User.id, User.email).where(User.id.in_({r.actor_user_id for r in rows}))
                                       )).all()) if rows else {}
    return Report(
        tiles=[Tile("Changes", len(rows))],
        columns=[Column("at", "When", "date"), Column("actor", "Who"), Column("action", "Action"),
                 Column("object", "What"), Column("key", "Key"), Column("reason", "Reason")],
        rows=[{"at": r.at, "actor": users.get(r.actor_user_id, r.actor_role), "action": r.action,
               "object": r.object_type, "key": r.object_key, "reason": r.reason} for r in rows])


@report(id="R-A24", title="Admin audit log", description="Every staff change to settings, money, plans, partners and flags",
        workspaces=C, staff_functions=OPS + SUPPORT, group="Overview",
        filters=(Filter("object", "What changed (e.g. plan, feature_flag)"), Filter("actor", "Who (e-mail)")))
async def admin_audit(ctx: Context) -> Report:
    from src.auth.models import User
    from src.common.admin_audit import AdminAuditLog as AL

    query = select(AL).where(AL.at >= ctx.start_dt, AL.at < ctx.end_dt)
    if ctx.filters.get("object"):
        query = query.where(AL.object_type.ilike(f"%{ctx.filters['object']}%"))
    if ctx.companies is not None:
        query = query.where(or_(AL.target_company_id.in_(ctx.companies), AL.acting_company_id.in_(ctx.companies)))
    if ctx.filters.get("actor"):
        ids = (await ctx.db.execute(select(User.id).where(User.email.ilike(f"%{ctx.filters['actor']}%")))).scalars().all()
        query = query.where(AL.actor_user_id.in_(ids or [None]))
    rows = (await ctx.db.execute(query.order_by(AL.at.desc()).limit(1000))).scalars().all()
    users = dict((await ctx.db.execute(select(User.id, User.email).where(User.id.in_({r.actor_user_id for r in rows}))
                                       )).all()) if rows else {}
    company_names = await names(ctx.db, {r.target_company_id for r in rows})
    kinds: Dict[str, int] = defaultdict(int)
    for r in rows:
        kinds[r.object_type] += 1
    return Report(
        tiles=[Tile("Changes", len(rows)), Tile("People", len({r.actor_user_id for r in rows})),
               Tile("Most changed", max(kinds.items(), key=lambda kv: kv[1])[0] if kinds else "—", "text")],
        columns=[Column("at", "When"), Column("actor", "Who"), Column("action", "Action"), Column("object", "What"),
                 Column("key", "Key"), Column("company", "Company"), Column("change", "From → to"), Column("reason", "Reason")],
        rows=[{"at": r.at, "actor": users.get(r.actor_user_id, r.actor_role), "action": r.action, "object": r.object_type,
               "key": r.object_key, "company": company_names.get(r.target_company_id, "—") if r.target_company_id else "platform",
               "change": f"{_short(r.old_value)} → {_short(r.new_value)}", "reason": r.reason} for r in rows],
        notes=["The newest 1,000 changes in the period; narrow the period or filter for older ones."])


def _short(value: Any) -> str:
    text = "—" if value is None else str(value)
    return text if len(text) <= 60 else text[:57] + "…"


@report(id="R-A25", title="Work queues", description="What waits for each console desk: support, sales, finance, ops",
        workspaces=C, group="Overview", period=False)
async def work_queues(ctx: Context) -> Report:
    """The console home's queues (07 §8.1–8.2): an app_user sees its own functions' queues, an app_admin all."""
    from src.ai.orm.execution import ExecutionRun as R, HumanApproval as H
    from src.ai.orm.usage import UsageLog as U
    from src.billing.billing_models import PaymentTransaction as P
    from src.partners.models import PartnerApplication as PA, PartnerLead as PL, PartnerStatement as PS

    now = datetime.utcnow()
    mine = {"support", "sales", "finance", "ops"} if str(ctx.user.role) == "app_admin" else \
        set(getattr(ctx.user, "staff_functions", None) or [])
    states = await wallet_states(ctx)
    queues: List[Dict[str, Any]] = []

    def add(desk: str, label: str, count: Any, link: str, tone: str = "warning") -> None:
        if desk in mine:
            queues.append({"desk": desk, "queue": label, "count": int(count or 0), "link": link,
                           "tone": tone if count else "neutral"})

    if "support" in mine:
        add("support", "Companies in debt", sum(1 for w in states.values() if w.state != "ok"), "/console/finance/receivables")
        stale = await ctx.tenant_rows(select(func.count()).select_from(H).where(
            H.status == "PENDING", H.requested_at < now - timedelta(hours=24)))
        add("support", "Approvals waiting over a day", sum(r[0] for r in stale), "/console/ops/approvals")
    if "sales" in mine:
        add("sales", "Leads to work", (await ctx.db.execute(select(func.count()).select_from(PL).where(
            PL.status.notin_(("converted", "lost", "expired", "rejected"))))).scalar(), "/console/leads")
        add("sales", "Applications to review", (await ctx.db.execute(select(func.count()).select_from(PA).where(
            PA.status.notin_(("approved", "rejected", "withdrawn"))))).scalar(), "/console/partners?tab=applications")
    if "finance" in mine:
        add("finance", "Failed payments (7 days)", (await ctx.db.execute(select(func.count()).select_from(P).where(
            P.status == "failed", P.created_at >= now - timedelta(days=7)))).scalar(), "/console/finance/payments", "negative")
        add("finance", "Partner statements to approve", (await ctx.db.execute(select(func.count()).select_from(PS).where(
            PS.status.in_(("draft", "disputed"))))).scalar(), "/console/finance/payouts")
    if "ops" in mine:
        add("ops", "Usage unsettled over an hour", (await ctx.db.execute(select(func.count()).select_from(U).where(
            U.settlement_id.is_(None), U.timestamp < now - timedelta(hours=1)))).scalar(), "/console/ops/health", "negative")
        failed = await ctx.tenant_rows(select(func.count()).select_from(R).where(
            R.status == "FAILED", R.parent_run_id.is_(None), R.created_at >= now - timedelta(hours=24)))
        add("ops", "Failed runs (24 h)", sum(r[0] for r in failed), "/console/ops/runs")
    return Report(
        tiles=[Tile(q["queue"], q["count"], tone=q["tone"]) for q in queues],
        columns=[Column("desk", "Desk"), Column("queue", "Queue", "link"), Column("count", "Waiting", "number")],
        rows=queues, drill={"queue": "{link}"})

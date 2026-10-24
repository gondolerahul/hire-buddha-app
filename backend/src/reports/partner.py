"""Partner Portal reports R-P01…R-P10 (Phase 15 T9-6; 07 §7.2).

A partner sees its own customers' **billed** amounts (in its currency) and its
own ledger — never cost, never a sub-partner's customers (overrides are shown
per sub-partner, not per tenant). Gold-only reports are about tenants it
resells; R-P04 is a Silver partner's referrals. A partner_user sees the tenant
health and lead reports (07 §4.4).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List

from sqlalchemy import func, select

from src.reports.facts import CATEGORY_LABEL, ZERO, by_category_day, d, lines, names, pct
from src.reports.framework import Chart, Column, Context, Report, Tile, report

P = ("partner",)
ADMIN = ("partner_admin",)
BOTH = ("partner_admin", "partner_user")


async def _customers(ctx: Context) -> List[Any]:
    from src.partners.models import PartnerAssignment as A

    return list((await ctx.db.execute(select(A).where(A.partner_id == ctx.partner_id, A.until.is_(None)))).scalars().all())


async def _ledger(ctx: Context, *group: Any, where: tuple = ()) -> List[Any]:
    from src.partners.models import PartnerLedgerEntry as E

    query = select(*group, func.coalesce(func.sum(E.amount), 0)).where(
        E.partner_id == ctx.partner_id, E.created_at >= ctx.start_dt, E.created_at < ctx.end_dt, *where)
    return list((await ctx.db.execute(query.group_by(*group) if group else query)).all())


@report(id="R-P01", title="Portfolio overview", description="Customers, what they were billed, plan mix, your earnings",
        workspaces=P, roles=ADMIN, group="Portfolio")
async def portfolio(ctx: Context) -> Report:
    from src.billing.billing_models import BillingLine as L
    from src.billing.plans import plan_of

    customers = await _customers(ctx)
    rows = {r.company_id: r for r in await lines(ctx, L.company_id)}
    named = await names(ctx.db, [c.tenant_id for c in customers])
    mix: Dict[str, int] = defaultdict(int)
    table = []
    for c in customers:
        plan = await plan_of(ctx.db, c.tenant_id)
        mix[plan.name if plan else "Pay-as-you-go"] += 1
        table.append({"tenant": named.get(c.tenant_id), "relationship": c.relationship,
                      "plan": plan.name if plan else "Pay-as-you-go",
                      "billed": ctx.money(rows[c.tenant_id].billed_usd) if c.tenant_id in rows else ZERO})
    [earned] = await _ledger(ctx, where=(_earning(),))
    return Report(
        tiles=[Tile("Customers", len(customers)), Tile("Billed in the period", sum((r["billed"] for r in table), ZERO), "money"),
               Tile("Your earnings", d(earned[0]), "money")],
        chart=Chart("bar", "plan", [{"key": "customers", "label": "Customers"}],
                    [{"plan": k, "customers": v} for k, v in mix.items()]),
        columns=[Column("tenant", "Customer"), Column("relationship", "How"), Column("plan", "Plan"),
                 Column("billed", "Billed", "money")],
        rows=sorted(table, key=lambda r: r["billed"], reverse=True))


def _earning() -> Any:
    from src.partners.models import PartnerLedgerEntry as E
    return E.kind.in_(("commission", "override", "fee_share", "clawback"))


@report(id="R-P02", title="Tenant billed usage", description="Billed by tenant, month and category", workspaces=P,
        roles=ADMIN, partner_types=("GOLD",), group="Portfolio")
async def tenant_usage(ctx: Context) -> Report:
    from src.billing.billing_models import BillingLine as L

    resold = [c.tenant_id for c in await _customers(ctx) if c.relationship == "resold"]
    where = [L.company_id.in_(resold)]
    data, series = await by_category_day(ctx, where)
    month = func.to_char(L.period_day, "YYYY-MM")
    rows = await lines(ctx, L.company_id, month, L.category, where=where)
    named = await names(ctx.db, resold)
    return Report(
        tiles=[Tile("Billed", sum((ctx.money(r.billed_usd) for r in rows), ZERO), "money"), Tile("Tenants", len(resold))],
        chart=Chart("stacked", "day", series, data),
        columns=[Column("tenant", "Tenant"), Column("month", "Month"), Column("category", "Category"),
                 Column("billed", "Billed", "money")],
        rows=[{"tenant": named.get(r[0]), "month": r[1], "category": CATEGORY_LABEL.get(r[2], r[2]),
               "billed": ctx.money(r.billed_usd)} for r in rows])


@report(id="R-P03", title="Tenant health & risk", description="One health score per tenant with its reasons",
        workspaces=P, roles=BOTH, partner_types=("GOLD",), group="Portfolio", period=False)
async def tenant_health(ctx: Context) -> Report:
    from src.ai.reports_service import ReportsService
    from src.billing.billing_models import CreditWallet

    data = await ReportsService(ctx.db).get_tenant_health_scores(ctx.partner_id)
    wallets = {w.company_id: w for w in (await ctx.db.execute(select(CreditWallet).where(
        CreditWallet.company_id.in_([_uuid(t["company_id"]) for t in data["tenants"]] or [None])))).scalars().all()}
    rows = []
    for t in data["tenants"]:
        wallet = wallets.get(_uuid(t["company_id"]))
        reasons = []
        if wallet is not None and wallet.state != "ok":
            reasons.append(f"wallet {wallet.state.replace('_', ' ')}")
        if t.get("failed_runs", 0) > t.get("completed_runs", 0):
            reasons.append("more failed runs than completed")
        if t.get("total_runs_30d", 0) == 0:
            reasons.append("no runs in 30 days")
        rows.append({"tenant": t["company_name"], "score": t.get("health_score"), "at_risk": t.get("at_risk"),
                     "runs_30d": t.get("total_runs_30d"), "failed": t.get("failed_runs"),
                     "state": wallet.state if wallet else "—", "reasons": "; ".join(reasons) or "—"})
    return Report(
        tiles=[Tile("Tenants", len(rows)), Tile("At risk", sum(1 for r in rows if r["at_risk"]), tone="warning")],
        columns=[Column("tenant", "Tenant"), Column("score", "Health", "number"), Column("at_risk", "At risk"),
                 Column("runs_30d", "Runs (30 days)", "number"), Column("failed", "Failed", "number"),
                 Column("state", "Wallet"), Column("reasons", "Why")],
        rows=sorted(rows, key=lambda r: r["score"] or 0))


def _uuid(value: Any) -> Any:
    from uuid import UUID
    try:
        return UUID(str(value))
    except ValueError:
        return value


@report(id="R-P04", title="Referred customers", description="Status, plan, billed this month, commission this month "
        "and lifetime", workspaces=P, roles=ADMIN, partner_types=("SILVER",), group="Portfolio")
async def referred(ctx: Context) -> Report:
    from src.auth.models import Company
    from src.billing.billing_models import BillingLine as L
    from src.billing.plans import plan_of
    from src.partners.models import PartnerLedgerEntry as E

    customers = [c for c in await _customers(ctx) if c.relationship == "referred"]
    ids = [c.tenant_id for c in customers]
    billed = {r.company_id: r for r in await lines(ctx, L.company_id, where=[L.company_id.in_(ids)])}
    period = dict(await _ledger(ctx, E.tenant_id, where=(E.level == 0, _earning())))
    lifetime = dict((await ctx.db.execute(select(E.tenant_id, func.sum(E.amount)).where(
        E.partner_id == ctx.partner_id, E.level == 0, _earning(), E.tenant_id.in_(ids)).group_by(E.tenant_id))).all()) if ids else {}
    companies = {c.id: c for c in (await ctx.db.execute(select(Company).where(Company.id.in_(ids)))).scalars().all()} if ids else {}
    rows = []
    for c in customers:
        plan = await plan_of(ctx.db, c.tenant_id)
        company = companies.get(c.tenant_id)
        rows.append({"customer": company.name if company else None, "status": company.status if company else None,
                     "since": c.since, "plan": plan.name if plan else "Pay-as-you-go",
                     "billed": ctx.money(billed[c.tenant_id].billed_usd) if c.tenant_id in billed else ZERO,
                     "commission": d(period.get(c.tenant_id)), "lifetime": d(lifetime.get(c.tenant_id))})
    return Report(
        tiles=[Tile("Referred customers", len(rows)), Tile("Commission in the period", sum((r["commission"] for r in rows), ZERO), "money"),
               Tile("Lifetime commission", sum((r["lifetime"] for r in rows), ZERO), "money")],
        columns=[Column("customer", "Customer"), Column("status", "Status"), Column("since", "Since", "date"),
                 Column("plan", "Plan"), Column("billed", "Billed", "money"), Column("commission", "Commission", "money"),
                 Column("lifetime", "Lifetime", "money")],
        rows=rows, notes=["Commission on a referral has no end date while your partnership is active (O-8)."])


@report(id="R-P05", title="Earnings", description="Earnings by source, level and status", workspaces=P, roles=ADMIN,
        group="Earnings")
async def earnings(ctx: Context) -> Report:
    from src.partners.models import PartnerLedgerEntry as E

    rows = await _ledger(ctx, E.revenue_kind, E.level, E.status, where=(_earning(),))
    labels = {"usage_topup": "Top-ups", "subscription": "Subscriptions", "setup_fee": "Setup fees",
              "customisation_fee": "Customisation fees"}
    by_source: Dict[str, Decimal] = defaultdict(lambda: ZERO)
    table = []
    for kind, level, status, amount in rows:
        source = labels.get(kind, kind or "Other")
        by_source[source] += d(amount)
        table.append({"source": source, "level": "your customers" if level == 0 else f"override (level {level})",
                      "status": status, "amount": d(amount)})
    return Report(
        tiles=[Tile("Earned", sum(by_source.values(), ZERO), "money")] +
              [Tile(k, v, "money") for k, v in by_source.items()],
        chart=Chart("bar", "source", [{"key": "amount", "label": "Earned"}],
                    [{"source": k, "amount": v} for k, v in by_source.items()]),
        columns=[Column("source", "Source"), Column("level", "Level"), Column("status", "Status"), Column("amount", "Amount", "money")],
        rows=table)


@report(id="R-P06", title="Statements & payouts", description="Statements, TDS, paid", workspaces=P, roles=ADMIN,
        group="Earnings")
async def statements_report(ctx: Context) -> Report:
    from src.partners.models import PartnerStatement as S

    rows = (await ctx.db.execute(select(S).where(S.partner_id == ctx.partner_id, S.period >= ctx.start.replace(day=1) - timedelta(days=366))
                                 .order_by(S.period.desc()))).scalars().all()
    return Report(
        tiles=[Tile("Paid", sum((d(s.net) for s in rows if s.status == "paid"), ZERO), "money"),
               Tile("TDS deducted", sum((d(s.tds) for s in rows), ZERO), "money"),
               Tile("To be paid", sum((d(s.net) for s in rows if s.status in ("draft", "approved")), ZERO), "money")],
        columns=[Column("period", "Month"), Column("gross", "Gross", "money"), Column("tds", "TDS", "money"),
                 Column("net", "Net", "money"), Column("status", "Status"), Column("payout_ref", "Reference")],
        rows=[{"period": f"{s.period:%Y-%m}", "gross": d(s.gross), "tds": d(s.tds), "net": d(s.net), "status": s.status,
               "payout_ref": s.payout_ref} for s in rows])


@report(id="R-P07", title="Network", description="Partners you recruited, their status, your overrides", workspaces=P,
        roles=ADMIN, group="Network")
async def network(ctx: Context) -> Report:
    from src.partners.models import PartnerLedgerEntry as E, PartnerProfile as PP

    first = (await ctx.db.execute(select(PP).where(PP.recruiter_partner_id == ctx.partner_id))).scalars().all()
    second = (await ctx.db.execute(select(PP).where(PP.recruiter_partner_id.in_([p.company_id for p in first])))
              ).scalars().all() if first else []
    overrides = dict(await _ledger(ctx, E.origin_partner_id, where=(E.level >= 1, _earning())))
    named = await names(ctx.db, [p.company_id for p in [*first, *second]])
    rows = [{"partner": named.get(p.company_id), "type": p.partner_type, "status": p.status,
             "level": 1 if p in first else 2, "overrides": d(overrides.get(p.company_id))} for p in [*first, *second]]
    return Report(
        tiles=[Tile("Recruited", len(first)), Tile("Their recruits", len(second)),
               Tile("Overrides in the period", sum((r["overrides"] for r in rows), ZERO), "money")],
        columns=[Column("partner", "Partner"), Column("type", "Type"), Column("status", "Status"),
                 Column("level", "Level", "number"), Column("overrides", "Your overrides", "money")],
        rows=rows, notes=["Their customers are never shown: overrides are per partner (§11.9)."])


@report(id="R-P08", title="Leads", description="Leads by status, conversion, exclusivity ending", workspaces=P,
        roles=BOTH, group="Leads")
async def leads(ctx: Context) -> Report:
    from src.partners.models import PartnerLead as LD

    rows = (await ctx.db.execute(select(LD).where(LD.partner_id == ctx.partner_id, LD.created_at >= ctx.start_dt,
                                                  LD.created_at < ctx.end_dt))).scalars().all()
    soon = datetime.utcnow() + timedelta(days=14)
    counts: Dict[str, int] = defaultdict(int)
    for lead in rows:
        counts[lead.status] += 1
    return Report(
        tiles=[Tile("Leads", len(rows)), Tile("Converted", counts["converted"], hint=f"{pct(counts['converted'], len(rows))} %"),
               Tile("Exclusivity ending in 14 days", sum(1 for x in rows if x.status in ("registered", "accepted", "in_progress")
                                                          and x.exclusive_until and x.exclusive_until <= soon), tone="warning")],
        chart=Chart("bar", "status", [{"key": "leads", "label": "Leads"}], [{"status": k, "leads": v} for k, v in counts.items()]),
        columns=[Column("company", "Company"), Column("status", "Status"), Column("exclusive_until", "Yours until", "date"),
                 Column("created_at", "Registered", "date")],
        rows=[{"company": x.company_name, "status": x.status, "exclusive_until": x.exclusive_until, "created_at": x.created_at}
              for x in rows])


@report(id="R-P09", title="Charges", description="Setup and customisation fees raised, paid, your share",
        workspaces=P, roles=ADMIN, partner_types=("GOLD",), group="Earnings")
async def charges(ctx: Context) -> Report:
    from src.partners.models import OneTimeCharge as O, PartnerLedgerEntry as E

    rows = (await ctx.db.execute(select(O).where(O.partner_id == ctx.partner_id, O.created_at >= ctx.start_dt,
                                                 O.created_at < ctx.end_dt))).scalars().all()
    named = await names(ctx.db, [r.tenant_id for r in rows])
    [share] = await _ledger(ctx, where=(E.kind == "fee_share", E.level == 0))
    return Report(
        tiles=[Tile("Raised", len(rows)), Tile("Paid", sum(1 for r in rows if r.status == "paid")),
               Tile("Your share", d(share[0]), "money")],
        columns=[Column("tenant", "Tenant"), Column("fee", "Fee"), Column("amount", "Amount (theirs)"), Column("status", "Status")],
        rows=[{"tenant": named.get(r.tenant_id), "fee": r.fee_kind, "amount": f"{r.currency} {d(r.amount):,.2f}",
               "status": r.status} for r in rows])


@report(id="R-P10", title="Upsell & plan matrix", description="Tenants near their plan's limits and upgrade candidates",
        workspaces=P, roles=ADMIN, partner_types=("GOLD",), group="Portfolio", period=False)
async def upsell(ctx: Context) -> Report:
    from src.auth.models import User
    from src.billing.features import entitlements_for
    from src.billing.plans import plan_of
    from src.voice.phone_pool_models import PhoneNumber

    resold = [c.tenant_id for c in await _customers(ctx) if c.relationship == "resold"]
    named = await names(ctx.db, resold)
    rows = []
    for tenant_id in resold:
        ents = await entitlements_for(ctx.db, tenant_id)
        plan = await plan_of(ctx.db, tenant_id)
        users = (await ctx.db.execute(select(func.count()).select_from(User).where(User.company_id == tenant_id))).scalar()
        numbers = (await ctx.db.execute(select(func.count()).select_from(PhoneNumber).where(
            PhoneNumber.company_id == tenant_id))).scalar()
        near = []
        for key, used in (("limit.users", users), ("feature.phone_numbers", numbers)):
            limit = ents[key].limit if key in ents else None
            if limit and used >= 0.8 * limit:
                near.append(f"{key.split('.')[-1]} {used}/{limit}")
        locked = [k.split(".", 1)[1] for k, e in ents.items() if k.startswith("feature.") and not e.enabled]
        rows.append({"tenant": named.get(tenant_id), "plan": plan.name if plan else "Pay-as-you-go",
                     "near_limits": ", ".join(near) or "—", "not_in_plan": ", ".join(locked[:6]) or "—",
                     "candidate": bool(near or locked)})
    return Report(
        tiles=[Tile("Upgrade candidates", sum(1 for r in rows if r["candidate"]))],
        columns=[Column("tenant", "Tenant"), Column("plan", "Plan"), Column("near_limits", "Near a limit"),
                 Column("not_in_plan", "Not in their plan"), Column("candidate", "Candidate")],
        rows=sorted(rows, key=lambda r: not r["candidate"]))

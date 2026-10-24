"""Business Workspace reports R-T01…R-T14 (Phase 15 T9-7; 07 §7.3).

A business sees its own billed amounts, in its own currency as they were
locked at settlement — never cost. A tenant_user sees its own work (R-T05,
R-T07, R-T09 for itself; R-T14 "my work"); some reports need the plan's
advanced reports.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List

from sqlalchemy import func, select

from src.reports.facts import CATEGORY_LABEL, ZERO, billed, by_category_day, d, lines, pct
from src.reports.framework import Chart, Column, Context, Filter, Report, Tile, report

B = ("business",)
ADMIN = ("tenant_admin",)
BOTH = ("tenant_admin", "tenant_user")
ADVANCED = "feature.reports.advanced"


def _mine(ctx: Context) -> bool:
    return str(ctx.user.role) == "tenant_user"


async def _entity_names(ctx: Context, ids: Any) -> Dict[Any, str]:
    from src.ai.orm.entity import HierarchicalEntity as E

    wanted = [i for i in ids if i is not None]
    if not wanted:
        return {}
    return {r[0]: r[1] for r in await ctx.tenant_rows(select(E.id, E.name).where(E.id.in_(wanted)))}


@report(id="R-T01", title="Business overview", description="Billed this month against the cap, balance and runway, "
        "runs, calls, approvals", workspaces=B, roles=ADMIN, group="Overview")
async def overview(ctx: Context) -> Report:
    from src.ai.orm.entity import HierarchicalEntity as E
    from src.ai.orm.execution import ExecutionRun as R, HumanApproval as H
    from src.auth.models import Company
    from src.billing.billing_models import WalletLot
    from src.billing.wallet import WalletService
    from src.voice.models import VoiceSession as V

    company = await ctx.db.get(Company, ctx.company_id)
    [total] = await lines(ctx)
    week = await lines_since(ctx, 7)
    balance = await WalletService(ctx.db).balance(ctx.company_id)
    daily = d(week) / 7
    runway = (d(balance["available"]) / daily).quantize(Decimal("1")) if daily > 0 else None
    runs = await ctx.tenant_rows(select(R.status, func.count()).where(
        R.company_id == ctx.company_id, R.parent_run_id.is_(None), R.created_at >= ctx.start_dt,
        R.created_at < ctx.end_dt).group_by(R.status))
    total_runs = sum(n for _s, n in runs)
    completed = sum(n for s, n in runs if s == "COMPLETED")
    calls = await ctx.tenant_rows(select(func.count()).select_from(V).where(
        V.company_id == ctx.company_id, V.started_at >= ctx.start_dt, V.started_at < ctx.end_dt))
    pending = await ctx.tenant_rows(select(func.count()).select_from(H).where(
        H.company_id == ctx.company_id, H.status == "PENDING"))
    agents = await ctx.tenant_rows(select(func.count()).select_from(E).where(
        E.company_id == ctx.company_id, E.deleted_at.is_(None), E.is_template.is_(False)))
    failed = await ctx.tenant_rows(select(R.id, R.entity_id, R.created_at, R.error_message).where(
        R.company_id == ctx.company_id, R.parent_run_id.is_(None), R.status == "FAILED", R.created_at >= ctx.start_dt,
        R.created_at < ctx.end_dt).order_by(R.created_at.desc()).limit(10))
    named = await _entity_names(ctx, {r[1] for r in failed})
    soon = datetime.utcnow() + timedelta(days=7)
    expiring = d((await ctx.db.execute(select(func.coalesce(func.sum(WalletLot.remaining), 0)).where(
        WalletLot.company_id == ctx.company_id, WalletLot.remaining > 0, WalletLot.expires_at <= soon,
        WalletLot.expires_at > datetime.utcnow()))).scalar())
    attention: List[Dict[str, Any]] = []
    if balance["state"] != "ok" or (runway is not None and runway < 7):
        attention.append({"what": "Low balance: recharge", "when": None, "detail": f"{runway} days left" if runway is not None
                          else f"wallet {balance['state']}", "link": "/billing"})
    if expiring > 0:
        attention.append({"what": "Credit expiring in 7 days", "when": None, "detail": f"{expiring:,.2f}", "link": "/billing"})
    if pending and pending[0][0]:
        attention.append({"what": "Approvals waiting", "when": None, "detail": str(pending[0][0]), "link": "/approvals"})
    attention += [{"what": f"Failed: {named.get(entity_id, 'an AI employee')}", "when": at,
                   "detail": (error or "")[:120], "link": f"/work/{run_id}"} for run_id, entity_id, at, error in failed]
    cap = ctx.money(company.monthly_spend_cap_usd) if company and company.monthly_spend_cap_usd else None
    data, series = await by_category_day(ctx)
    return Report(
        tiles=[Tile("Billed", billed(ctx, total), "money", hint=f"cap {cap:,.2f}" if cap else "no spend cap"),
               Tile("Balance", d(balance["available"]), "money",
                    tone="negative" if balance["state"] != "ok" else "neutral"),
               Tile("Runway", f"{runway} days" if runway is not None else "—", "text", hint="at the last 7 days' spend"),
               Tile("AI employees", agents[0][0] if agents else 0),
               Tile("Runs", total_runs, hint=f"{pct(completed, total_runs)} % succeeded"),
               Tile("Calls", calls[0][0] if calls else 0), Tile("Approvals waiting", pending[0][0] if pending else 0)],
        chart=Chart("stacked", "day", series, data),
        columns=[Column("what", "Needs attention", "link"), Column("when", "When", "date"), Column("detail", "Detail")],
        rows=attention, drill={"what": "{link}"})


async def lines_since(ctx: Context, days: int) -> Decimal:
    from src.billing.billing_models import BillingLine as L

    since = (datetime.utcnow() - timedelta(days=days)).date()
    value = (await ctx.db.execute(select(func.coalesce(func.sum(L.billed_ccy), 0)).where(
        L.company_id == ctx.company_id, L.period_day >= since))).scalar()
    return d(value)


@report(id="R-T02", title="Usage & charges", description="Billed by category, AI employee and day; calls per second",
        workspaces=B, roles=ADMIN, group="Billing",
        filters=(Filter("category", "Category", "choice", tuple(CATEGORY_LABEL)),))
async def usage(ctx: Context) -> Report:
    from src.billing.billing_models import BillingLine as L

    where = [L.category == ctx.filters["category"]] if ctx.filters.get("category") else []
    data, series = await by_category_day(ctx, where)
    rows = await lines(ctx, L.category, L.grouping_type, L.grouping_id, where=where)
    entity_names = await _entity_names(ctx, {r.grouping_id for r in rows if r.grouping_type == "entity"})
    table = []
    for r in rows:
        what = entity_names.get(r.grouping_id) if r.grouping_type == "entity" else \
            {"standalone": "Other usage", "phone_number": "Phone number rent"}.get(r.grouping_type or "", r.grouping_type or "—")
        table.append({"category": CATEGORY_LABEL.get(r.category, r.category), "for": what or "An AI employee",
                      "quantity": d(r.quantity), "billed": billed(ctx, r)})
    total = sum((r["billed"] for r in table), ZERO)
    by_cat: Dict[str, Decimal] = defaultdict(lambda: ZERO)
    for r in table:
        by_cat[r["category"]] += r["billed"]
    top = max(by_cat.items(), key=lambda kv: kv[1])[0] if by_cat else "—"
    prior = await _previous_period_total(ctx)
    return Report(
        tiles=[Tile("Billed", total, "money"), Tile("Previous period", prior, "money"),
               Tile("Change", pct(total - prior, prior) if prior else ZERO, "percent"), Tile("Top category", top, "text")],
        chart=Chart("stacked", "day", series, data),
        columns=[Column("category", "Category"), Column("for", "For"), Column("quantity", "Quantity", "number"),
                 Column("billed", "Billed", "money")],
        rows=sorted(table, key=lambda r: r["billed"], reverse=True),
        notes=["Calls are billed per second of the call: duration × the per-second rate."])


async def _previous_period_total(ctx: Context) -> Decimal:
    from src.billing.billing_models import BillingLine as L

    length = ctx.end - ctx.start
    value = (await ctx.db.execute(select(func.coalesce(func.sum(L.billed_ccy), 0)).where(
        L.company_id == ctx.company_id, L.period_day >= ctx.start - length, L.period_day < ctx.start))).scalar()
    return d(value)


@report(id="R-T03", title="Wallet activity", description="Recharges, plan credits, daily credits, usage, expiries, debt",
        workspaces=B, roles=ADMIN, group="Billing")
async def wallet_activity(ctx: Context) -> Report:
    from src.billing.billing_models import WalletEntry as W

    rows = (await ctx.db.execute(select(func.date(W.created_at), W.kind, func.sum(W.amount)).where(
        W.company_id == ctx.company_id, W.created_at >= ctx.start_dt, W.created_at < ctx.end_dt)
        .group_by(func.date(W.created_at), W.kind).order_by(func.date(W.created_at)))).all()
    labels = {"grant": "Credit added", "deduct": "Usage", "expire": "Expired", "debt_add": "Usage owed",
              "debt_repay": "Debt repaid", "adjust": "Adjustment", "refund": "Refund", "convert": "Currency change"}
    totals: Dict[str, Decimal] = defaultdict(lambda: ZERO)
    for _day, kind, amount in rows:
        totals[labels.get(kind, kind)] += d(amount)
    return Report(
        tiles=[Tile(k, v, "money") for k, v in totals.items()],
        columns=[Column("day", "Day", "date"), Column("kind", "What"), Column("amount", "Amount", "money")],
        rows=[{"day": day, "kind": labels.get(kind, kind), "amount": d(amount)} for day, kind, amount in rows])


@report(id="R-T04", title="Credit forecast", description="Burn rate, days left, expiring credit, a suggested recharge",
        workspaces=B, roles=ADMIN, group="Billing", period=False)
async def forecast(ctx: Context) -> Report:
    from src.ai.reports_service import ReportsService
    from src.billing.billing_models import WalletLot

    data = await ReportsService(ctx.db).get_credit_forecast(ctx.company_id)
    if data.get("forecast") is None:
        return Report(notes=["No wallet yet."])
    soon = datetime.utcnow() + timedelta(days=7)
    expiring = (await ctx.db.execute(select(func.coalesce(func.sum(WalletLot.remaining), 0)).where(
        WalletLot.company_id == ctx.company_id, WalletLot.remaining > 0, WalletLot.expires_at <= soon,
        WalletLot.expires_at > datetime.utcnow()))).scalar()
    avg = d(data["burn_rate"]["avg_daily"])
    return Report(
        tiles=[Tile("Available", d(data["wallet"]["total_available"]), "money"), Tile("Spend a day", avg, "money"),
               Tile("Days left", data["forecast"]["days_remaining"]), Tile("Expiring in 7 days", d(expiring), "money"),
               Tile("Suggested recharge (30 days)", max(avg * 30 - d(data["wallet"]["total_available"]), ZERO), "money")],
        chart=Chart("line", "date", [{"key": "projected_balance", "label": "Projected balance"}],
                    data["forecast"]["projection"]))


@report(id="R-T05", title="AI employee performance", description="Runs, success, billed per run, failures",
        workspaces=B, roles=BOTH, entitlement=ADVANCED, group="Work")
async def agent_performance(ctx: Context) -> Report:
    from src.ai.orm.execution import ExecutionRun as R

    query = select(R.entity_id, R.status, func.count(), func.coalesce(func.sum(R.billed_amount), 0),
                   func.avg(R.execution_time_ms)).where(
        R.company_id == ctx.company_id, R.parent_run_id.is_(None), R.created_at >= ctx.start_dt, R.created_at < ctx.end_dt)
    if _mine(ctx):
        query = query.where(R.user_id == ctx.user.id)
    rows = await ctx.tenant_rows(query.group_by(R.entity_id, R.status))
    named = await _entity_names(ctx, {r[0] for r in rows})
    agents: Dict[Any, Dict[str, Any]] = {}
    for entity_id, status, n, billed_usd, avg_ms in rows:
        a = agents.setdefault(entity_id, {"agent": named.get(entity_id, "—"), "runs": 0, "completed": 0, "failed": 0,
                                          "billed": ZERO, "ms": []})
        a["runs"] += n
        a["completed"] += n if status == "COMPLETED" else 0
        a["failed"] += n if status == "FAILED" else 0
        a["billed"] += ctx.money(billed_usd)
        if avg_ms:
            a["ms"].append(float(avg_ms))
    table = []
    for a in agents.values():
        ms = a.pop("ms")
        table.append({**a, "success": pct(a["completed"], a["runs"]),
                      "per_run": (a["billed"] / a["runs"]) if a["runs"] else ZERO,
                      "avg_seconds": round(sum(ms) / len(ms) / 1000, 1) if ms else None})
    return Report(
        tiles=[Tile("Runs", sum(a["runs"] for a in table)),
               Tile("Succeeded", pct(sum(a["completed"] for a in table), sum(a["runs"] for a in table)), "percent"),
               Tile("Billed", sum((a["billed"] for a in table), ZERO), "money")],
        columns=[Column("agent", "AI employee"), Column("runs", "Runs", "number"), Column("success", "Succeeded", "percent"),
                 Column("failed", "Failed", "number"), Column("billed", "Billed", "money"), Column("per_run", "Per run", "money"),
                 Column("avg_seconds", "Average time (s)", "number")],
        rows=sorted(table, key=lambda a: a["runs"], reverse=True))


@report(id="R-T06", title="Campaign analytics", description="Dials, connects, outcomes, billed per call",
        workspaces=B, roles=BOTH, entitlement=ADVANCED, group="Calls")
async def campaigns(ctx: Context) -> Report:
    from src.ai.campaign_models import Campaign as CA, CampaignCall as CC

    query = select(CA.id, CA.name, CC.status, CC.outcome, func.count()).join(CC, CC.campaign_id == CA.id).where(
        CA.company_id == ctx.company_id, CA.created_at >= ctx.start_dt - timedelta(days=90))
    if _mine(ctx):
        query = query.where(CA.created_by == ctx.user.id)
    rows = await ctx.tenant_rows(query.group_by(CA.id, CA.name, CC.status, CC.outcome))
    table: Dict[Any, Dict[str, Any]] = {}
    for cid, name, status, outcome, n in rows:
        row = table.setdefault(cid, {"campaign": name, "contacts": 0, "dialled": 0, "connected": 0, "outcomes": defaultdict(int)})
        row["contacts"] += n
        if status not in ("pending", "leased"):
            row["dialled"] += n
        if status == "completed" or outcome == "success":
            row["connected"] += n
        if outcome:
            row["outcomes"][outcome] += n
    out = [{**{k: v for k, v in r.items() if k != "outcomes"}, "connect_rate": pct(r["connected"], r["dialled"]),
            "outcomes": ", ".join(f"{k} {v}" for k, v in r["outcomes"].items()) or "—"} for r in table.values()]
    [voice] = await lines(ctx, where=[_voice_category()])
    return Report(
        tiles=[Tile("Campaigns", len(out)), Tile("Dialled", sum(r["dialled"] for r in out)),
               Tile("Connected", sum(r["connected"] for r in out)), Tile("Voice billed", billed(ctx, voice), "money")],
        columns=[Column("campaign", "Campaign"), Column("contacts", "Contacts", "number"), Column("dialled", "Dialled", "number"),
                 Column("connected", "Connected", "number"), Column("connect_rate", "Connect rate", "percent"),
                 Column("outcomes", "Outcomes")],
        rows=out)


def _voice_category() -> Any:
    from src.billing.billing_models import BillingLine as L
    return L.category == "voice"


@report(id="R-T07", title="Calls", description="Calls, duration in seconds, billed, inbound and outbound", workspaces=B,
        roles=ADMIN, group="Calls")
async def calls(ctx: Context) -> Report:
    from src.voice.models import VoiceSession as V

    rows = await ctx.tenant_rows(select(V.direction, V.status, V.duration_seconds).where(
        V.company_id == ctx.company_id, V.started_at >= ctx.start_dt, V.started_at < ctx.end_dt))
    buckets = {"under 30 s": 0, "30 s – 2 min": 0, "2 – 10 min": 0, "over 10 min": 0}
    seconds = 0
    for _direction, _status, duration in rows:
        s = duration or 0
        seconds += s
        key = "under 30 s" if s < 30 else "30 s – 2 min" if s < 120 else "2 – 10 min" if s < 600 else "over 10 min"
        buckets[key] += 1
    [voice] = await lines(ctx, where=[_voice_category()])
    return Report(
        tiles=[Tile("Calls", len(rows)), Tile("Inbound", sum(1 for r in rows if r[0] == "inbound")),
               Tile("Outbound", sum(1 for r in rows if r[0] == "outbound")),
               Tile("Minutes", round(seconds / 60, 1)), Tile("Billed", billed(ctx, voice), "money",
                                                             hint="per second of each call")],
        chart=Chart("bar", "length", [{"key": "calls", "label": "Calls"}], [{"length": k, "calls": v} for k, v in buckets.items()]),
        columns=[Column("status", "Status"), Column("calls", "Calls", "number")],
        rows=[{"status": s, "calls": sum(1 for r in rows if r[1] == s)} for s in sorted({r[1] for r in rows})])


@report(id="R-T08", title="Automation", description="Triggers fired, blocked (incl. for balance), failed", workspaces=B,
        roles=ADMIN, group="Work")
async def automation(ctx: Context) -> Report:
    from src.automation.models import Trigger, TriggerFiring as F

    rows = await ctx.tenant_rows(select(Trigger.name, F.outcome, func.count()).join(Trigger, Trigger.id == F.trigger_id).where(
        Trigger.company_id == ctx.company_id, F.decided_at >= ctx.start_dt, F.decided_at < ctx.end_dt)
        .group_by(Trigger.name, F.outcome))
    table: Dict[str, Dict[str, Any]] = {}
    for name, outcome, n in rows:
        row = table.setdefault(name, {"trigger": name, "started": 0, "blocked": 0, "skipped": 0, "failed": 0})
        bucket = "started" if outcome in ("started", "queued") else "blocked" if outcome.startswith("blocked") else \
            "failed" if outcome == "failed" else "skipped"
        row[bucket] += n
    return Report(
        tiles=[Tile(k.capitalize(), sum(r[k] for r in table.values())) for k in ("started", "blocked", "skipped", "failed")],
        columns=[Column("trigger", "Trigger"), Column("started", "Started", "number"), Column("blocked", "Blocked", "number"),
                 Column("skipped", "Skipped", "number"), Column("failed", "Failed", "number")],
        rows=list(table.values()), notes=["Blocked includes waits for balance (negative balance) and budget."])


@report(id="R-T09", title="Approvals", description="Volume, time to approve, rejection rate", workspaces=B, roles=BOTH,
        group="Work")
async def approvals(ctx: Context) -> Report:
    from src.ai.orm.execution import ExecutionRun as R, HumanApproval as H

    query = select(H.status, H.requested_at, H.responded_at).where(
        H.company_id == ctx.company_id, H.requested_at >= ctx.start_dt, H.requested_at < ctx.end_dt)
    if _mine(ctx):
        query = query.join(R, R.id == H.run_id).where(R.user_id == ctx.user.id)
    rows = await ctx.tenant_rows(query)
    answered = [(r[2] - r[1]).total_seconds() / 3600 for r in rows if r[1] and r[2]]
    counts: Dict[str, int] = defaultdict(int)
    for status, *_x in rows:
        counts[status or "PENDING"] += 1
    return Report(
        tiles=[Tile("Requests", len(rows)), Tile("Waiting", counts.get("PENDING", 0)),
               Tile("Average time to answer (h)", round(sum(answered) / len(answered), 1) if answered else None),
               Tile("Rejected", pct(counts.get("REJECTED", 0), len(rows)), "percent")],
        columns=[Column("status", "Status"), Column("count", "Requests", "number")],
        rows=[{"status": k, "count": v} for k, v in counts.items()])


@report(id="R-T10", title="Spend by user", description="Billed per person (the wallet is shared)", workspaces=B,
        roles=ADMIN, entitlement=ADVANCED, group="Billing")
async def spend_by_user(ctx: Context) -> Report:
    from src.ai.orm.execution import ExecutionRun as R
    from src.auth.models import User
    from src.billing.billing_models import WalletEntry as W

    entries = (await ctx.db.execute(select(W.run_id, W.user_id, func.sum(W.amount)).where(
        W.company_id == ctx.company_id, W.kind.in_(("deduct", "debt_add")), W.created_at >= ctx.start_dt,
        W.created_at < ctx.end_dt).group_by(W.run_id, W.user_id))).all()
    run_ids = [r[0] for r in entries if r[0] is not None and r[1] is None]
    run_users = {r[0]: r[1] for r in await ctx.tenant_rows(select(R.id, R.user_id).where(R.id.in_(run_ids)))} if run_ids else {}
    per_user: Dict[Any, Decimal] = defaultdict(lambda: ZERO)
    for run_id, user_id, amount in entries:
        per_user[user_id or run_users.get(run_id)] += abs(d(amount))
    people = dict((await ctx.db.execute(select(User.id, User.email).where(User.id.in_([u for u in per_user if u]))
                                        )).all()) if per_user else {}
    rows = [{"user": people.get(u, "Automation and other usage") if u else "Automation and other usage", "billed": v}
            for u, v in per_user.items()]
    return Report(
        tiles=[Tile("Billed", sum((r["billed"] for r in rows), ZERO), "money"), Tile("People", sum(1 for u in per_user if u))],
        columns=[Column("user", "Person"), Column("billed", "Billed", "money")],
        rows=sorted(rows, key=lambda r: r["billed"], reverse=True))


@report(id="R-T11", title="Phone numbers", description="Numbers, rent, calls per number", workspaces=B, roles=ADMIN,
        group="Calls")
async def numbers(ctx: Context) -> Report:
    from src.billing.billing_models import NumberRental
    from src.voice.models import VoiceSession as V
    from src.voice.phone_pool_models import PhoneNumber

    owned = (await ctx.db.execute(select(PhoneNumber).where(PhoneNumber.company_id == ctx.company_id))).scalars().all()
    rentals = {r.phone_number_id: r for r in (await ctx.db.execute(select(NumberRental).where(
        NumberRental.company_id == ctx.company_id, NumberRental.status != "ended"))).scalars().all()}
    counts = {r[0]: r[1] for r in await ctx.tenant_rows(select(V.phone_number, func.count()).where(
        V.company_id == ctx.company_id, V.started_at >= ctx.start_dt, V.started_at < ctx.end_dt).group_by(V.phone_number))}
    rows = []
    for n in owned:
        rental = rentals.get(n.id)
        rows.append({"number": n.phone_number, "status": n.status, "rent": d(rental.last_amount) if rental else None,
                     "rental": rental.status if rental else "—", "next_charge": rental.next_charge_at if rental else None,
                     "calls": counts.get(n.phone_number, 0)})
    return Report(
        tiles=[Tile("Numbers", len(rows)), Tile("Rent a period", sum((r["rent"] or ZERO for r in rows), ZERO), "money"),
               Tile("Held", sum(1 for r in rows if r["rental"] == "held"), tone="warning")],
        columns=[Column("number", "Number"), Column("status", "Status"), Column("rental", "Rent"),
                 Column("rent", "Rent (30 days)", "money"), Column("next_charge", "Next charge", "date"),
                 Column("calls", "Calls", "number")],
        rows=rows)


@report(id="R-T12", title="Apps & hosting", description="Hosting and database billed by app", workspaces=B,
        roles=ADMIN, group="Billing")
async def apps(ctx: Context) -> Report:
    from src.ai.orm.usage import UsageLog as U
    from src.billing.billing_models import BillingLine as L

    app = U.log_metadata["app"].astext
    rows = (await ctx.db.execute(select(app, func.sum(U.billed_ccy)).where(
        U.company_id == ctx.company_id, U.category.in_(("hosting", "database")), U.timestamp >= ctx.start_dt,
        U.timestamp < ctx.end_dt).group_by(app))).all()
    [hosting] = await lines(ctx, where=[L.category == "hosting"])
    [database] = await lines(ctx, where=[L.category == "database"])
    return Report(
        tiles=[Tile("Hosting", billed(ctx, hosting), "money"), Tile("Database", billed(ctx, database), "money")],
        columns=[Column("app", "App"), Column("billed", "Billed", "money")],
        rows=[{"app": name or "Workspace database and storage", "billed": d(amount)} for name, amount in rows])


@report(id="R-T13", title="Invoices & receipts", description="Invoices and credit notes", workspaces=B, roles=ADMIN,
        group="Billing")
async def invoices(ctx: Context) -> Report:
    from src.billing.billing_models import Invoice as I

    rows = (await ctx.db.execute(select(I).where(I.company_id == ctx.company_id, I.issued_at >= ctx.start_dt,
                                                 I.issued_at < ctx.end_dt).order_by(I.issued_at.desc()))).scalars().all()
    return Report(
        tiles=[Tile("Invoices", len(rows)), Tile("Total paid", sum((d(i.total) for i in rows), ZERO), "money")],
        columns=[Column("number", "Invoice"), Column("issued_at", "Date", "date"), Column("net", "Net", "money"),
                 Column("tax", "GST", "money"), Column("total", "Total", "money")],
        rows=[{"number": i.number, "issued_at": i.issued_at, "net": d(i.net), "tax": d(i.tax), "total": d(i.total)} for i in rows],
        notes=["Download each invoice as a PDF on the Invoices page."])


@report(id="R-T14", title="My work", description="My runs, time saved, my approvals", workspaces=B, roles=("tenant_user",),
        group="Work")
async def my_work(ctx: Context) -> Report:
    from src.ai.reports_service import ReportsService

    data = await ReportsService(ctx.db).get_personal_tasks(user_id=ctx.user.id, company_id=ctx.company_id)
    summary: Dict[str, Any] = data.get("summary", {})
    tasks: List[Dict[str, Any]] = data.get("tasks", [])
    return Report(
        tiles=[Tile("Runs", summary.get("total", 0)), Tile("Succeeded", summary.get("success_rate", 0), "percent"),
               Tile("Time saved (h)", summary.get("estimated_time_saved_hours", 0))],
        columns=[Column("entity_name", "AI employee"), Column("status", "Status"), Column("created_at", "When", "date"),
                 Column("billed", "Billed", "money")],
        rows=[{"entity_name": t["entity_name"], "status": t["status"], "created_at": t["created_at"],
               "billed": ctx.money(t.get("billed_amount") or 0)} for t in tasks])

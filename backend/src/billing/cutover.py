"""Cutover readiness and reconciliation (Phase 15 T10-1, T10-3; plan 08 §4, §6).

    python -m src.billing.cutover [--json] [--markdown FILE] [--shadow-days 14]

One report over the control database, in the order of the production
migration (08 §4), each check with the companies it fails for:

1. reference data — currencies, a rate for every billing currency in use, a
   country profile for every company's country;
2. company geography — country and billing currency set;
3. registry unit codes — every SKU mapped (the migration stops on one that is not);
4. billing formula — the platform formula is set and active;
5. usage — no unsettled row without a rating, none waiting more than a day;
6. wallets — lots equal the old buckets × rate (``wallet_cutover``), every lot
   and the debt equal the ledger (``WalletService.check``), every business and
   partner has a wallet;
7. plans — no live subscription without a plan;
8. partners — every tenant under a partner assigned to it, the tree clean;
9. shadow — no billed difference over the tolerance in the last days.

A *blocker* fails the cutover; a *warning* is for the sign-off. The exit code
is 1 while any blocker remains. ``billing.v2_mode = on`` is refused until the
report has no blockers (``settings_router``).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select

BLOCKER, WARNING = "blocker", "warning"
LIVE_SUBSCRIPTIONS = ("active", "past_due", "paused", "pending_payment")


@dataclass
class Check:
    step: int
    name: str
    severity: str
    ok: bool
    detail: str
    problems: List[Dict[str, Any]] = field(default_factory=list)


def _names(rows: Any) -> Dict[Any, str]:
    return {r.id: r.name for r in rows}


async def _reference(db: Any, companies: List[Any]) -> Check:
    from src.billing.billing_models import CountryProfile, Currency, FxRate

    codes = set((await db.execute(select(Currency.code))).scalars().all())
    used = {c.billing_currency or "INR" for c in companies}
    rated = set((await db.execute(select(FxRate.currency).where(FxRate.effective_from <= datetime.utcnow()))
                 ).scalars().all()) | {"USD"}
    countries = set((await db.execute(select(CountryProfile.country_code))).scalars().all())
    problems = [{"what": f"currency {c} missing"} for c in sorted(used - codes)]
    problems += [{"what": f"no FX rate for {c}"} for c in sorted(used - rated)]
    problems += [{"company": c.name, "what": f"no country profile for {c.country_code}"}
                 for c in companies if c.country_code and c.country_code not in countries]
    return Check(1, "Reference data", BLOCKER, not problems,
                 f"{len(codes)} currencies, rates for {', '.join(sorted(rated & used)) or 'none'}", problems)


def _geography(companies: List[Any]) -> Check:
    problems = [{"company": c.name, "what": "no country" if not c.country_code else "no billing currency"}
                for c in companies if not c.country_code or not c.billing_currency]
    return Check(2, "Company country and currency", BLOCKER, not problems, f"{len(companies)} companies", problems)


async def _units(db: Any) -> Check:
    from sqlalchemy import text

    from src.billing.unit_codes_report import report

    migrated = (await db.execute(text("SELECT count(*) FROM information_schema.columns WHERE "
                                      "table_name = 'integration_registry' AND column_name = 'cost_unit_code'"))).scalar()
    if migrated:
        # After the migration (08 §4 step 3) every row carries its code.
        rows = (await db.execute(text("SELECT service_sku, cost_unit, cost_unit_code FROM integration_registry "
                                      "ORDER BY service_sku"))).all()
        problems = [{"what": f"{r.service_sku}: no unit code (text {r.cost_unit!r})"} for r in rows if not r.cost_unit_code]
        return Check(3, "Registry unit codes", BLOCKER, not problems,
                     f"{len(rows) - len(problems)} coded, {len(problems)} without a code", problems)
    result = await report(db)
    problems = [{"what": f"{u['service_sku']}: unit {u['cost_unit']!r} unmapped"} for u in result["unmapped"]]
    return Check(3, "Registry unit codes", BLOCKER, not problems,
                 f"{len(result['mapped'])} mapped, {len(result['unmapped'])} unmapped", problems)


async def _formula(db: Any) -> Check:
    from src.billing.billing_models import BillingFormula as F

    row = (await db.execute(select(F).where(F.scope == "platform", F.scope_id.is_(None),
                                            F.effective_from <= datetime.utcnow())
                            .order_by(F.effective_from.desc(), F.created_at.desc()).limit(1))).scalar_one_or_none()
    ok = row is not None and bool(row.active)
    detail = f"mf {row.mf}, pf {row.pf}, d {row.d} (version from {row.effective_from:%Y-%m-%d})" if row else "none"
    return Check(4, "Platform billing formula", BLOCKER, ok, detail,
                 [] if ok else [{"what": "no active platform formula: usage would be billed at cost"}])


async def _usage(db: Any, names: Dict[Any, str]) -> Check:
    from src.ai.orm.usage import UsageLog as U

    unrated = (await db.execute(select(U.company_id, func.count()).where(
        U.settlement_id.is_(None), U.billed_usd.is_(None)).group_by(U.company_id))).all()
    stale = (await db.execute(select(U.company_id, func.count()).where(
        U.settlement_id.is_(None), U.timestamp < datetime.utcnow() - timedelta(days=1)).group_by(U.company_id))).all()
    problems = [{"company": names.get(c, str(c)), "what": f"{n} unsettled rows not rated"} for c, n in unrated]
    problems += [{"company": names.get(c, str(c)), "what": f"{n} rows unsettled for over a day"} for c, n in stale]
    return Check(5, "Usage rated and settled", BLOCKER, not problems,
                 f"{sum(n for _c, n in unrated)} unrated, {sum(n for _c, n in stale)} stale", problems)


async def _buckets(db: Any) -> Check:
    """Step 6 before the one-way wallet migration: what each wallet's lots will be. After it, a check of
    the migration lots against the old buckets — a warning then, since old buckets keep expiring."""
    from src.billing.wallet_cutover import report

    cutover = await report(db)
    migrated = bool(cutover.get("migrated"))
    problems = [{"company": p.get("name", p.get("company_id")), "what": "migrated lots ≠ old buckets × rate",
                 "detail": p} for p in cutover["problems"]]
    return Check(6, "Old buckets → lots", WARNING if migrated else BLOCKER, not problems,
                 f"{len(cutover['companies'])} wallets; {'migrated' if migrated else 'not migrated yet'}", problems)


async def _wallets(db: Any, companies: List[Any]) -> Check:
    from src.billing.billing_models import CreditWallet
    from src.billing.wallet import WalletService

    from src.auth.platform import platform_company_id

    problems: List[Dict[str, Any]] = []
    wallets = set((await db.execute(select(CreditWallet.company_id))).scalars().all())
    service = WalletService(db)
    platform = await platform_company_id(db)
    for c in companies:
        if c.id == platform:
            continue
        if c.id not in wallets:
            problems.append({"company": c.name, "what": "no wallet"})
            continue
        for problem in await service.check(c.id):
            problems.append({"company": c.name, "what": problem})
    return Check(6, "Wallets equal their ledgers", BLOCKER, not problems, f"{len(wallets)} wallets", problems)


async def _plans(db: Any, names: Dict[Any, str]) -> Check:
    from src.billing.billing_models import Subscription

    rows = (await db.execute(select(Subscription.company_id, Subscription.status).where(
        Subscription.status.in_(LIVE_SUBSCRIPTIONS), Subscription.plan_id.is_(None)))).all()
    problems = [{"company": names.get(c, str(c)), "what": f"{s} subscription without a plan"} for c, s in rows]
    return Check(7, "Subscriptions on plans", BLOCKER, not problems, f"{len(rows)} without a plan", problems)


async def _partners(db: Any, companies: List[Any]) -> Check:
    from src.partners.models import PartnerAssignment as A
    from src.partners.tree import violations

    by_id = {c.id: c for c in companies}
    open_ = set((await db.execute(select(A.tenant_id).where(A.until.is_(None)))).scalars().all())
    problems = [{"company": c.name, "what": f"under partner {by_id[c.parent_id].name} with no assignment"}
                for c in companies if c.type == "TENANT" and c.parent_id in by_id
                and by_id[c.parent_id].type == "PARTNER" and c.id not in open_]
    problems += [{"what": str(v)} for v in await violations(db)]
    return Check(8, "Partner assignments and tree", BLOCKER, not problems,
                 f"{len(open_)} assigned tenants", problems)


async def _shadow(db: Any, names: Dict[Any, str], days: int, tolerance: Decimal) -> Check:
    from src.billing.billing_models import BillingShadowDiff as S

    since = datetime.utcnow() - timedelta(days=days)
    total = (await db.execute(select(func.count()).select_from(S).where(S.created_at >= since))).scalar() or 0
    rows = (await db.execute(select(S.company_id, func.count(), func.sum(S.diff_usd)).where(
        S.created_at >= since, func.abs(S.diff_usd) > tolerance).group_by(S.company_id))).all()
    problems = [{"company": names.get(c, str(c)), "what": f"{n} settlements differ, Σ {Decimal(s or 0):.6f} USD"}
                for c, n, s in rows]
    if total == 0:
        problems.append({"what": f"no shadow rows in the last {days} days: run the shadow period first"})
    return Check(9, f"Shadow differences ({days} days)", BLOCKER, not problems,
                 f"{total} settlements compared, {sum(n for _c, n, _s in rows)} over {tolerance} USD", problems)


async def _test_deletes(db: Any, companies: List[Any]) -> Check:
    """Go-live (docs/phase15/13 §10): immediate delete switched off, no test businesses left — a warning."""
    from src.billing.settings_catalogue import value

    problems = []
    if await value(db, "offboarding.immediate_delete_enabled"):
        problems.append({"what": "offboarding.immediate_delete_enabled is on: turn it off at go-live"})
    tests = [c for c in companies if getattr(c, "is_test", False)]
    if tests:
        problems.append({"what": f"{len(tests)} test businesses remain: delete them (Delete now) before go-live",
                         "companies": [c.name for c in tests][:20]})
    return Check(10, "Test deletes off, no test businesses", WARNING, not problems,
                 f"{len(tests)} test businesses", problems)


async def readiness(db: Any, *, shadow_days: int = 14, tolerance_usd: Decimal = Decimal("0.01")) -> Dict[str, Any]:
    """The report: ``{ready, at, checks: [...]}`` — ``ready`` when no blocker fails."""
    from src.auth.models import Company

    companies = list((await db.execute(select(Company).order_by(Company.name))).scalars().all())
    names = _names(companies)
    checks = [
        await _reference(db, companies), _geography(companies), await _units(db), await _formula(db),
        await _usage(db, names), await _buckets(db), await _wallets(db, companies), await _plans(db, names),
        await _partners(db, companies), await _shadow(db, names, shadow_days, tolerance_usd),
        await _test_deletes(db, companies),
    ]
    return {"ready": all(c.ok for c in checks if c.severity == BLOCKER), "at": datetime.utcnow().isoformat(),
            "checks": [asdict(c) for c in checks]}


async def require_ready(db: Any) -> None:
    """Refuse the switch-on (409) while the report has a blocker (T10-3)."""
    from fastapi import HTTPException

    report = await readiness(db)
    if not report["ready"]:
        blockers = [f"{c['step']}. {c['name']}: {c['detail']}" for c in report["checks"]
                    if not c["ok"] and c["severity"] == BLOCKER]
        raise HTTPException(status_code=409, detail={"message": "The cutover is not ready", "blockers": blockers})


def markdown(result: Dict[str, Any]) -> str:
    """The report as Markdown, for the sign-off (T10-1)."""
    lines = [f"# Cutover readiness — {result['at'][:16]} UTC", "",
             f"**{'READY' if result['ready'] else 'NOT READY'}**", "", "| Step | Check | Result | Detail |", "|---|---|---|---|"]
    for c in result["checks"]:
        lines.append(f"| {c['step']} | {c['name']} | {'ok' if c['ok'] else c['severity'].upper()} | {c['detail']} |")
    for c in result["checks"]:
        if c["problems"]:
            lines += ["", f"## {c['step']}. {c['name']}", ""]
            lines += [f"- {p.get('company', 'platform')}: {p['what']}" for p in c["problems"][:500]]
    return "\n".join(lines) + "\n"


async def _main(args: argparse.Namespace) -> int:
    from src.common import database
    from src.common.tenancy.session import control_session

    try:
        async with control_session() as db:
            result = await readiness(db, shadow_days=args.shadow_days)
    finally:
        await database.engine.dispose()
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(markdown(result))
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        for c in result["checks"]:
            print(f"{c['step']}. {c['name']:38} {'ok' if c['ok'] else c['severity'].upper():8} {c['detail']}")
            for p in c["problems"][:20]:
                print(f"     - {p.get('company', 'platform')}: {p['what']}")
        print("READY" if result["ready"] else "NOT READY")
    return 0 if result["ready"] else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", metavar="FILE")
    parser.add_argument("--shadow-days", type=int, default=14)
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())

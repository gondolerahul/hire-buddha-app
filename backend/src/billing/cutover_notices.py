"""What customers are told about the Phase 15 changes (T10-4; plan 08 §4, §6, §7).

    python -m src.billing.cutover_notices list
    python -m src.billing.cutover_notices preview <template> [--company NAME]
    python -m src.billing.cutover_notices send <template> [--audience businesses|partners|all] [--yes]

Each template is filled per company (its currency, rate, plan, call rate) and
sent through ``notifications.notify`` to the company's admins: in the app and
by e-mail. A notice is sent once per person (its dedupe key), so a send that
stopped half-way is simply run again. Without ``--yes``, ``send`` only counts.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select

VERSION = "v1"


@dataclass(frozen=True)
class Template:
    key: str
    audience: str           # businesses | partners
    title: str
    body: str
    link: str


TEMPLATES: Dict[str, Template] = {t.key: t for t in (
    Template("billing_currency", "businesses", "Your HireBuddha account is now billed in {currency}",
             "From {date} prices, recharges, your wallet and invoices are in {currency}. Your balance was converted "
             "at {rate} {currency} per US dollar and keeps its expiry date. Payments in India carry GST, shown on "
             "each invoice.", "/billing"),
    Template("per_second_calls", "businesses", "Calls are now billed per second",
             "From {date} each call is billed for the seconds it lasts — {call_rate} a minute, charged per second — "
             "instead of whole minutes. Short calls cost less.", "/reports/R-T07"),
    Template("recharge_validity", "businesses", "New recharges are valid for {validity_days} days",
             "Credit you add from {date} is valid for {validity_days} days. Credit you already have keeps the "
             "expiry date it had.", "/billing"),
    Template("number_rent", "businesses", "Phone numbers now have a monthly rent",
             "From {date} each phone number you hold is charged {number_rent} every 30 days from your wallet. "
             "Release a number you do not use on Calls → Phone numbers.", "/calls/numbers"),
    Template("plans", "businesses", "Your plan: {plan}",
             "HireBuddha now has plans that include features and limits. Your account is on {plan}; everything you "
             "use today stays available. Compare plans on the Plan page.", "/billing/plan"),
    Template("enforcement", "businesses", "What happens when the balance runs out",
             "From {date} work that would take your wallet below zero is recorded as owed and new work waits until "
             "it is repaid; apps stop after a grace period. Set a low-balance alert or a spend cap to stay ahead.",
             "/billing/controls"),
    Template("partner_programme", "partners", "The HireBuddha partner programme",
             "From {date} the partner portal shows your customers, leads, commissions and monthly statements. Your "
             "rates are in your agreement and on the programme guide.", "/partner/guide"),
)}


async def facts(db: Any, company: Any, date: str) -> Dict[str, str]:
    from src.billing.currency import current_rate, to_ccy
    from src.billing.settings_catalogue import value

    currency = company.billing_currency or "INR"
    out = {"date": date, "currency": currency, "rate": "—", "validity_days": "90",
           "call_rate": "the rate on your Usage & charges report",
           "number_rent": "—", "plan": "Pay as you go"}
    try:
        rate = await current_rate(db, currency)
        out["rate"] = f"{rate.units_per_usd.normalize():f}"
    except Exception:  # noqa: BLE001
        rate = None
    try:
        out["validity_days"] = str(await value(db, "wallet.topup_validity_days", company.id))
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.voice.call_credit import billed_rate_per_second

        per_second = await billed_rate_per_second(db, company.id, None)
        if rate is not None and per_second > 0:
            out["call_rate"] = f"{currency} {to_ccy(per_second * 60, rate):.2f}"
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.billing.plans import plan_of

        plan = await plan_of(db, company.id)
        out["plan"] = getattr(plan, "name", None) or out["plan"]
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.billing.price_items import price_for
        from src.billing.rentals import RENT

        price = await price_for(db, RENT, currency)
        out["number_rent"] = f"{currency} {Decimal(str(price.amount)):.2f}"
    except Exception:  # noqa: BLE001
        out["number_rent"] = "the rent shown on Calls → Phone numbers"
    return out


def fill(template: Template, values: Dict[str, str]) -> Dict[str, str]:
    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            return "—"

    return {"title": template.title.format_map(_Safe(values)), "body": template.body.format_map(_Safe(values)),
            "link": template.link}


async def companies_for(db: Any, audience: str, name: Optional[str] = None) -> List[Any]:
    from src.auth.models import Company

    types = {"businesses": ("TENANT",), "partners": ("PARTNER",), "all": ("TENANT", "PARTNER")}[audience]
    query = select(Company).where(Company.type.in_(types), Company.status == "active").order_by(Company.name)
    if name:
        query = query.where(Company.name == name)
    return list((await db.execute(query)).scalars().all())


async def send(db: Any, key: str, *, date: str, audience: Optional[str] = None, dry_run: bool = True,
               company_ids: Optional[List[UUID]] = None) -> Dict[str, Any]:
    """Send (or, dry, count) one template to every company of its audience; ``{companies, told, sample}``."""
    from src.notifications.service import notify

    template = TEMPLATES[key]
    targets = await companies_for(db, audience or template.audience)
    if company_ids is not None:
        targets = [c for c in targets if c.id in company_ids]
    told, sample = 0, None
    for company in targets:
        message = fill(template, await facts(db, company, date))
        sample = sample or {"company": company.name, **message}
        if not dry_run:
            told += await notify(company.id, kind=f"phase15.{key}", title=message["title"], body=message["body"],
                                 link=message["link"], severity="info", dedupe_key=f"phase15:{key}:{VERSION}")
    return {"template": key, "companies": len(targets), "told": told, "dry_run": dry_run, "sample": sample}


async def _main(args: argparse.Namespace) -> int:
    from src.common import database
    from src.common.tenancy.session import control_session

    if args.command == "list":
        for t in TEMPLATES.values():
            print(f"{t.key:20} {t.audience:10} {t.title}")
        return 0
    if args.template not in TEMPLATES:
        print(f"no template {args.template!r}; see `list`")
        return 2
    try:
        async with control_session() as db:
            if args.command == "preview":
                [company] = (await companies_for(db, "all", args.company))[:1] or [None]
                if company is None:
                    print("no such company")
                    return 2
                message = fill(TEMPLATES[args.template], await facts(db, company, args.date))
                print(f"To the admins of {company.name}\n\n{message['title']}\n\n{message['body']}\n\n→ {message['link']}")
                return 0
            result = await send(db, args.template, date=args.date, audience=args.audience, dry_run=not args.yes)
    finally:
        await database.engine.dispose()
    verb = "told" if args.yes else "would tell the admins of"
    print(f"{args.template}: {verb} {result['companies']} companies" + (f" ({result['told']} people)" if args.yes else ""))
    if result["sample"]:
        print(f"e.g. {result['sample']['company']}: {result['sample']['title']}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("list", "preview", "send"))
    parser.add_argument("template", nargs="?", default="")
    parser.add_argument("--company")
    parser.add_argument("--audience", choices=("businesses", "partners", "all"))
    parser.add_argument("--date", default="the next billing cycle", help="when the change applies, as customers read it")
    parser.add_argument("--yes", action="store_true", help="really send (otherwise count only)")
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())

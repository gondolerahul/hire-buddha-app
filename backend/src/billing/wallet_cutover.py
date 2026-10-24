"""The bucket → lot cutover report (Phase 15 T4-2): ``python -m src.billing.wallet_cutover [--json]``.

Per company: the old wallet's live buckets in USD, what they are (or, before
``control_0015_wallet_lots`` has run, would be) in the company's currency at
the rate in effect now, and the lots the cutover created. A company whose lots
do not equal its buckets × rate is listed as a problem; the exit code is 1 then.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from typing import Any

from sqlalchemy import text

BUCKETS = (
    ("daily_credits", "daily_expires_at"),
    ("subscription_credits", "sub_credits_expire_at"),
    ("subscription_bonus_credits", "sub_credits_expire_at"),
    ("wallet_balance", "wallet_expires_at"),
)


async def report(db: Any) -> dict:
    """The report as a dict: ``companies`` and ``problems``."""
    lots_exist = (await db.execute(text("SELECT to_regclass('wallet_lots') IS NOT NULL"))).scalar()
    live = " + ".join(f"(CASE WHEN w.{c} > 0 AND (w.{e} IS NULL OR w.{e} > now()) THEN w.{c} ELSE 0 END)"
                      for c, e in BUCKETS)
    currency = "w.currency" if lots_exist else "COALESCE(c.billing_currency, 'INR')"
    migrated = ("(SELECT COALESCE(SUM(l.original), 0) FROM wallet_lots l WHERE l.company_id = w.company_id "
                "AND l.source_type = 'migration')") if lots_exist else "NULL"
    rows = (await db.execute(text(f"""
        SELECT w.company_id, c.name, {currency} AS currency, {live} AS buckets_usd,
               COALESCE((SELECT r.units_per_usd FROM fx_rates r WHERE r.currency = {currency}
                         AND r.effective_from <= now() ORDER BY r.effective_from DESC, r.created_at DESC
                         LIMIT 1), 1) AS rate,
               {migrated} AS lots_ccy
        FROM credit_wallets w JOIN companies c ON c.id = w.company_id ORDER BY c.name
    """))).all()
    companies, problems = [], []
    for row in rows:
        expected = Decimal(str(row.buckets_usd)) * Decimal(str(row.rate))
        entry = {"company_id": str(row.company_id), "name": row.name, "currency": row.currency,
                 "buckets_usd": str(row.buckets_usd), "rate": str(row.rate), "expected_ccy": str(expected),
                 "lots_ccy": None if row.lots_ccy is None else str(row.lots_ccy)}
        companies.append(entry)
        if row.lots_ccy is not None and Decimal(str(row.lots_ccy)) != expected:
            problems.append(entry)
    return {"migrated": bool(lots_exist), "companies": companies, "problems": problems}


async def _main(as_json: bool) -> int:
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        result = await report(db)
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{'company':40} {'ccy':4} {'buckets USD':>16} {'rate':>10} {'expected':>18} {'lots':>18}")
        for c in result["companies"]:
            print(f"{c['name'][:40]:40} {c['currency']:4} {Decimal(c['buckets_usd']):>16.4f} "
                  f"{Decimal(c['rate']):>10.4f} {Decimal(c['expected_ccy']):>18.4f} "
                  f"{'-' if c['lots_ccy'] is None else format(Decimal(c['lots_ccy']), '.4f'):>18}")
        print(f"{len(result['companies'])} wallets; {len(result['problems'])} do not reconcile"
              + ("" if result["migrated"] else " (not migrated yet: expected amounts only)"))
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    sys.exit(asyncio.run(_main(parser.parse_args().json)))

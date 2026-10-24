"""The rules simulator (Phase 15 T8-13, 07 §5.10): what a chain earns from one payment, before a rule changes.

Staff describe a chain — each level's type, status, KYC, its own paid revenue
this month and months since the level below joined — a revenue kind and an
amount; optionally the month's billed and cost for the margin guard, and
proposed rates. The answer is ``commission.compute`` on today's (or the
proposed) rules: each level's share or why it gets none, the platform's
share, whether the pool cap cut it and what the margin guard would allow.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from src.partners.commission import FEE_KIND_OF, LevelIn, compute
from src.partners.models import EARNING_STATUSES


async def simulate(db: Any, *, revenue_kind: str, base: Decimal, chain: List[Dict[str, Any]],
                   billed: Optional[Decimal] = None, cost: Optional[Decimal] = None,
                   rates: Optional[Dict[str, Decimal]] = None, cap_pct: Optional[Decimal] = None) -> Dict[str, Any]:
    from src.billing.settings_catalogue import value
    from src.partners.rules import commission_rule, fee_rule, unknown_kind

    unknown_kind(revenue_kind)
    if not 1 <= len(chain) <= 3:
        raise HTTPException(status_code=422, detail="a chain is one to three partners (the originator first)")
    min_override = Decimal(str(await value(db, "partners.override_min_monthly_revenue_usd")))
    override_months = int(await value(db, "partners.override_months"))
    levels: List[LevelIn] = []
    cap: Optional[Decimal] = None
    split: Dict[str, Decimal] = {}
    if revenue_kind in FEE_KIND_OF:
        rule = await fee_rule(db, chain[0].get("type", "GOLD"), FEE_KIND_OF[revenue_kind])
        split = {k: Decimal(str(v)) for k, v in ((rule.split if rule else {}) or {}).items()}
    for k, item in enumerate(chain):
        kind = str(item.get("type", "GOLD")).upper()
        if rates and f"level{k}" in rates:
            rate = Decimal(str(rates[f"level{k}"]))
        elif revenue_kind in FEE_KIND_OF:
            rate = split.get("originator" if k == 0 else f"level{k}", Decimal(0))
        else:
            rule = await commission_rule(db, kind, revenue_kind, k)
            rate = rule.rate_pct if rule else Decimal(0)
            if k == 0:
                cap = rule.cap_pct if rule else Decimal(0)
        lv = LevelIn(k, item.get("name") or f"level {k}", rate)
        status = item.get("status", "active")
        if status == "lapsed":
            lv.hold = "lapsed"
        elif status not in EARNING_STATUSES:
            lv.eligible, lv.why = False, f"partner {status}"
        if lv.eligible and not item.get("kyc_verified", True):
            lv.hold = lv.hold or "kyc"
        if lv.eligible and k >= 1:
            if int(item.get("months_since_below_joined", 0)) >= override_months:
                lv.eligible, lv.why = False, f"overrides end after {override_months} months"
            elif Decimal(str(item.get("own_revenue_usd", 0))) < min_override:
                lv.eligible, lv.why = False, "no own paid revenue this month"
        if rate == 0:
            lv.eligible, lv.why = False, lv.why or "no rate"
        levels.append(lv)
    if cap_pct is not None:
        cap = Decimal(str(cap_pct))
    result = compute(Decimal(str(base)), levels, cap_pct=None if revenue_kind in FEE_KIND_OF else cap)
    out = result.view()
    for share in out["shares"]:
        share["partner"] = share.pop("partner_id")
    if billed is not None and cost is not None and revenue_kind not in FEE_KIND_OF:
        share_pct = Decimal(str(await value(db, "partners.max_margin_share_pct")))
        allowed = max(Decimal(str(billed)) - Decimal(str(cost)), Decimal(0)) * share_pct / Decimal(100)
        paid = sum((Decimal(s["amount"]) for s in out["shares"]), Decimal(0))
        out["margin_guard"] = {"margin": str(Decimal(str(billed)) - Decimal(str(cost))), "allowed": str(allowed),
                               "commissions": str(paid), "held": str(max(paid - allowed, Decimal(0)))}
    return out

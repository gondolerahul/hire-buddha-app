"""Shadow billing: each settlement priced the old way and the new way (Phase 15 T3-7, plan §1, §6).

``billing.v2_mode`` (a staff platform setting): ``off`` — nothing recorded;
``shadow`` (default) — every settled run and call writes a
``billing_shadow_diffs`` row: the formula on the run's total (the pre-M15.2
charge) against the sum of its usage rows as rated at write (T3-3), which is
what the settlement (``src.billing.settlement``, T3-5) charges since M15.2.

By linearity the two agree; a difference is a row rated with another formula
version, a row written after the run settled (the hourly job charges it), or a
row whose rating failed (rated at settlement) — each worth explaining.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Optional
from uuid import UUID

MODES = ("off", "shadow")


async def v2_mode(db: Any) -> str:
    from src.common.settings_store import get_platform_setting

    mode = str(await get_platform_setting(db, "billing.v2_mode") or "shadow")
    return mode if mode in MODES else "shadow"


async def record_shadow(control: Any, *, company_id: UUID, subject_type: str, subject_id: Optional[UUID],
                        rows: Iterable[Any], v1_cost_usd: Decimal, v1_billed_usd: Decimal) -> Optional[Any]:
    """Write the comparison for one settlement (the caller commits); nothing when the mode is ``off``."""
    if await v2_mode(control) == "off":
        return None
    from src.billing.billing_models import BillingShadowDiff

    rows = list(rows)
    v2_cost = sum((Decimal(str(r.calculated_cost or 0)) for r in rows), Decimal(0))
    v2_billed = sum((Decimal(str(r.billed_usd or 0)) for r in rows), Decimal(0))
    diff = BillingShadowDiff(
        company_id=company_id, subject_type=subject_type, subject_id=subject_id,
        v1_cost_usd=Decimal(str(v1_cost_usd)), v1_billed_usd=Decimal(str(v1_billed_usd)),
        v2_cost_usd=v2_cost, v2_billed_usd=v2_billed, diff_usd=v2_billed - Decimal(str(v1_billed_usd)),
        rows=len(rows), formula_ids=sorted({str(r.formula_id) for r in rows if r.formula_id}))
    control.add(diff)
    return diff

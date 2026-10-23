"""Shadow billing: each settlement priced the old way and the new way (Phase 15 T3-7, plan §1, §6).

``billing.v2_mode`` (a staff platform setting): ``off`` — nothing recorded;
``shadow`` (default) — every settled run and call writes a
``billing_shadow_diffs`` row: the old path's charge (the formula on the run's
total) against the sum of its usage rows as rated at write (T3-3); ``on`` —
the new settlement charges (WS15-4; refused until it exists).

By linearity the two agree; a difference is a row rated with another formula
version than the settlement used, a row written after the run settled, or a
row whose rating failed — each worth explaining before the switch (T10-3).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Optional
from uuid import UUID

MODES = ("off", "shadow", "on")


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


async def record_settlement(run_db: Any, control: Any, *, company_id: UUID, run_id: Optional[UUID],
                            subject_type: str, grouping_type: Optional[str], grouping_id: Optional[UUID],
                            v1_cost_usd: Decimal, v1_billed_usd: Decimal, descendants: bool = True) -> None:
    """Billing lines and the shadow comparison for one settlement, in a savepoint of ``control``.

    Best-effort: a failure here is logged and rolled back to the savepoint, so
    the settlement it accompanies still commits.
    """
    import logging

    from src.billing.lines import record_lines, settlement_rows

    log = logging.getLogger(__name__)
    try:
        async with control.begin_nested():
            if descendants:
                rows = await settlement_rows(run_db, control, run_id)
            else:
                from sqlalchemy import select

                from src.ai.orm.usage import UsageLog
                rows = list((await control.execute(select(UsageLog).where(UsageLog.run_id == run_id))
                             ).scalars().all()) if run_id else []
            await record_lines(control, company_id=company_id, rows=rows, grouping_type=grouping_type,
                               grouping_id=grouping_id)
            await record_shadow(control, company_id=company_id, subject_type=subject_type, subject_id=run_id,
                                rows=rows, v1_cost_usd=v1_cost_usd, v1_billed_usd=v1_billed_usd)
    except Exception:  # noqa: BLE001 - reporting must not undo the charge
        log.warning("billing lines / shadow for %s %s not recorded", subject_type, run_id, exc_info=True)

"""Settlement: usage charged to the wallet exactly once (Phase 15 T3-5, T3-6; tech design §6.5).

Every usage row is rated when it is written (``billed_usd``, T3-3); settling
it charges that amount to the company's wallet in its billing currency at the
rate in effect now, and marks the row with the settlement, so no row is ever
charged twice and none is free:

    settle(company, rows)
      lock the wallet
      mark the rows settled                 -- only rows WHERE settlement_id IS NULL
      billed_ccy = Σ billed_usd × rate       -- locked for this settlement (FX-4)
      draw the lots in spend order, the rest becomes debt (no free usage, B-10)
      add to the day's billing lines ; claim the run's settlement ; update the state
      the caller commits ; then ``enforcement.wallet_changed``

* Runs settle when they finish (top-level; their descendants' rows with them).
* Calls settle at hang-up (the rows of the call's run).
* Usage with no run — and any row left unsettled for more than ten minutes,
  say by a settlement that failed — is settled by the hourly job
  (``settle_unsettled``), except rows of work still holding credit.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy import func, or_, select, update

logger = logging.getLogger(__name__)
ZERO = Decimal(0)
SWEEP_AFTER = timedelta(minutes=10)
STALE_HOLD = timedelta(hours=24)        # a hold older than this no longer protects its rows from the sweep


@dataclass
class Settled:
    settlement_id: Optional[UUID] = None
    rows: list = field(default_factory=list)
    cost_usd: Decimal = ZERO
    billed_usd: Decimal = ZERO
    billed_ccy: Decimal = ZERO
    currency: Optional[str] = None
    claimed: bool = True
    change: Any = None


async def _rate_unrated(control: Any, company_id: UUID, ids: list) -> None:
    """Rows whose rating failed when written are rated now, so they are not free."""
    from src.ai.orm.usage import UsageLog
    from src.billing.formulas import formula_for

    formula = await formula_for(control, company_id)
    await control.execute(update(UsageLog).where(UsageLog.id.in_(ids), UsageLog.billed_usd.is_(None),
                                                 UsageLog.settlement_id.is_(None))
                          .values(billed_usd=UsageLog.calculated_cost * formula.rate(Decimal(1)),
                                  formula_id=formula.id, category=func.coalesce(UsageLog.category, "tools"))
                          .execution_options(synchronize_session=False))


async def settle_rows(control: Any, *, company_id: UUID, row_ids: Iterable[UUID], source_type: str,
                      source_id: Optional[str] = None, run_id: Optional[UUID] = None,
                      grouping_type: Optional[str] = None, grouping_id: Optional[UUID] = None,
                      claim_run_id: Optional[UUID] = None, reason: Optional[str] = None,
                      v1_cost_usd: Optional[Decimal] = None, v1_billed_usd: Optional[Decimal] = None,
                      subject_type: Optional[str] = None) -> Settled:
    """Charge the unsettled rows among ``row_ids`` (the caller commits).

    ``claim_run_id`` records the run's settlement on its hold (and releases
    it); when the run was settled before, nothing is charged and
    ``claimed`` is False — rows it wrote since are left to the hourly job.
    """
    from src.ai.orm.usage import UsageLog
    from src.billing.credit_service import CreditService
    from src.billing.currency import current_rate, to_ccy
    from src.billing.lines import record_lines
    from src.billing.wallet import WalletService

    wallet_svc = WalletService(control)
    wallet = await wallet_svc.lock(company_id)
    ids = list(row_ids)
    if ids:
        await _rate_unrated(control, company_id, ids)
    rows = list((await control.execute(
        select(UsageLog).where(UsageLog.id.in_(ids), UsageLog.settlement_id.is_(None),
                               UsageLog.company_id == company_id)
        .with_for_update().execution_options(populate_existing=True))).scalars().all()) if ids else []
    rate = await current_rate(control, wallet.currency)
    out = Settled(settlement_id=uuid.uuid4(), rows=rows, currency=wallet.currency)
    out.cost_usd = sum((Decimal(str(r.calculated_cost or 0)) for r in rows), ZERO)
    out.billed_usd = sum((Decimal(str(r.billed_usd or 0)) for r in rows), ZERO)
    out.billed_ccy = to_ccy(out.billed_usd, rate)
    if claim_run_id is not None:
        out.claimed = await CreditService(control).claim_settlement(company_id, claim_run_id, out.billed_usd,
                                                                    out.billed_ccy)
        if not out.claimed:
            return Settled(currency=wallet.currency, claimed=False)
    for row in rows:
        row.settlement_id, row.currency, row.fx_rate_id = out.settlement_id, wallet.currency, rate.id
        row.billed_ccy = to_ccy(Decimal(str(row.billed_usd or 0)), rate)
    by_category: dict = defaultdict(lambda: ZERO)
    for row in rows:
        by_category[row.category or "tools"] += Decimal(str(row.billed_usd or 0))
    for category, usd in sorted(by_category.items()):
        if usd <= 0:
            continue
        change = await wallet_svc.deduct(company_id, to_ccy(usd, rate), source_type=source_type,
                                         source_id=source_id or str(out.settlement_id), category=category,
                                         run_id=run_id, reason=reason, fx_rate_id=rate.id)
        if out.change is None:
            out.change = change
        else:
            out.change.amount += change.amount
            out.change.debt_added += change.debt_added
            out.change.state_after = change.state_after
    if rows:
        try:
            async with control.begin_nested():
                await record_lines(control, company_id=company_id, rows=rows, grouping_type=grouping_type,
                                   grouping_id=grouping_id)
                if v1_billed_usd is not None and subject_type:
                    from src.billing.shadow import record_shadow
                    await record_shadow(control, company_id=company_id, subject_type=subject_type,
                                        subject_id=run_id, rows=rows, v1_cost_usd=v1_cost_usd or ZERO,
                                        v1_billed_usd=v1_billed_usd)
        except Exception:  # noqa: BLE001 - reporting must not undo the charge
            logger.warning("billing lines for settlement %s not recorded", out.settlement_id, exc_info=True)
    if out.change is not None and out.change.debt_added > 0:
        logger.warning("settlement %s of %s: %s went to debt", out.settlement_id, company_id,
                       out.change.debt_added)
    return out


async def settle_run(run_db: Any, control: Any, run: Any, *, grouping_type: str = "entity",
                     grouping_id: Optional[UUID] = None, subject_type: str = "run",
                     descendants: bool = True) -> Settled:
    """A finished top-level run (or a call's run): its rows and its descendants' (§6.5)."""
    from src.ai.orm.usage import UsageLog
    from src.billing.formulas import formula_for_run

    ids = [run.id]
    if descendants:
        from src.ai.governance.run_cost import descendant_run_ids
        ids += await descendant_run_ids(run_db, run.id)
    row_ids = list((await control.execute(select(UsageLog.id).where(
        UsageLog.run_id.in_(ids), UsageLog.settlement_id.is_(None)))).scalars().all())
    total = Decimal(str(getattr(run, "total_cost_usd", None) or 0))
    v1_billed = None
    try:
        v1_billed = (await formula_for_run(control, run.company_id, run.id)).rate(total)
    except Exception:  # noqa: BLE001 - the comparison is optional
        pass
    return await settle_rows(control, company_id=run.company_id, row_ids=row_ids, source_type="settlement",
                             source_id=f"{subject_type}:{run.id}", run_id=run.id, grouping_type=grouping_type,
                             grouping_id=grouping_id if grouping_id is not None else getattr(run, "entity_id", None),
                             claim_run_id=run.id, reason=f"{subject_type} usage", v1_cost_usd=total,
                             v1_billed_usd=v1_billed, subject_type=subject_type)


async def settle_unsettled(control: Any, company_id: UUID, *, now: Optional[datetime] = None,
                           limit: int = 5000) -> Settled:
    """The hourly job's work for one company (T3-6): usage with no run, and any
    row unsettled for more than ten minutes, except rows of work that still
    holds credit (a run or call in progress settles its own)."""
    from src.ai.orm.usage import UsageLog
    from src.billing.billing_models import CreditHold

    now = now or datetime.utcnow()
    running = select(CreditHold.run_id).where(CreditHold.company_id == company_id,
                                              CreditHold.released_at.is_(None),
                                              CreditHold.created_at > now - STALE_HOLD)
    row_ids = list((await control.execute(
        select(UsageLog.id).where(
            UsageLog.company_id == company_id, UsageLog.settlement_id.is_(None),
            or_(UsageLog.run_id.is_(None), UsageLog.timestamp < now - SWEEP_AFTER),
            or_(UsageLog.run_id.is_(None), UsageLog.run_id.notin_(running)))
        .order_by(UsageLog.timestamp).limit(limit))).scalars().all())
    return await settle_rows(control, company_id=company_id, row_ids=row_ids, source_type="settlement",
                             source_id=f"standalone:{now:%Y-%m-%dT%H}", grouping_type="standalone",
                             reason="usage outside runs")


async def companies_with_unsettled(control: Any) -> list[UUID]:
    from src.ai.orm.usage import UsageLog
    return list((await control.execute(select(UsageLog.company_id).where(UsageLog.settlement_id.is_(None))
                                       .distinct())).scalars().all())

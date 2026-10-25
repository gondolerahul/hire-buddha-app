"""The customer price of usage: versioned billing formulas (Phase 15 T3-2, tech design §8.1).

``TB = c·mf·(1 + pf − d)`` — ``c`` the provider cost in USD, ``mf`` the
multiplier, ``pf`` the platform fee and ``d`` the discount, both fractions.
The sales-partner fee ``spf`` left the customer price (K-10): partners earn
commission (WS15-8); a ``billing_config`` that had one was migrated with it
added to ``pf``, so no price changed.

Resolution, first hit: the company's formula → (the plan's, with T6-1) → the
platform's → the identity (billed = cost). Rows are versions: the latest
already in effect wins; a company row with ``active = false`` ends the
company's override.

The formula is linear, so rating each usage row (T3-3) and summing gives what
rating the total gave: Σ TB(cᵢ) = TB(Σ cᵢ).
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select


@dataclass(frozen=True)
class Formula:
    mf: Decimal
    pf: Decimal
    d: Decimal
    id: Optional[UUID] = None
    scope: str = "identity"

    def rate(self, cost: Any) -> Decimal:
        """The billed amount for ``cost`` USD — exact, no rounding."""
        return Decimal(str(cost)) * self.mf * (1 + self.pf - self.d)


IDENTITY = Formula(Decimal(1), Decimal(0), Decimal(0))


def _formula(row: Any) -> Formula:
    return Formula(Decimal(str(row.mf)), Decimal(str(row.pf)), Decimal(str(row.d)), row.id, row.scope)


async def _latest(db: Any, scope: str, scope_id: Optional[UUID], at: datetime) -> Any:
    from src.billing.billing_models import BillingFormula as F

    where = [F.scope == scope, F.effective_from <= at]
    where.append(F.scope_id == scope_id if scope_id is not None else F.scope_id.is_(None))
    return (await db.execute(select(F).where(*where).order_by(F.effective_from.desc(), F.created_at.desc())
                             .limit(1))).scalar_one_or_none()


async def formula_for(db: Any, company_id: Optional[UUID], *, at: Optional[datetime] = None) -> Formula:
    """The formula that prices ``company_id``'s usage at ``at`` (now)."""
    at = at or datetime.utcnow()
    if company_id is not None:
        row = await _latest(db, "company", company_id, at)
        if row is not None and row.active:
            return _formula(row)
    row = await _latest(db, "platform", None, at)
    if row is not None and row.active:
        return _formula(row)
    return IDENTITY


# One formula per run (like tool prices, TX-I1): a formula edited mid-run does
# not price the run's later rows differently from its earlier ones.
_RUN_CACHE_LIMIT = 1024
_RUN_FORMULAS: "OrderedDict[UUID, Formula]" = OrderedDict()


async def formula_for_run(db: Any, company_id: UUID, run_id: Optional[UUID]) -> Formula:
    if run_id is None:
        return await formula_for(db, company_id)
    cached = _RUN_FORMULAS.get(run_id)
    if cached is not None:
        _RUN_FORMULAS.move_to_end(run_id)
        return cached
    formula = await formula_for(db, company_id)
    _RUN_FORMULAS[run_id] = formula
    while len(_RUN_FORMULAS) > _RUN_CACHE_LIMIT:
        _RUN_FORMULAS.popitem(last=False)
    return formula


def forget_run_formulas() -> None:
    """Tests: drop the per-run cache."""
    _RUN_FORMULAS.clear()


async def set_formula(db: Any, *, scope: str, scope_id: Optional[UUID], mf: Decimal, pf: Decimal, d: Decimal,
                      actor: Any, reason: Optional[str] = None, active: bool = True,
                      effective_from: Optional[datetime] = None) -> Any:
    """Add a formula version (audited; the caller commits). ``active=False`` on a
    company ends its override."""
    from src.billing.billing_models import BillingFormula
    from src.common.admin_audit import record_admin_change

    at = effective_from or datetime.utcnow()
    previous = await _latest(db, scope, scope_id, at)
    row = BillingFormula(scope=scope, scope_id=scope_id, mf=mf, pf=pf, d=d, active=active, effective_from=at,
                         created_by=getattr(actor, "id", None), reason=reason)
    db.add(row)
    await db.flush()
    record_admin_change(
        db, actor=actor, action="set", object_type="billing_formula", object_key=scope,
        target_company_id=scope_id if scope == "company" else None,
        old_value=None if previous is None else {"mf": str(previous.mf), "pf": str(previous.pf),
                                                 "d": str(previous.d), "active": previous.active},
        new_value={"mf": str(mf), "pf": str(pf), "d": str(d), "active": active, "formula_id": str(row.id)},
        reason=reason)
    return row

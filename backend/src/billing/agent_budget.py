"""An agent's budget in the billed currency (Phase 15 T5-7, K-19; tech design §5.2).

A builder caps what one run of an agent may be **billed**: ``governance.max_bill
= {"amount": "500", "currency": "INR"}`` — the company's currency, as every
amount it sees. The run-time guards (the budget, the step engine's hard stop,
the plan invariants) count raw provider cost, so when an agent is saved its
``max_cost_usd`` is derived from ``max_bill``: the amount in USD at today's
rate, through the company's formula backwards (``cost = billed / (mf·(1+pf−d))``).
``CreditGuard.over_budget`` compares the plan's **billed** estimate with
``max_bill`` itself.

An agent saved before this has only ``max_cost_usd``; ``max_bill_of`` shows it as
the billed amount it stands for (formula and rate of today), and the builder
saves ``max_bill`` from then on. Tenant databases are not rewritten: they cannot
read a company's currency or formula in split mode, and the reading covers it.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional
from uuid import UUID


def _amount(value: Any) -> Optional[Decimal]:
    try:
        amount = Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None
    return amount if amount > 0 else None


async def cost_cap_for(db: Any, company_id: UUID, max_bill: dict) -> Optional[Decimal]:
    """The raw-cost cap (USD) that ``max_bill`` stands for today."""
    from src.billing.currency import current_rate, to_usd
    from src.billing.formulas import formula_for

    amount = _amount((max_bill or {}).get("amount"))
    if amount is None:
        return None
    currency = str((max_bill or {}).get("currency") or "USD")
    billed_usd = to_usd(amount, await current_rate(db, currency))
    factor = (await formula_for(db, company_id)).rate(Decimal(1))
    return billed_usd / factor if factor > 0 else billed_usd


async def max_bill_of(db: Any, company_id: UUID, governance: Optional[dict]) -> Optional[dict]:
    """The agent's cap as ``{"amount", "currency"}`` in billed terms (derived from ``max_cost_usd``
    for an agent saved before T5-7); ``None`` when it has no cap."""
    from src.billing.currency import current_rate, to_ccy
    from src.billing.formulas import formula_for
    from src.billing.wallet import WalletService

    gov = governance if isinstance(governance, dict) else {}
    if isinstance(gov.get("max_bill"), dict) and _amount(gov["max_bill"].get("amount")) is not None:
        return {"amount": str(gov["max_bill"]["amount"]), "currency": gov["max_bill"].get("currency")}
    cost = _amount(gov.get("max_cost_usd"))
    if cost is None:
        return None
    currency = (await WalletService(db).get(company_id)).currency
    billed = (await formula_for(db, company_id)).rate(cost)
    return {"amount": str(to_ccy(billed, await current_rate(db, currency))), "currency": currency, "derived": True}


async def apply_max_bill(db: Any, company_id: UUID, governance: Any) -> Any:
    """On save: with a ``max_bill``, set its ``max_cost_usd`` (and the company's currency when none is given)."""
    from src.billing.wallet import WalletService

    if not isinstance(governance, dict) or not isinstance(governance.get("max_bill"), dict):
        return governance
    bill = dict(governance["max_bill"])
    if _amount(bill.get("amount")) is None:
        out = dict(governance)
        out.pop("max_bill", None)
        return out
    bill["currency"] = (bill.get("currency") or (await WalletService(db).get(company_id)).currency).upper()
    bill["amount"] = str(Decimal(str(bill["amount"])))
    cap = await cost_cap_for(db, company_id, bill)
    return {**governance, "max_bill": bill, "max_cost_usd": float(cap) if cap is not None else None}


async def over_bill_cap(db: Any, company_id: UUID, governance: Any, billed_estimate_usd: Decimal) -> Optional[str]:
    """The refusal when the plan's billed estimate is past the agent's ``max_bill``, else ``None``."""
    from src.billing.currency import current_rate, to_ccy
    from src.billing.wallet import money

    gov = governance if isinstance(governance, dict) else {}
    bill = gov.get("max_bill") if isinstance(gov.get("max_bill"), dict) else None
    cap = _amount(bill.get("amount")) if bill else None
    if cap is None:
        return None
    currency = str(bill.get("currency") or "USD")
    estimate = to_ccy(billed_estimate_usd, await current_rate(db, currency))
    if estimate <= cap:
        return None
    return (f"The plan is estimated at {money(estimate, currency)}, over this agent's budget of "
            f"{money(cap, currency)}: raise the budget or shorten the plan")

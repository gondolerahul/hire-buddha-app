"""A call's credit while it runs (Phase 15 T4-5, T4-6; tech design §6.3, §6.4).

* **Hold** — once the call's run is open, it holds
  ``voice.call_hold_seconds`` (300) of the call's billed per-second rate, at
  least ``admission.min_balance.call``, like a run holds its estimate; other
  work cannot be admitted on that credit. The settlement at hang-up releases it.
* **Mid-call check** — every ``voice.credit_check_seconds`` (30) the call's
  bill so far (its seconds at the rate, plus its tool calls) is held against
  what it may spend: free credit plus the wallet's tolerance, less any debt.
  At the limit — or once the wallet is over its tolerance or suspended — the
  agent says a closing line and the call ends.

The per-second rate is the telephony SKU's price through the company's
formula; the live model's audio is billed on top at hang-up, so the check is
a floor, not the whole bill.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

CLOSING_LINE = ("[SYSTEM: The account has run out of credit. Apologise briefly, say a short goodbye and end "
                "the call now.]")
ZERO = Decimal(0)


async def billed_rate_per_second(db: Any, company_id: UUID, provider: Optional[str]) -> Decimal:
    """USD billed per second of the call's telephony (0 when no SKU prices it)."""
    from src.ai.usage_service import price_at
    from src.billing.formulas import formula_for
    from src.billing.units import Dimension
    from src.voice.usage_logger import VoiceUsageLogger

    sku = VoiceUsageLogger.TELEPHONY_SKU_MAP.get(provider or "")
    if not sku:
        return ZERO
    entry = await VoiceUsageLogger(db)._get_sku(company_id, sku)
    price = price_at(entry, Decimal(1), Dimension.SECOND)
    return (await formula_for(db, company_id)).rate(price.cost) if price.priced else ZERO


async def place_call_hold(db: Any, company_id: UUID, run_id: UUID, provider: Optional[str]) -> Decimal:
    """Hold the call's credit (§6.4); returns the amount held, in the wallet's currency.

    Raises ``InsufficientCreditsError`` when the credit is gone since admission
    (another call or run took it); the caller ends the call then.
    """
    from src.billing.credit_service import CreditService
    from src.billing.settings_catalogue import value

    seconds = Decimal(str(await value(db, "voice.call_hold_seconds", company_id)))
    floor = Decimal(str(await value(db, "admission.min_balance.call", company_id)))
    estimate = seconds * await billed_rate_per_second(db, company_id, provider)
    return await CreditService(db).place_hold(company_id, run_id, estimate, floor)


async def call_headroom(db: Any, company_id: UUID, run_id: Optional[UUID], *, seconds: Decimal,
                        rate_usd: Decimal, tools_cost_usd: Decimal = ZERO) -> tuple[Decimal, dict]:
    """What the call may still spend (≤ 0: end it), in the wallet's currency, and the balance."""
    from src.billing.credit_service import CreditService
    from src.billing.formulas import formula_for

    tools_billed = (await formula_for(db, company_id)).rate(tools_cost_usd) if tools_cost_usd else ZERO
    return await CreditService(db).headroom(company_id, run_id, seconds * rate_usd + tools_billed)

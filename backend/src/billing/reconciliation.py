"""What a carrier charges us for a call, next to what we bill (Phase 15 T1-6, K-2, O-1).

Customers are billed per second, exactly (REQ-CO-1). Carriers (Tata, Twilio in
India) bill by pulse — usually per started minute — so a short call costs us
more than we bill at the same rate. Each telephony SKU carries
``service_metadata.provider_billing_increment_seconds`` (e.g. 60): **used only
here**, by the cost reconciliation report (R-A03), to show the carrier's true
cost and the margin gap. Nothing in customer billing reads it.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from typing import Any, Optional

from src.billing.units import price_usd

INCREMENT_KEY = "provider_billing_increment_seconds"
DEFAULT_INCREMENT_SECONDS = 60


def billing_increment(entry: Any) -> int:
    """The carrier's pulse for this SKU, in seconds (default 60)."""
    value = (getattr(entry, "service_metadata", None) or {}).get(INCREMENT_KEY)
    return int(value) if value else DEFAULT_INCREMENT_SECONDS


def carrier_seconds(seconds: Decimal, increment: int) -> Decimal:
    """The seconds a carrier bills for a call of ``seconds``: whole pulses, the last one started."""
    seconds = Decimal(str(seconds))
    if seconds <= 0:
        return Decimal("0")
    pulses = (seconds / increment).to_integral_value(rounding=ROUND_CEILING)  # pulses started
    return pulses * increment


def call_cost_gap(seconds: Decimal, entry: Any, increment: Optional[int] = None) -> dict:
    """The call's cost per second (what we bill on) and per carrier pulse (what we pay)."""
    increment = increment or billing_increment(entry)
    billed_seconds = Decimal(str(seconds))
    paid_seconds = carrier_seconds(billed_seconds, increment)
    rate, code = Decimal(str(entry.internal_cost)), entry.cost_unit_code
    per_second = price_usd(billed_seconds, rate, code)
    per_pulse = price_usd(paid_seconds, rate, code)
    return {"seconds": billed_seconds, "carrier_seconds": paid_seconds, "increment_seconds": increment,
            "cost_per_second": per_second, "carrier_cost": per_pulse, "gap": per_pulse - per_second}

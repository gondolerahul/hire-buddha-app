"""The only list of cost units (Phase 15 T1-1, REQ-CO-2; tech design §2).

A registry price is ``internal_cost`` USD per ``per_quantity`` of a
``Dimension``: ``PER_1M_TOKENS`` is per 1,000,000 tokens, ``PER_MINUTE`` per
60 seconds. Pricing is ``cost_usd = quantity × internal_cost ÷ per_quantity`` —
no other arithmetic, no text parsing.

Each meter emits a quantity in one dimension (an LLM call: tokens; a phone
call: seconds; hosting: vCPU-hours …); a SKU whose unit has another dimension
is a unit mismatch, not a price.

The control table ``cost_units`` holds the same list (seeded by migration
``control_0006_cost_units``), so a registry row can name its unit by code with
a foreign key (T1-2). ``tests/integration/test_cost_units.py`` fails when the
table and ``UNITS`` differ, ``tests/unit/test_cost_units.py`` when the
migrations' ``COST_UNITS`` do: a new unit is a change here *and* a migration
that inserts its row (listing it in its own ``COST_UNITS``).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Dimension(StrEnum):
    """What a meter counts."""
    TOKEN = "token"
    CHARACTER = "character"
    SECOND = "second"
    REQUEST = "request"
    IMAGE = "image"
    VIDEO = "video"
    MESSAGE = "message"
    EMAIL = "email"
    PAGE = "page"
    QUERY = "query"
    GB = "gb"
    GB_HOUR = "gb_hour"
    GB_MONTH = "gb_month"
    VCPU_HOUR = "vcpu_hour"
    DAY = "day"
    MONTH = "month"
    UNIT = "unit"


class CostUnit(StrEnum):
    """A price's unit, by code (the value stored in ``cost_units.code``)."""
    PER_TOKEN = "PER_TOKEN"
    PER_1K_TOKENS = "PER_1K_TOKENS"
    PER_1M_TOKENS = "PER_1M_TOKENS"
    PER_CHARACTER = "PER_CHARACTER"
    PER_1K_CHARACTERS = "PER_1K_CHARACTERS"
    PER_1M_CHARACTERS = "PER_1M_CHARACTERS"
    PER_SECOND = "PER_SECOND"
    PER_MINUTE = "PER_MINUTE"
    PER_HOUR = "PER_HOUR"
    PER_REQUEST = "PER_REQUEST"
    PER_1K_REQUESTS = "PER_1K_REQUESTS"
    PER_IMAGE = "PER_IMAGE"
    PER_VIDEO = "PER_VIDEO"
    PER_MESSAGE = "PER_MESSAGE"
    PER_EMAIL = "PER_EMAIL"
    PER_PAGE = "PER_PAGE"
    PER_QUERY = "PER_QUERY"
    PER_1K_QUERIES = "PER_1K_QUERIES"
    PER_GB = "PER_GB"
    PER_GB_HOUR = "PER_GB_HOUR"
    PER_GB_MONTH = "PER_GB_MONTH"
    PER_VCPU_HOUR = "PER_VCPU_HOUR"
    PER_DAY = "PER_DAY"
    PER_MONTH = "PER_MONTH"
    PER_UNIT = "PER_UNIT"


@dataclass(frozen=True)
class UnitSpec:
    dimension: Dimension
    per_quantity: Decimal
    label: str


def _spec(dimension: Dimension, per_quantity: int, label: str) -> UnitSpec:
    return UnitSpec(dimension, Decimal(per_quantity), label)


UNITS: dict[CostUnit, UnitSpec] = {
    CostUnit.PER_TOKEN: _spec(Dimension.TOKEN, 1, "per token"),
    CostUnit.PER_1K_TOKENS: _spec(Dimension.TOKEN, 1_000, "per 1K tokens"),
    CostUnit.PER_1M_TOKENS: _spec(Dimension.TOKEN, 1_000_000, "per 1M tokens"),
    CostUnit.PER_CHARACTER: _spec(Dimension.CHARACTER, 1, "per character"),
    CostUnit.PER_1K_CHARACTERS: _spec(Dimension.CHARACTER, 1_000, "per 1K characters"),
    CostUnit.PER_1M_CHARACTERS: _spec(Dimension.CHARACTER, 1_000_000, "per 1M characters"),
    # Time is metered in seconds; a per-minute or per-hour price is a price per
    # 60 or 3,600 of them (calls are billed per second, REQ-CO-1).
    CostUnit.PER_SECOND: _spec(Dimension.SECOND, 1, "per second"),
    CostUnit.PER_MINUTE: _spec(Dimension.SECOND, 60, "per minute"),
    CostUnit.PER_HOUR: _spec(Dimension.SECOND, 3_600, "per hour"),
    CostUnit.PER_REQUEST: _spec(Dimension.REQUEST, 1, "per request"),
    CostUnit.PER_1K_REQUESTS: _spec(Dimension.REQUEST, 1_000, "per 1K requests"),
    CostUnit.PER_IMAGE: _spec(Dimension.IMAGE, 1, "per image"),
    CostUnit.PER_VIDEO: _spec(Dimension.VIDEO, 1, "per video"),
    CostUnit.PER_MESSAGE: _spec(Dimension.MESSAGE, 1, "per message"),
    CostUnit.PER_EMAIL: _spec(Dimension.EMAIL, 1, "per e-mail"),
    CostUnit.PER_PAGE: _spec(Dimension.PAGE, 1, "per page"),
    CostUnit.PER_QUERY: _spec(Dimension.QUERY, 1, "per query"),
    CostUnit.PER_1K_QUERIES: _spec(Dimension.QUERY, 1_000, "per 1K queries"),
    CostUnit.PER_GB: _spec(Dimension.GB, 1, "per GB"),
    CostUnit.PER_GB_HOUR: _spec(Dimension.GB_HOUR, 1, "per GB-hour"),
    CostUnit.PER_GB_MONTH: _spec(Dimension.GB_MONTH, 1, "per GB-month"),
    CostUnit.PER_VCPU_HOUR: _spec(Dimension.VCPU_HOUR, 1, "per vCPU-hour"),
    CostUnit.PER_DAY: _spec(Dimension.DAY, 1, "per day"),
    CostUnit.PER_MONTH: _spec(Dimension.MONTH, 1, "per month"),
    CostUnit.PER_UNIT: _spec(Dimension.UNIT, 1, "per unit"),
}


def unit_spec(code: str | CostUnit) -> UnitSpec:
    """The unit's dimension, quantity and label; ``ValueError`` for an unknown code."""
    try:
        return UNITS[CostUnit(code)]
    except ValueError:
        raise ValueError(f"unknown cost unit {code!r}: one of {', '.join(CostUnit)}") from None


def price_usd(quantity: Decimal, internal_cost: Decimal, code: str | CostUnit) -> Decimal:
    """``quantity`` (in the unit's dimension) at ``internal_cost`` USD per the unit."""
    return Decimal(quantity) * Decimal(internal_cost) / unit_spec(code).per_quantity

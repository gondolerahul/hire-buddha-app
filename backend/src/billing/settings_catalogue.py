"""Every money setting: what it is, where it may be set, who sets it (Phase 15 T5-1, tech design §8.4, REQ-DC-6).

A setting has a type, bounds, a default and the scopes it may be set at. Values
live in ``platform_settings`` (``src.common.settings_store``); ``resolve``
reads a company's value from the most specific scope that sets it:

    company → its partner (the parent PARTNER company) → its plan (T6-1) → platform → the default

and says which one did (``explain``). Amounts are USD (K-16): the screens show
them in the display currency beside it. Only ``app_admin`` edits them (§8.4).
A key not in ``CATALOGUE`` cannot be read or written —
``tests/unit/test_settings_catalogue.py`` fails on code that reads one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from uuid import UUID

PLATFORM, PLAN, PARTNER, COMPANY = "platform", "plan", "partner", "company"
LEVELS = ("GRAPH", "LOOP", "PROCESS", "AGENT", "SKILL", "ACTION")


@dataclass(frozen=True)
class SettingSpec:
    key: str
    type: str                       # usd | int | bool | choice | usd_list | decimal | text
    default: Any
    help: str
    scopes: tuple[str, ...] = (PLATFORM,)
    minimum: Optional[Decimal] = None
    maximum: Optional[Decimal] = None
    choices: tuple[str, ...] = ()
    unit: Optional[str] = None
    nullable: bool = False
    group: str = "billing"
    editors: tuple[str, ...] = field(default=("app_admin",))


def _usd(key: str, default: Optional[str], help: str, scopes=(PLATFORM,), nullable=False, group="billing",
         maximum: Optional[str] = None) -> SettingSpec:
    return SettingSpec(key, "usd", Decimal(default) if default is not None else None, help, tuple(scopes),
                       minimum=Decimal(0), maximum=Decimal(maximum) if maximum else None, unit="USD",
                       nullable=nullable, group=group)


def _int(key: str, default: int, help: str, scopes=(PLATFORM,), minimum=0, maximum=None, unit=None,
         group="billing") -> SettingSpec:
    return SettingSpec(key, "int", default, help, tuple(scopes), minimum=Decimal(minimum),
                       maximum=Decimal(maximum) if maximum is not None else None, unit=unit, group=group)


_MIN_BALANCE = {"GRAPH": "2.00", "LOOP": "1.00", "PROCESS": "0.50", "AGENT": "0.05", "SKILL": "0.02",
                "ACTION": "0.01"}

_SPECS = [
    SettingSpec("billing.display_currency", "choice", "INR", "The currency staff views show amounts in (REQ-BL-4)",
                choices=("INR", "USD"), group="currency"),
    SettingSpec("billing.default_currency", "choice", "INR",
                "The billing currency of a company whose country has no profile (REQ-BL-2)",
                choices=("INR", "USD"), group="currency"),
    SettingSpec("billing.v2_mode", "choice", "shadow",
                "Record each settlement priced two ways (shadow) or not (off) — T3-7", choices=("off", "shadow"),
                group="billing"),
    *[_usd(f"admission.min_balance.{level}", amount,
           f"Free credit {'an' if level[0] in 'AEIOU' else 'a'} {level.lower()} needs to start (billed amount)", (PLATFORM, PLAN, COMPANY), group="admission")
      for level, amount in _MIN_BALANCE.items()],
    _usd("admission.min_balance.default", "0.05", "Free credit any other run needs to start",
         (PLATFORM, PLAN, COMPANY), group="admission"),
    _usd("admission.min_balance.call", "0.05", "Free credit needed to take or make a call", (PLATFORM, PLAN),
         group="admission"),
    _int("admission.hold_history_runs", 10, "Finished runs averaged into a run's credit hold", minimum=1,
         maximum=100, group="admission"),
    _int("voice.call_hold_seconds", 300, "Seconds of a call's billed rate held when it starts", (PLATFORM, PLAN),
         minimum=0, maximum=7200, unit="seconds", group="admission"),
    _int("voice.credit_check_seconds", 30, "How often a live call checks the credit it may still spend",
         minimum=5, maximum=600, unit="seconds", group="admission"),
    _usd("wallet.negative_tolerance_usd", "0", "How far a wallet may go below zero before running work stops "
         "(Q1; per plan with T6-1)", (PLATFORM, PLAN, COMPANY), group="wallet"),
    _int("billing.app_stop_grace_hours", 0, "Hours a company in debt keeps its apps running (K-14)",
         (PLATFORM, PLAN), maximum=720, unit="hours", group="wallet"),
    _int("billing.suspend_after_days", 7, "Days over the tolerance before a company is suspended (read-only)",
         minimum=1, maximum=365, unit="days", group="wallet"),
    _int("wallet.topup_validity_days", 90, "Days a recharge lasts (REQ-WL-1)", (PLATFORM, PLAN), minimum=1,
         maximum=3650, unit="days", group="wallet"),
    _usd("wallet.topup_min_usd", "5", "The smallest recharge", group="wallet"),
    _usd("wallet.topup_max_usd", "10000", "The largest recharge", group="wallet"),
    SettingSpec("wallet.topup_presets_usd", "usd_list", [10, 25, 50, 100], "The recharge buttons", unit="USD",
                group="wallet"),
    _int("numbers.hold_after_days_over_tolerance", 7, "Days over the tolerance before a company's numbers are held",
         minimum=1, maximum=365, unit="days", group="wallet"),
    _int("checkout.abandoned_after_hours", 24, "Hours before an unpaid checkout is marked abandoned", minimum=1,
         maximum=720, unit="hours", group="payments"),
    _int("subscriptions.total_cycles", 120, "Billing cycles a Razorpay subscription is created for", minimum=1,
         maximum=1200, group="payments"),
    _int("alerts.low_balance_pct", 20, "Warn when the balance falls below this share of the last recharge",
         (PLATFORM, COMPANY), maximum=100, unit="%", group="alerts"),
    _usd("alerts.low_balance_usd", None, "Warn when the balance falls below this amount", (PLATFORM, COMPANY),
         nullable=True, group="alerts"),
    SettingSpec("daily_credits.inherit_up_partner_chain", "bool", False,
                "A partner's tenant with no policy of its partner's takes the nearest upline partner's",
                group="daily_credits"),
    # GST and invoices (Phase 15 T6-5, tech design §12.3, Q8).
    SettingSpec("tax.gst_rate", "decimal", Decimal("18"), "GST on payments made in India (%, CGST + SGST or IGST)",
                minimum=Decimal(0), maximum=Decimal(40), unit="%", group="tax"),
    SettingSpec("tax.supplier_legal_name", "text", "Buddha Consulting LLP", "The supplier on invoices", group="tax"),
    SettingSpec("tax.supplier_gstin", "text", "", "The supplier's GSTIN on invoices", group="tax"),
    SettingSpec("tax.supplier_state", "text", "KA",
                "The supplier's state (two-character code): the same state is CGST + SGST, another IGST",
                group="tax"),
    SettingSpec("tax.supplier_address", "text", "", "The supplier's address on invoices", group="tax"),
    SettingSpec("tax.lut_number", "text", "", "The Letter of Undertaking for zero-rated exports", group="tax"),
    SettingSpec("invoice.series_prefix", "text", "HB", "Invoice numbers: <prefix>/<financial year>/<number>",
                group="tax"),
    # The partner programme (Phase 15 WS15-8, tech design §11.3, §11.6, §11.7).
    _int("partners.max_depth", 3, "Levels a partner may be below the platform (O-9)", minimum=1, maximum=5,
         group="partners"),
    _int("partners.holdback_days", 30, "Days a commission is held before it can be paid", minimum=0, maximum=365,
         unit="days", group="partners"),
    _int("partners.probation_holdback_days", 60, "The holdback while a partner is on probation", minimum=0,
         maximum=365, unit="days", group="partners"),
    _int("partners.probation_days", 90, "How long a new partner is on probation", minimum=0, maximum=730,
         unit="days", group="partners"),
    _usd("partners.payout_min_usd", "50", "The smallest payout; less carries forward", group="partners"),
    SettingSpec("partners.tds_pct", "decimal", Decimal("5"), "TDS deducted from a commission payout (Sec. 194H)",
                minimum=Decimal(0), maximum=Decimal(40), unit="%", group="partners"),
    _usd("partners.override_min_monthly_revenue_usd", "100",
         "The month's own paid revenue an upline needs to earn overrides", group="partners"),
    _int("partners.override_months", 24, "Months an upline earns overrides on a partner it recruited",
         minimum=0, maximum=600, unit="months", group="partners"),
    SettingSpec("partners.max_margin_share_pct", "decimal", Decimal("50"),
                "Commissions on a tenant's usage in a month may be at most this share of its margin",
                minimum=Decimal(0), maximum=Decimal(100), unit="%", group="partners"),
    _int("partners.lead_exclusivity_days", 90, "Days a registered lead is the partner's alone", minimum=1,
         maximum=365, unit="days", group="partners"),
    _int("partners.fee_grace_days", 30, "Days after the fee lapses before the partner is suspended", minimum=0,
         maximum=365, unit="days", group="partners"),
    _int("partners.statement_day", 5, "The day of the month last month's statements are made", minimum=1,
         maximum=28, group="partners"),
]
CATALOGUE: dict[str, SettingSpec] = {spec.key: spec for spec in _SPECS}


class UnknownSetting(KeyError):
    pass


class InvalidSetting(ValueError):
    pass


def spec_for(key: str) -> SettingSpec:
    try:
        return CATALOGUE[key]
    except KeyError:
        raise UnknownSetting(key) from None


def coerce(spec: SettingSpec, value: Any) -> Any:
    """``value`` as the setting stores it (JSON), or ``InvalidSetting``."""
    if value is None:
        if spec.nullable:
            return None
        raise InvalidSetting(f"{spec.key} needs a value")

    def _number(raw: Any) -> Decimal:
        if isinstance(raw, bool):
            raise InvalidSetting(f"{spec.key} is a number")
        try:
            number = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            raise InvalidSetting(f"{spec.key} is a number") from None
        if spec.minimum is not None and number < spec.minimum:
            raise InvalidSetting(f"{spec.key} must be at least {spec.minimum}")
        if spec.maximum is not None and number > spec.maximum:
            raise InvalidSetting(f"{spec.key} must be at most {spec.maximum}")
        return number

    if spec.type == "usd" or spec.type == "decimal":
        return str(_number(value))
    if spec.type == "int":
        number = _number(value)
        if number != number.to_integral_value():
            raise InvalidSetting(f"{spec.key} is a whole number")
        return int(number)
    if spec.type == "bool":
        if not isinstance(value, bool):
            raise InvalidSetting(f"{spec.key} is true or false")
        return value
    if spec.type == "choice":
        if value not in spec.choices:
            raise InvalidSetting(f"{spec.key} is one of {', '.join(spec.choices)}")
        return value
    if spec.type == "usd_list":
        if not isinstance(value, list) or not value:
            raise InvalidSetting(f"{spec.key} is a list of amounts")
        return [str(_number(v)) for v in value]
    if spec.type == "text":
        if not isinstance(value, str) or len(value) > 500:
            raise InvalidSetting(f"{spec.key} is text of at most 500 characters")
        return value.strip()
    raise InvalidSetting(f"{spec.key}: unknown type {spec.type}")  # pragma: no cover


def typed(spec: SettingSpec, value: Any) -> Any:
    """A stored value as code uses it: ``Decimal`` for money, ``int``, ``bool``, ``str``, ``list[Decimal]``."""
    if value is None:
        return None
    if spec.type in ("usd", "decimal"):
        return Decimal(str(value))
    if spec.type == "int":
        return int(value)
    if spec.type == "usd_list":
        return [Decimal(str(v)) for v in value]
    return value


@dataclass(frozen=True)
class Resolved:
    key: str
    value: Any
    source: str                     # company | partner | plan | platform | default
    scope_id: Optional[UUID] = None


async def _partner_of(db: Any, company_id: UUID) -> Optional[UUID]:
    """The tenant's partner: its current assignment (Phase 15 T8-2), else a partner parent."""
    from sqlalchemy import select

    from src.auth.models import Company
    from src.partners.models import PartnerAssignment

    assigned = (await db.execute(select(PartnerAssignment.partner_id).where(
        PartnerAssignment.tenant_id == company_id, PartnerAssignment.until.is_(None)))).scalar_one_or_none()
    if assigned is not None:
        return assigned
    parent = (await db.execute(select(Company.parent_id).where(Company.id == company_id))).scalar_one_or_none()
    if parent is None:
        return None
    kind = (await db.execute(select(Company.type).where(Company.id == parent))).scalar_one_or_none()
    return parent if kind == "PARTNER" else None


async def resolve(db: Any, key: str, company_id: Optional[UUID] = None) -> Resolved:
    """The value of ``key`` for ``company_id`` (the platform's when None), and where it came from."""
    from src.common.settings_store import read_values

    spec = spec_for(key)
    candidates: list[tuple[str, Optional[UUID]]] = []
    if company_id is not None:
        if COMPANY in spec.scopes:
            candidates.append((COMPANY, company_id))
        if PARTNER in spec.scopes:
            partner = await _partner_of(db, company_id)
            if partner is not None:
                candidates.append((PARTNER, partner))
        if PLAN in spec.scopes:
            from src.billing.plans import plan_id_of
            plan_id = await plan_id_of(db, company_id)
            if plan_id is not None:
                candidates.append((PLAN, plan_id))
    candidates.append((PLATFORM, None))
    values = await read_values(db, key, candidates)
    for scope, scope_id in candidates:
        if (scope, scope_id) in values:
            return Resolved(key, typed(spec, values[(scope, scope_id)]), scope, scope_id)
    return Resolved(key, typed(spec, spec.default), "default")


async def value(db: Any, key: str, company_id: Optional[UUID] = None) -> Any:
    return (await resolve(db, key, company_id)).value


async def explain(db: Any, company_id: Optional[UUID] = None) -> list[dict]:
    """Every setting's value for a company (the platform when None) and its source."""
    out = []
    for key, spec in CATALOGUE.items():
        resolved = await resolve(db, key, company_id)
        out.append({"key": key, "type": spec.type, "group": spec.group, "unit": spec.unit, "help": spec.help,
                    "scopes": list(spec.scopes), "choices": list(spec.choices),
                    "minimum": str(spec.minimum) if spec.minimum is not None else None,
                    "maximum": str(spec.maximum) if spec.maximum is not None else None,
                    "nullable": spec.nullable,
                    "default": _jsonable(spec.default), "value": _jsonable(resolved.value), "source": resolved.source})
    return out


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


async def min_balance(db: Any, company_id: Optional[UUID], entity_type: str) -> Decimal:
    """Free credit (USD, billed) a run of this level needs to start (R-A2, T5-2)."""
    level = (entity_type or "").upper()
    key = f"admission.min_balance.{level}" if level in LEVELS else "admission.min_balance.default"
    return await value(db, key, company_id)

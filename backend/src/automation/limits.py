"""Automation limits a business sets on screen (decision D47, functional spec §3.5).

Every limit is optional: **none applies unless someone sets it**. Platform
staff may set platform-wide defaults; a business's own value wins. Values are
stored as a JSON object per scope in the control table ``automation_limits``
(one platform row, one row per business):

* a key that is absent inherits (business ← platform ← no limit / default behaviour);
* a key set to ``null`` means "no limit" explicitly, even if the platform has one;
* a number or choice is the limit.

The wallet check before every automated run (D06) is not one of these: it
always applies.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, Optional, Tuple

CACHE_SECONDS = 60


@dataclass(frozen=True)
class Limit:
    key: str
    label: str
    help: str
    kind: str                         # "count" (a whole number ≥ 1) | "choice"
    choices: Tuple[str, ...] = ()
    unit: str = ""
    default: Optional[str] = None     # a choice's behaviour when nothing is set


CATALOGUE: Tuple[Limit, ...] = (
    Limit("max_chain_depth", "Loop limit",
          "A chain of agent-caused events stops after this many steps, with a visible \"loop stopped\" item.",
          "count", unit="steps"),
    Limit("max_active_runs", "Runs at the same time",
          "Automated runs this business may have going at once; more wait in line.", "count", unit="runs"),
    Limit("trigger_rate_per_hour", "Runs per trigger per hour",
          "How many runs one trigger may start in an hour (a trigger may set its own).", "count", unit="runs/hour"),
    Limit("overlap", "If the previous run is still going",
          "What a trigger does when its last run has not finished (a trigger may set its own).",
          "choice", choices=("allow", "queue", "skip"), default="allow"),
    Limit("catch_up", "Missed times",
          "What happens to schedule times missed while paused or down (a trigger may set its own).",
          "choice", choices=("all", "once", "skip"), default="all"),
    Limit("catch_up_max", "Most missed times to run",
          "With \"all\", at most this many missed times run after a pause or outage.", "count", unit="runs"),
    Limit("agent_max_schedules", "Agent-made schedules",
          "Active schedules agents may have created for this business.", "count", unit="schedules"),
    Limit("agent_schedules_per_run", "Schedules per agent run",
          "How many schedules one agent run may create.", "count", unit="schedules"),
    Limit("agent_min_repeat_minutes", "Shortest repeat for agent schedules",
          "A repeating schedule an agent creates may not fire more often than this.", "count", unit="minutes"),
    Limit("agent_events_per_run", "Signals per agent run",
          "How many custom events one agent run may send.", "count", unit="events"),
    Limit("max_wait_days", "Longest wait",
          "How long a run may wait for an event before it times out.", "count", unit="days"),
    Limit("event_retention_days", "Event history kept",
          "Events older than this are deleted; with no limit they are kept.", "count", unit="days"),
    Limit("ads_monthly_ceiling", "Google Ads monthly ceiling",
          "The most the ad account's campaigns may plan to spend in a month (daily budgets × 30.4, in the "
          "account's currency) when an agent creates one; with none set, agents create no campaigns.",
          "count", unit="per month"),
)
BY_KEY: Dict[str, Limit] = {limit.key: limit for limit in CATALOGUE}
MAX_COUNT = 1_000_000


class LimitsError(ValueError):
    """Values that cannot be stored; the message names the key."""


def validate(values: Any) -> Dict[str, Any]:
    """A scope's stored values: known keys only, ``null`` or a valid value each."""
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise LimitsError("limits must be an object of limit name to value")
    clean: Dict[str, Any] = {}
    for key, value in values.items():
        limit = BY_KEY.get(key)
        if limit is None:
            raise LimitsError(f"unknown limit {key!r}; known: {', '.join(BY_KEY)}")
        if value is None:
            clean[key] = None
        elif limit.kind == "count":
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_COUNT:
                raise LimitsError(f"{key}: a whole number from 1 to {MAX_COUNT}, or null for no limit")
            clean[key] = value
        else:
            if value not in limit.choices:
                raise LimitsError(f"{key}: one of {', '.join(limit.choices)}, or null for the default")
            clean[key] = value
    return clean


@dataclass(frozen=True)
class AutomationLimits:
    """The limits in force for one business (``None`` = no limit)."""

    max_chain_depth: Optional[int] = None
    max_active_runs: Optional[int] = None
    trigger_rate_per_hour: Optional[int] = None
    overlap: str = "allow"
    catch_up: str = "all"
    catch_up_max: Optional[int] = None
    agent_max_schedules: Optional[int] = None
    agent_schedules_per_run: Optional[int] = None
    agent_min_repeat_minutes: Optional[int] = None
    agent_events_per_run: Optional[int] = None
    max_wait_days: Optional[int] = None
    event_retention_days: Optional[int] = None
    ads_monthly_ceiling: Optional[int] = None      # GADS-E3: agents' Google Ads campaigns

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


NO_LIMITS = AutomationLimits()


def resolve(platform: Optional[Dict[str, Any]], business: Optional[Dict[str, Any]]) -> AutomationLimits:
    """Business over platform over none; a ``null`` choice means its default behaviour."""
    merged: Dict[str, Any] = {}
    for scope in (platform or {}, business or {}):
        merged.update(scope)
    values: Dict[str, Any] = {}
    for field in fields(AutomationLimits):
        if field.name not in merged:
            continue
        value = merged[field.name]
        if value is None and BY_KEY[field.name].kind == "choice":
            continue  # the choice's default behaviour
        values[field.name] = value
    return AutomationLimits(**values)


# ── Reading them (cached a minute per process, like the time zone) ─────────

_cache: Dict[str, Tuple[AutomationLimits, float]] = {}


async def stored_values(db: Any, company_id: Any) -> Dict[str, Any]:
    """One scope's stored values (``company_id`` None = the platform row)."""
    from sqlalchemy import select

    from src.automation.models import AutomationLimitsRow

    column = AutomationLimitsRow.company_id
    condition = column.is_(None) if company_id is None else column == company_id
    row = (await db.execute(select(AutomationLimitsRow.limits).where(condition))).scalar()
    return dict(row or {})


async def limits_for(company_id: Any, db: Any = None) -> AutomationLimits:
    """What applies to the business now."""
    key = str(company_id)
    hit = _cache.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]

    async def read(session: Any) -> AutomationLimits:
        return resolve(await stored_values(session, None), await stored_values(session, company_id))

    if db is not None:
        limits = await read(db)
    else:
        from src.common.tenancy.session import control_session

        async with control_session() as session:
            limits = await read(session)
    _cache[key] = (limits, time.monotonic() + CACHE_SECONDS)
    return limits


def forget(company_id: Any = None) -> None:
    """Drop cached limits (one business, or all after a platform change)."""
    if company_id is None:
        _cache.clear()
    else:
        _cache.pop(str(company_id), None)


# ── Whether automation runs (the kill switch) ──────────────────────────────

_state_cache: Dict[str, Tuple[str, float]] = {}
STATE_CACHE_SECONDS = 15  # a pause takes hold within this long on every worker


async def automation_state_for(company_id: Any, db: Any = None) -> str:
    """``running`` or ``paused``: paused when the business paused its automation,
    or when platform staff paused everything (the platform row, an emergency stop)."""
    key = str(company_id)
    hit = _state_cache.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    from sqlalchemy import or_, select

    from src.automation.models import AutomationLimitsRow

    async def read(session: Any) -> str:
        column = AutomationLimitsRow.company_id
        rows = (await session.execute(
            select(AutomationLimitsRow.automation_state).where(or_(column.is_(None), column == company_id))
        )).scalars().all()
        return "paused" if "paused" in rows else "running"

    if db is not None:
        state = await read(db)
    else:
        from src.common.tenancy.session import control_session

        async with control_session() as session:
            state = await read(session)
    _state_cache[key] = (state, time.monotonic() + STATE_CACHE_SECONDS)
    return state


def forget_state(company_id: Any = None) -> None:
    if company_id is None:
        _state_cache.clear()
    else:
        _state_cache.pop(str(company_id), None)


async def save(db: Any, company_id: Any, values: Dict[str, Any], updated_by: Any) -> Dict[str, Any]:
    """Replace a scope's stored values (validated); returns them."""
    from datetime import datetime

    from sqlalchemy import select

    from src.automation.models import AutomationLimitsRow

    clean = validate(values)
    column = AutomationLimitsRow.company_id
    condition = column.is_(None) if company_id is None else column == company_id
    row = (await db.execute(select(AutomationLimitsRow).where(condition))).scalar_one_or_none()
    if row is None:
        row = AutomationLimitsRow(company_id=company_id)
        db.add(row)
    row.limits = clean
    row.updated_by = updated_by
    row.updated_at = datetime.utcnow()
    await db.commit()
    forget(None if company_id is None else company_id)
    return clean

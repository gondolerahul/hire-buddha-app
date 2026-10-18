"""Triggers (tech spec §7.1, §7.3, §7.5; functional spec §3.1–§3.3).

A trigger is a rule: *when* (a schedule, a one-time timer, an event type and
filter, a data change, a condition) → *run* this agent with this input →
under these rules. Saving a trigger never runs anything. A schedule or timer
keeps one row in the control plane's ``time_index`` with its next due time;
the tenant row is the truth and the index follows it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from src.automation import events as events_mod
from src.automation import filters, schedules, templates
from src.automation.models import (
    CATCH_UP_POLICIES,
    OVERLAP_POLICIES,
    TRIGGER_KINDS,
    TimeIndexEntry,
    Trigger,
)

EDITABLE = ("name", "enabled", "entity_id", "entity_version_id", "input_template", "event_type", "filter", "cron",
            "timezone", "run_at", "until_at", "max_firings", "catch_up", "overlap", "max_concurrency",
            "rate_per_hour", "condition", "scope")
TIMED = ("schedule", "timer", "condition")  # fired by the scheduler
EVENT_KINDS = ("event", "data")             # fired by the router


class TriggerError(ValueError):
    """A trigger that cannot be saved; the message says which field and why."""


def _naive_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise TriggerError(f"{value!r} is not an ISO-8601 time") from None
    if value.tzinfo is not None:
        from datetime import timezone

        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def validate(fields: Dict[str, Any], *, now: datetime, new_run_at: bool = True) -> Dict[str, Any]:
    """The fields of a trigger, checked for its kind (raises :class:`TriggerError`).

    ``new_run_at``: the timer's time is being set, so it must be in the future;
    a change to anything else of a timer that already fired is fine.
    """
    data = dict(fields)
    kind = data.get("kind")
    if kind not in TRIGGER_KINDS:
        raise TriggerError(f"kind must be one of {', '.join(TRIGGER_KINDS)}")
    if not str(data.get("name") or "").strip():
        raise TriggerError("name is required")
    if not data.get("entity_id"):
        raise TriggerError("entity_id (the agent to run) is required")
    for key, choices in (("catch_up", CATCH_UP_POLICIES), ("overlap", OVERLAP_POLICIES)):
        if data.get(key) is not None and data[key] not in choices:
            raise TriggerError(f"{key} must be one of {', '.join(choices)}, or null for the business setting")
    for key in ("max_concurrency", "rate_per_hour", "max_firings"):
        value = data.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise TriggerError(f"{key} must be a whole number of at least 1, or null for no limit")
    try:
        data["input_template"] = templates.validate(data.get("input_template") or {})
    except templates.TemplateError as error:
        raise TriggerError(f"input_template: {error}") from None
    for key in ("run_at", "until_at"):
        data[key] = _naive_utc(data.get(key))

    if kind in ("schedule", "condition"):
        try:
            schedules.validate_cron(data.get("cron"))
            if data.get("timezone"):
                schedules.validate_timezone(data["timezone"])
        except schedules.ScheduleError as error:
            raise TriggerError(f"cron: {error}") from None
    if kind == "condition":  # checked on the business's records each time the schedule fires (WS4 4.10)
        from src.automation import conditions

        try:
            data["condition"] = conditions.validate(data.get("condition"))
        except conditions.ConditionError as error:
            raise TriggerError(str(error)) from None
    else:
        data["condition"] = None
    if kind == "timer":
        if data.get("run_at") is None:
            raise TriggerError("a timer needs run_at")
        if new_run_at and data["run_at"] <= now:
            raise TriggerError("run_at is in the past")
    if kind in EVENT_KINDS:
        try:
            pattern = str(data.get("event_type") or "")
            if pattern != "*":
                events_mod.validate_type(pattern[:-2] + ".x" if pattern.endswith(".*") else pattern)
        except events_mod.EventError:
            raise TriggerError("event_type must be an event type like social.comment.created, "
                               "or a prefix like record.order.*") from None
        if pattern == "*" and (kind != "event" or not data.get("filter")):
            raise TriggerError("event_type * (every event) is for event triggers with a filter that says which")
        if kind == "data" and not str(data["event_type"]).startswith("record."):
            raise TriggerError("a data trigger listens to record.<object>.* events")
    try:
        data["filter"] = filters.validate(data.get("filter")) or None
    except filters.FilterError as error:
        raise TriggerError(f"filter: {error}") from None
    if kind in EVENT_KINDS and str(data.get("event_type") or "").startswith("run.") \
            and str(data.get("entity_id")) in _watched_agents(data.get("filter")):
        raise TriggerError("this trigger would start its own agent every time that agent finishes, forever; "
                           "run a different agent")
    return data


def _watched_agents(spec: Any) -> set:
    """The agents a run-finished filter names with ``data.entity_id`` equal to them."""
    if not isinstance(spec, dict):
        return set()
    if spec.get("path") == "data.entity_id" and spec.get("op") == "eq":
        return {str(spec.get("value"))}
    if spec.get("op") == "in" and spec.get("path") == "data.entity_id" and isinstance(spec.get("value"), list):
        return {str(v) for v in spec["value"]}
    if isinstance(spec.get("all"), list):
        return set().union(*(_watched_agents(s) for s in spec["all"])) if spec["all"] else set()
    return set()


def next_fire_at(trigger: Any, *, now: datetime, default_timezone: str) -> Optional[datetime]:
    """When the scheduler should next look at a timed trigger (``None``: never)."""
    if not trigger.enabled or trigger.kind not in TIMED:
        return None
    if trigger.max_firings is not None and trigger.firings >= trigger.max_firings:
        return None
    if trigger.kind == "timer":
        return trigger.run_at if trigger.firings == 0 else None
    moment = schedules.next_fire_time(trigger.cron, trigger.timezone or default_timezone, now)
    if trigger.until_at is not None and moment > trigger.until_at:
        return None
    return moment


async def sync_time_index(control_db: Any, company_id: Any, trigger: Any) -> None:
    """Make the control plane's time index say what the trigger says (no commit)."""
    key = {"company_id": company_id, "ref_kind": "trigger", "ref_id": trigger.id}
    if trigger.next_fire_at is None:
        await control_db.execute(delete(TimeIndexEntry).filter_by(**key))
        return
    await control_db.execute(
        insert(TimeIndexEntry).values(**key, due_at=trigger.next_fire_at)
        .on_conflict_do_update(index_elements=["company_id", "ref_kind", "ref_id"],
                               set_={"due_at": trigger.next_fire_at, "lease_owner": None, "lease_until": None})
    )


@dataclass
class Actor:
    """Who creates or changes a trigger (functional spec §3.3: agent-made ones are marked)."""

    kind: str = "user"                 # user | agent | system
    id: Optional[uuid.UUID] = None     # the user or the agent (entity)
    run_id: Optional[uuid.UUID] = None


async def _check_entity(db: Any, company_id: Any, entity_id: Any) -> None:
    from src.ai.orm import HierarchicalEntity

    entity = (await db.execute(select(HierarchicalEntity).where(
        HierarchicalEntity.id == entity_id, HierarchicalEntity.company_id == company_id,
        HierarchicalEntity.status != "DELETED"))).scalar_one_or_none()
    if entity is None:
        raise TriggerError("entity_id is not an agent of this business")


async def create(db: Any, control_db: Any, company_id: Any, fields: Dict[str, Any], actor: Actor, *,
                 now: Optional[datetime] = None) -> Trigger:
    """Save a new trigger (nothing runs); returns it with its next fire time."""
    from src.common.timezones import company_timezone_name

    now = now or datetime.utcnow()
    data = validate(fields, now=now)
    await _check_entity(db, company_id, data["entity_id"])
    trigger = Trigger(id=uuid.uuid4(), company_id=company_id, kind=data["kind"],
                      created_by_kind=actor.kind, created_by_id=actor.id, created_by_run_id=actor.run_id,
                      **{key: data.get(key) for key in EDITABLE if key in data})
    if trigger.enabled is None:
        trigger.enabled = True
    trigger.firings = 0
    trigger.next_fire_at = next_fire_at(trigger, now=now,
                                        default_timezone=await company_timezone_name(company_id, control_db))
    db.add(trigger)
    await db.flush()
    await sync_time_index(control_db, company_id, trigger)
    return trigger


async def update(db: Any, control_db: Any, company_id: Any, trigger: Trigger, changes: Dict[str, Any], *,
                 now: Optional[datetime] = None) -> Trigger:
    """Change a trigger's editable fields; its kind and author stay."""
    from src.common.timezones import company_timezone_name

    now = now or datetime.utcnow()
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise TriggerError(f"cannot change {', '.join(sorted(unknown))}")
    current = {key: getattr(trigger, key) for key in EDITABLE}
    current.update(changes)
    current["kind"] = trigger.kind
    data = validate(current, now=now, new_run_at="run_at" in changes)
    if "entity_id" in changes:
        await _check_entity(db, company_id, data["entity_id"])
    for key in changes:
        setattr(trigger, key, data.get(key))
    if "enabled" in changes and data.get("enabled"):
        trigger.paused_reason = None
    trigger.version = (trigger.version or 1) + 1
    trigger.next_fire_at = next_fire_at(trigger, now=now,
                                        default_timezone=await company_timezone_name(company_id, control_db))
    await db.flush()
    await sync_time_index(control_db, company_id, trigger)
    return trigger


async def remove(db: Any, control_db: Any, company_id: Any, trigger: Trigger) -> None:
    trigger.next_fire_at = None
    await sync_time_index(control_db, company_id, trigger)
    await db.delete(trigger)
    await db.flush()


async def get(db: Any, company_id: Any, trigger_id: Any) -> Optional[Trigger]:
    return (await db.execute(select(Trigger).where(Trigger.id == trigger_id,
                                                   Trigger.company_id == company_id))).scalar_one_or_none()


async def listening(db: Any, company_id: Any, event_type: str) -> List[Trigger]:
    """Enabled event and data triggers whose ``event_type`` matches (exact or ``prefix.*``)."""
    rows = (await db.execute(select(Trigger).where(
        Trigger.company_id == company_id, Trigger.enabled.is_(True), Trigger.kind.in_(EVENT_KINDS),
        Trigger.event_type.isnot(None)).order_by(Trigger.created_at))).scalars().all()
    return [t for t in rows if events_mod.type_matches(t.event_type, event_type)]

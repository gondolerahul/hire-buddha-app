"""What an agent may do with automation on its own (tech spec §7.10;
functional spec §3.3): the logic behind the ``schedule_agent``,
``cancel_schedule``, ``list_schedules`` and ``emit_event`` tools.

* **Schedule work** — a timer (``{"at": …}`` / ``{"in": "3d"}``) or a
  repeating schedule (``{"cron": …}``) that runs an agent with an input. The
  agent may schedule itself, the agents of its own process, and the agents
  the owner listed on its Automation tab (``capabilities.automation.can_schedule``).
  The trigger is marked as made by the agent and its run, so the owner sees
  and can stop it. Saving runs nothing.
* **Cancel** — only schedules the agent (or its process) made; cancelling
  turns the trigger off and keeps its history.
* **Send a signal** — a ``custom.*`` event, one step deeper in the chain of
  the run's own triggering event, so the loop limit sees chains of agents.

How much — active agent-made schedules, schedules per run, the shortest
repeat, signals per run — is the business's automation limits, none unless
set (decision D47). Using a tool at all is a tool grant on the agent.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, or_, select

from src.automation import events as events_mod
from src.automation import guards, schedules, store, templates
from src.automation import triggers as triggers_mod
from src.automation.limits import limits_for
from src.automation.models import Event, Trigger

MAX_PARENT_HOPS = 20
RUNNABLE = ("ACTIVE", "DEPRECATED")
SCOPES = ("mine", "process", "runs_me")


class AgentActionError(ValueError):
    """A refused call; the message is what the agent reads."""


@dataclass(frozen=True)
class RunOrigin:
    """Where a run sits in a chain of automation: its top-level run's trigger and event."""

    run_id: UUID
    top_run_id: UUID
    event_id: Optional[UUID]
    correlation_id: UUID
    chain_depth: int


def _status(entity: Any) -> str:
    return str(getattr(entity.status, "value", entity.status) or "").upper()


def _automation(entity: Any) -> Dict[str, Any]:
    caps = entity.capabilities if isinstance(entity.capabilities, dict) else {}
    automation = caps.get("automation")
    return automation if isinstance(automation, dict) else {}


async def run_origin(db: Any, company_id: Any, run_id: Any) -> RunOrigin:
    """The run's place in its chain: a child run belongs to its top-level run's."""
    from src.ai.orm import ExecutionRun

    run = await db.get(ExecutionRun, UUID(str(run_id)))
    if run is None or run.company_id != company_id:
        raise AgentActionError("this tool runs only inside a run of this business")
    top = run
    for _ in range(MAX_PARENT_HOPS):
        if not top.parent_run_id:
            break
        parent = await db.get(ExecutionRun, top.parent_run_id)
        if parent is None:
            break
        top = parent
    return RunOrigin(run_id=run.id, top_run_id=top.id, event_id=top.event_id,
                     correlation_id=top.correlation_id or top.event_id or top.id,
                     chain_depth=top.chain_depth or 0)


async def _entity(db: Any, company_id: Any, entity_id: Any) -> Any:
    from src.ai.orm import HierarchicalEntity

    entity = await db.get(HierarchicalEntity, UUID(str(entity_id)))
    if entity is None or entity.company_id != company_id or _status(entity) == "DELETED":
        return None
    return entity


async def find_agent(db: Any, company_id: Any, ref: str) -> Any:
    """An agent of the business by id or by name (exact, ignoring case)."""
    from src.ai.orm import HierarchicalEntity

    ref = str(ref or "").strip()
    if not ref:
        raise AgentActionError("name the agent to run (its id or name)")
    try:
        entity = await _entity(db, company_id, UUID(ref))
        if entity is not None:
            return entity
    except ValueError:
        pass
    rows = (await db.execute(select(HierarchicalEntity).where(
        HierarchicalEntity.company_id == company_id, HierarchicalEntity.status != "DELETED",
        HierarchicalEntity.is_template.isnot(True),
        or_(func.lower(HierarchicalEntity.name) == ref.lower(),
            func.lower(HierarchicalEntity.display_name) == ref.lower())))).scalars().all()
    if not rows:
        raise AgentActionError(f"no agent called {ref!r} in this business")
    if len(rows) > 1:
        raise AgentActionError(f"{len(rows)} agents are called {ref!r}; use the id of the one you mean")
    return rows[0]


async def _process_root(db: Any, company_id: Any, entity: Any) -> Optional[UUID]:
    """The top of the entity's hierarchy, when that is a process (else None)."""
    current = entity
    for _ in range(MAX_PARENT_HOPS):
        if not current.parent_id:
            break
        parent = await _entity(db, company_id, current.parent_id)
        if parent is None:
            break
        current = parent
    kind = str(getattr(current.type, "value", current.type) or "").upper()
    return current.id if kind == "PROCESS" else None


async def _same_process(db: Any, company_id: Any, one: Any, other: Any) -> bool:
    root = await _process_root(db, company_id, one)
    return root is not None and root == await _process_root(db, company_id, other)


async def may_schedule(db: Any, company_id: Any, caller: Any, target: Any) -> Optional[str]:
    """Why ``caller`` may not schedule ``target`` (None: it may)."""
    if target.id == caller.id or str(target.id) in {str(x) for x in _automation(caller).get("can_schedule") or []}:
        return None
    if await _same_process(db, company_id, caller, target):
        return None
    return (f"you may schedule yourself, the agents of your own process, or the agents the owner listed "
            f"on your Automation tab; {target.name!r} is none of these")


def _local_time(value: Any, zone: str) -> datetime:
    """An ISO time; without an offset it is the business's local time."""
    from zoneinfo import ZoneInfo

    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise AgentActionError(f"{value!r} is not an ISO-8601 time") from None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=ZoneInfo(zone))


def _input(value: Any) -> Dict[str, Any]:
    """The scheduled run's input, kept as written (not a template)."""
    if value is None:
        value = {}
    if isinstance(value, str):
        value = {"input": value}
    if not isinstance(value, dict):
        raise AgentActionError("input must be text or an object")
    return templates.literal(value)


async def schedule(db: Any, control_db: Any, company_id: Any, *, caller_id: Any, run_id: Any, agent: Optional[str],
                   when: Any, input: Any = None, name: Optional[str] = None, until: Optional[str] = None,
                   max_runs: Optional[int] = None, now: Optional[datetime] = None) -> Trigger:
    """Create a timer or schedule made by the agent (saving runs nothing)."""
    from src.common.timezones import company_timezone_name

    now = now or datetime.utcnow()
    caller = await _entity(db, company_id, caller_id)
    if caller is None:
        raise AgentActionError("this tool runs only for an agent of this business")
    target = await find_agent(db, company_id, agent) if agent else caller
    refused = await may_schedule(db, company_id, caller, target)
    if refused:
        raise AgentActionError(refused)
    if _status(target) not in RUNNABLE:
        raise AgentActionError(f"{target.name!r} is {_status(target)}; only an active agent runs automatically")
    if _automation(target).get("triggerable") is False:
        raise AgentActionError(f"{target.name!r} does not allow automatic runs")

    limits = await limits_for(company_id, control_db)
    zone = await company_timezone_name(company_id, control_db)
    active = (await db.execute(select(func.count()).select_from(Trigger).where(
        Trigger.company_id == company_id, Trigger.created_by_kind == "agent", Trigger.enabled.is_(True),
        Trigger.next_fire_at.isnot(None)))).scalar() or 0
    this_run = (await db.execute(select(func.count()).select_from(Trigger).where(
        Trigger.company_id == company_id, Trigger.created_by_run_id == UUID(str(run_id))))).scalar() or 0
    try:
        guards.agent_schedule(active, this_run, limits)
        parsed = schedules.parse_when(when, now=now, default_timezone=zone,
                                      min_interval=guards.agent_min_repeat(limits))
    except (guards.AgentLimitExceeded, schedules.ScheduleError) as error:
        raise AgentActionError(str(error)) from None
    if until is not None and parsed.kind != "schedule":
        raise AgentActionError("until applies to a repeating schedule ({\"cron\": …}) only")
    until_at = _local_time(until, zone) if until is not None else None

    fields = {
        "name": (name or f"{target.name} — scheduled by {caller.name}")[:200],
        "kind": parsed.kind, "entity_id": target.id, "input_template": _input(input),
        "run_at": parsed.run_at, "cron": parsed.cron, "timezone": parsed.timezone,
        "until_at": until_at, "max_firings": max_runs,
    }
    try:
        return await triggers_mod.create(db, control_db, company_id, fields,
                                         triggers_mod.Actor("agent", caller.id, UUID(str(run_id))), now=now)
    except triggers_mod.TriggerError as error:
        raise AgentActionError(str(error)) from None


async def _may_manage(db: Any, company_id: Any, caller: Any, trigger: Trigger) -> bool:
    if trigger.created_by_kind != "agent" or trigger.created_by_id is None:
        return False
    if trigger.created_by_id == caller.id:
        return True
    maker = await _entity(db, company_id, trigger.created_by_id)
    return maker is not None and await _same_process(db, company_id, caller, maker)


async def cancel(db: Any, control_db: Any, company_id: Any, *, caller_id: Any, trigger_id: Any,
                 now: Optional[datetime] = None) -> Trigger:
    """Turn off a schedule the agent (or its process) made; its history stays."""
    caller = await _entity(db, company_id, caller_id)
    if caller is None:
        raise AgentActionError("this tool runs only for an agent of this business")
    try:
        trigger = await triggers_mod.get(db, company_id, UUID(str(trigger_id)))
    except ValueError:
        trigger = None
    if trigger is None:
        raise AgentActionError(f"no schedule {trigger_id!r} in this business")
    if not await _may_manage(db, company_id, caller, trigger):
        raise AgentActionError("you may cancel only schedules you or your process made")
    if trigger.enabled:
        await triggers_mod.update(db, control_db, company_id, trigger, {"enabled": False}, now=now)
        trigger.paused_reason = f"cancelled by agent {caller.name}"
    return trigger


async def list_for(db: Any, company_id: Any, *, caller_id: Any, scope: str = "mine") -> List[Trigger]:
    """Schedules the agent may see: ones it made, ones its process made, or ones that run it."""
    if scope not in SCOPES:
        raise AgentActionError(f"scope must be one of {', '.join(SCOPES)}")
    caller = await _entity(db, company_id, caller_id)
    if caller is None:
        raise AgentActionError("this tool runs only for an agent of this business")
    query = select(Trigger).where(Trigger.company_id == company_id).order_by(Trigger.created_at.desc()).limit(200)
    if scope == "runs_me":
        return list((await db.execute(query.where(Trigger.entity_id == caller.id))).scalars().all())
    made = list((await db.execute(query.where(Trigger.created_by_kind == "agent"))).scalars().all())
    if scope == "mine":
        return [t for t in made if t.created_by_id == caller.id]
    return [t for t in made if await _may_manage(db, company_id, caller, t)]


async def emit(db: Any, control_db: Any, company_id: Any, *, run_id: Any, event_type: str,
               data: Optional[Dict[str, Any]] = None, subject: Optional[str] = None) -> Event:
    """Store a ``custom.*`` signal one step deeper in the run's chain (committed; then nudge)."""
    try:
        events_mod.validate_custom_type(event_type)
    except events_mod.EventError as error:
        raise AgentActionError(str(error)) from None
    data = data or {}
    if not isinstance(data, dict):
        raise AgentActionError("data must be an object")
    size = len(json.dumps(data, default=str))
    if size > events_mod.MAX_INLINE_DATA_BYTES:
        raise AgentActionError(f"data is {size} bytes; a signal carries at most {events_mod.MAX_INLINE_DATA_BYTES}")

    source = f"run:{run_id}"
    emitted = (await db.execute(select(func.count()).select_from(Event).where(
        Event.company_id == company_id, Event.source == source))).scalar() or 0
    try:
        guards.agent_emit(emitted, await limits_for(company_id, control_db))
    except guards.AgentLimitExceeded as error:
        raise AgentActionError(str(error)) from None

    origin = await run_origin(db, company_id, run_id)
    row, _ = await store.record(db, company_id, events_mod.Envelope(
        type=event_type, source=source, trust="internal", subject=(subject or None),
        dedupe_key=f"signal:{run_id}:{uuid.uuid4().hex}", data=data,
        causation_id=origin.event_id, correlation_id=origin.correlation_id, chain_depth=origin.chain_depth + 1))
    return row


def describe(trigger: Trigger) -> Dict[str, Any]:
    """A trigger as an agent reads it."""
    return {
        "schedule_id": str(trigger.id), "name": trigger.name, "kind": trigger.kind,
        "agent_id": str(trigger.entity_id), "enabled": trigger.enabled,
        "cron": trigger.cron, "timezone": trigger.timezone,
        "run_at": trigger.run_at.isoformat() + "Z" if trigger.run_at else None,
        "next_run_at": trigger.next_fire_at.isoformat() + "Z" if trigger.next_fire_at else None,
        "runs_so_far": trigger.firings, "max_runs": trigger.max_firings,
        "made_by": trigger.created_by_kind, "status_note": trigger.paused_reason,
    }

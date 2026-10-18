"""The automation control room's API (tech spec §7.12; functional spec §3.4).

``/api/v1/automation/*`` for one business (the caller's, or the company in
``X-Company-Id`` when the caller may see it):

* triggers — list, create, read, change, delete; a preview of the next fire
  times before saving; their firings (every decision, with its reason); "run
  now" (an ordinary run of the trigger, through the same rules);
* events — the log (by type, status, time), one event with its decisions and
  runs, replay of a dead or held event;
* waits — runs waiting for an event, and cancelling a wait (the run goes on
  without the event);
* scopes — pause and resume every trigger of one department or process;
* health — dead and held events, missed schedules, triggers that keep failing.

Saving a trigger never runs anything. Everyone in the business may look;
owners and admins change triggers; anyone running the business may run one
now, replay an event or pause a scope. Each endpoint carries the capability
annotations Pragya reads (§20, PR-2).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.automation import events as events_mod
from src.automation import guards, router as router_mod, schedules, store, triggers as triggers_mod
from src.automation.api import EDIT_ROLES, PAUSE_ROLES, capability
from src.automation.limits import automation_state_for
from src.automation.models import Event, Trigger, TriggerFiring, Wait
from src.common.tenancy.session import acting_company_id, get_acting_tenant_db, get_control_db

control_router = APIRouter(prefix="/api/v1/automation", tags=["Automation"])

OPERATE_ROLES = PAUSE_ROLES  # run now, replay, pause a scope
PROBLEM_OUTCOMES = (guards.BLOCKED_BUDGET, guards.BLOCKED_POLICY, guards.FAILED)


# ── Shapes ─────────────────────────────────────────────────────────────────

class TriggerFields(BaseModel):
    """What a trigger editor sends; on a change, only the fields it names."""

    name: Optional[str] = Field(None, max_length=200)
    enabled: Optional[bool] = None
    entity_id: Optional[UUID] = Field(None, description="The agent (or process) to run")
    entity_version_id: Optional[UUID] = Field(None, description="Pin a version; null runs the agent as it is now")
    input_template: Optional[Dict[str, Any]] = Field(
        None, description="The run's input; text may use {{ event.data.x }} and {{ trigger.name }}")
    event_type: Optional[str] = Field(None, description="event and data triggers: a type or a prefix like record.order.*")
    filter: Optional[Dict[str, Any]] = Field(None, description="event and data triggers: which events (src/automation/filters.py)")
    cron: Optional[str] = Field(None, description="schedule: five-field cron in the trigger's time zone")
    timezone: Optional[str] = Field(None, description="IANA zone; null uses the business time zone")
    run_at: Optional[datetime] = Field(None, description="timer: when it fires once")
    until_at: Optional[datetime] = Field(None, description="schedule: no firing after this")
    max_firings: Optional[int] = Field(None, ge=1, description="Stop after this many runs; null for no limit")
    catch_up: Optional[str] = Field(None, description="skip | once | all; null uses the business setting")
    overlap: Optional[str] = Field(None, description="skip | queue | allow; null uses the business setting")
    max_concurrency: Optional[int] = Field(None, ge=1)
    rate_per_hour: Optional[int] = Field(None, ge=1, description="null uses the business setting")
    scope: Optional[str] = Field(None, max_length=100, description="A department or process label")


class TriggerCreate(TriggerFields):
    name: str = Field(..., max_length=200)
    kind: str = Field(..., description="schedule | timer | event | data | manual")
    entity_id: UUID


class TriggerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    kind: str
    enabled: bool
    status: str = Field("active", description="active | off | finished | paused (automation paused)")
    entity_id: UUID
    entity_version_id: Optional[UUID] = None
    input_template: Dict[str, Any] = {}
    event_type: Optional[str] = None
    filter: Optional[Dict[str, Any]] = None
    cron: Optional[str] = None
    timezone: Optional[str] = None
    run_at: Optional[datetime] = None
    until_at: Optional[datetime] = None
    max_firings: Optional[int] = None
    catch_up: Optional[str] = None
    overlap: Optional[str] = None
    max_concurrency: Optional[int] = None
    rate_per_hour: Optional[int] = None
    scope: Optional[str] = None
    created_by_kind: str
    created_by_id: Optional[UUID] = None
    created_by_run_id: Optional[UUID] = None
    next_fire_at: Optional[datetime] = None
    last_fired_at: Optional[datetime] = None
    firings: int = 0
    paused_reason: Optional[str] = None
    version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PreviewRequest(BaseModel):
    kind: str
    cron: Optional[str] = None
    timezone: Optional[str] = None
    run_at: Optional[datetime] = None
    until_at: Optional[datetime] = None
    count: int = Field(10, ge=1, le=50)


class PreviewOut(BaseModel):
    timezone: str
    times: List[datetime]


class FilterTestRequest(BaseModel):
    event_type: str = Field(..., description="A type or a prefix like record.order.*")
    filter: Optional[Dict[str, Any]] = None
    sample: int = Field(50, ge=1, le=200, description="How many recent events of the type to test")


class FilterTestOut(BaseModel):
    checked: int
    matched: int
    matches: List["EventOut"] = []


class FiringOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trigger_id: UUID
    event_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    decided_at: datetime
    outcome: str
    reason: Optional[str] = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    source: str
    subject: Optional[str] = None
    time: datetime
    received_at: datetime
    trust: str
    chain_depth: int
    correlation_id: Optional[UUID] = None
    causation_id: Optional[UUID] = None
    status: str
    attempts: int = 0
    last_error: Optional[str] = None
    routed_at: Optional[datetime] = None


class RunRef(BaseModel):
    id: UUID
    status: str
    entity_id: UUID
    trigger_id: Optional[UUID] = None
    created_at: Optional[datetime] = None


class EventDetail(EventOut):
    data: Dict[str, Any] = {}
    data_ref: Optional[str] = None
    firings: List[FiringOut] = []
    runs: List[RunRef] = []


class FailingTrigger(BaseModel):
    trigger_id: UUID
    name: str
    problems: int
    last_outcome: str
    last_reason: Optional[str] = None


class UpcomingRun(BaseModel):
    trigger_id: UUID
    name: str
    kind: str
    next_fire_at: datetime
    created_by_kind: str


class HealthOut(BaseModel):
    automation_state: str
    started_24h: int = 0
    triggers_enabled: int
    triggers_total: int
    dead_events: int
    parked_events: int
    oldest_parked_at: Optional[datetime] = None
    queued_firings: int
    waiting_runs: int = 0
    missed_schedules_24h: int
    failing_triggers: List[FailingTrigger] = []
    upcoming: List[UpcomingRun] = []


class WaitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    event_type: Optional[str] = None
    match: Optional[Dict[str, Any]] = None
    deadline_at: Optional[datetime] = None
    status: str
    created_at: Optional[datetime] = None
    entity_id: Optional[UUID] = None
    entity_name: Optional[str] = None


class ScopeResult(BaseModel):
    scope: str
    changed: int


# ── Helpers ────────────────────────────────────────────────────────────────

def _require(user: User, roles: set, what: str) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail=f"Not authorized to {what}")


def _status(trigger: Trigger, automation_state: str) -> str:
    if not trigger.enabled:
        return "finished" if (trigger.paused_reason or "").startswith("finished") else "off"
    if trigger.kind in triggers_mod.TIMED and trigger.next_fire_at is None:
        return "finished"  # a timer that fired, a schedule past its end date or run cap
    return "paused" if automation_state != "running" else "active"


def _out(trigger: Trigger, automation_state: str) -> TriggerOut:
    out = TriggerOut.model_validate(trigger)
    out.status = _status(trigger, automation_state)
    return out


async def _trigger_or_404(db: AsyncSession, company_id: UUID, trigger_id: UUID) -> Trigger:
    trigger = await triggers_mod.get(db, company_id, trigger_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail="Trigger not found")
    return trigger


async def _event_or_404(db: AsyncSession, company_id: UUID, event_id: UUID) -> Event:
    event = await db.get(Event, event_id)
    if event is None or event.company_id != company_id:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


async def _commit(db: AsyncSession, control_db: AsyncSession) -> None:
    await db.commit()
    if control_db is not db:  # split mode: the time index is in the control database
        await control_db.commit()


# ── Triggers ───────────────────────────────────────────────────────────────

@control_router.get("/triggers", response_model=List[TriggerOut],
                    openapi_extra=capability("The business's triggers: schedules, timers and event rules, "
                                             "with their next and last firing", "read", "automation.read"))
async def list_triggers(request: Request, kind: Optional[str] = None, entity_id: Optional[UUID] = None,
                        scope: Optional[str] = None, created_by_kind: Optional[str] = None,
                        user: User = Depends(get_current_user), control_db: AsyncSession = Depends(get_control_db),
                        db: AsyncSession = Depends(get_acting_tenant_db)) -> List[TriggerOut]:
    company_id = await acting_company_id(request, user, control_db)
    query = select(Trigger).where(Trigger.company_id == company_id)
    for column, value in ((Trigger.kind, kind), (Trigger.entity_id, entity_id), (Trigger.scope, scope),
                          (Trigger.created_by_kind, created_by_kind)):
        if value is not None:
            query = query.where(column == value)
    rows = (await db.execute(query.order_by(Trigger.created_at.desc()))).scalars().all()
    state = await automation_state_for(company_id, control_db)
    return [_out(t, state) for t in rows]


@control_router.post("/triggers", response_model=TriggerOut, status_code=201,
                     openapi_extra=capability("Create a trigger: when something happens or at a time, run an agent "
                                              "with this input. Saving runs nothing", "write_internal",
                                              "automation.configure", idempotent=False))
async def create_trigger(body: TriggerCreate, request: Request, user: User = Depends(get_current_user),
                         control_db: AsyncSession = Depends(get_control_db),
                         db: AsyncSession = Depends(get_acting_tenant_db)) -> TriggerOut:
    _require(user, EDIT_ROLES, "create triggers")
    company_id = await acting_company_id(request, user, control_db)
    try:
        trigger = await triggers_mod.create(db, control_db, company_id, body.model_dump(exclude_unset=True),
                                            triggers_mod.Actor("user", user.id))
    except triggers_mod.TriggerError as error:
        raise HTTPException(status_code=422, detail=str(error))
    await _commit(db, control_db)
    return _out(trigger, await automation_state_for(company_id, control_db))


@control_router.post("/triggers/preview", response_model=PreviewOut,
                     openapi_extra=capability("The next times a schedule or timer would fire, before saving it",
                                              "read", "automation.read"))
async def preview_trigger(body: PreviewRequest, request: Request, user: User = Depends(get_current_user),
                          control_db: AsyncSession = Depends(get_control_db)) -> PreviewOut:
    from src.common.timezones import company_timezone_name

    company_id = await acting_company_id(request, user, control_db)
    zone = body.timezone or await company_timezone_name(company_id, control_db)
    fields = body.model_dump()
    if body.kind == "schedule":
        try:
            schedules.validate_cron(body.cron)
            schedules.validate_timezone(zone)
        except schedules.ScheduleError as error:
            raise HTTPException(status_code=422, detail=str(error))
    times = schedules.preview(fields, now=datetime.utcnow(), default_timezone=zone, count=body.count)
    if body.until_at is not None:
        until = triggers_mod._naive_utc(body.until_at)
        times = [t for t in times if t <= until]
    return PreviewOut(timezone=zone, times=times)


@control_router.post("/triggers/test-filter", response_model=FilterTestOut,
                     openapi_extra=capability("Which of the business's recent events a trigger's filter would have "
                                              "matched, before saving it", "read", "automation.read"))
async def test_filter(body: FilterTestRequest, request: Request, user: User = Depends(get_current_user),
                      control_db: AsyncSession = Depends(get_control_db),
                      db: AsyncSession = Depends(get_acting_tenant_db)) -> FilterTestOut:
    from src.automation import filters

    company_id = await acting_company_id(request, user, control_db)
    try:
        spec = filters.validate(body.filter)
    except filters.FilterError as error:
        raise HTTPException(status_code=422, detail=f"filter: {error}")
    pattern = body.event_type
    query = select(Event).where(Event.company_id == company_id)
    query = query.where(Event.type.startswith(pattern[:-1]) if pattern.endswith(".*") else Event.type == pattern)
    recent = (await db.execute(query.order_by(Event.id.desc()).limit(body.sample))).scalars().all()
    hits = [e for e in recent if filters.matches(spec, router_mod.event_view(e))]
    return FilterTestOut(checked=len(recent), matched=len(hits), matches=[EventOut.model_validate(e) for e in hits[:10]])


@control_router.get("/triggers/{trigger_id}", response_model=TriggerOut,
                    openapi_extra=capability("One trigger", "read", "automation.read"))
async def get_trigger(trigger_id: UUID, request: Request, user: User = Depends(get_current_user),
                      control_db: AsyncSession = Depends(get_control_db),
                      db: AsyncSession = Depends(get_acting_tenant_db)) -> TriggerOut:
    company_id = await acting_company_id(request, user, control_db)
    return _out(await _trigger_or_404(db, company_id, trigger_id), await automation_state_for(company_id, control_db))


@control_router.patch("/triggers/{trigger_id}", response_model=TriggerOut,
                      openapi_extra=capability("Change a trigger (turn it on or off, its timing, input or rules)",
                                               "write_internal", "automation.configure"))
async def update_trigger(trigger_id: UUID, body: TriggerFields, request: Request,
                         user: User = Depends(get_current_user), control_db: AsyncSession = Depends(get_control_db),
                         db: AsyncSession = Depends(get_acting_tenant_db)) -> TriggerOut:
    _require(user, EDIT_ROLES, "change triggers")
    company_id = await acting_company_id(request, user, control_db)
    trigger = await _trigger_or_404(db, company_id, trigger_id)
    try:
        await triggers_mod.update(db, control_db, company_id, trigger, body.model_dump(exclude_unset=True))
    except triggers_mod.TriggerError as error:
        raise HTTPException(status_code=422, detail=str(error))
    await _commit(db, control_db)
    return _out(trigger, await automation_state_for(company_id, control_db))


@control_router.delete("/triggers/{trigger_id}", status_code=204, response_class=Response, response_model=None,
                       openapi_extra=capability("Delete a trigger; its past firings go with it, runs it started stay",
                                                "destructive", "automation.configure", approval="human"))
async def delete_trigger(trigger_id: UUID, request: Request, user: User = Depends(get_current_user),
                         control_db: AsyncSession = Depends(get_control_db),
                         db: AsyncSession = Depends(get_acting_tenant_db)) -> Response:
    _require(user, EDIT_ROLES, "delete triggers")
    company_id = await acting_company_id(request, user, control_db)
    await triggers_mod.remove(db, control_db, company_id, await _trigger_or_404(db, company_id, trigger_id))
    await _commit(db, control_db)
    return Response(status_code=204)


@control_router.get("/triggers/{trigger_id}/firings", response_model=List[FiringOut],
                    openapi_extra=capability("What a trigger decided each time, and why (started, queued, "
                                             "skipped, blocked)", "read", "automation.read"))
async def trigger_firings(trigger_id: UUID, request: Request, limit: int = Query(50, ge=1, le=500),
                          user: User = Depends(get_current_user), control_db: AsyncSession = Depends(get_control_db),
                          db: AsyncSession = Depends(get_acting_tenant_db)) -> List[FiringOut]:
    company_id = await acting_company_id(request, user, control_db)
    await _trigger_or_404(db, company_id, trigger_id)
    rows = (await db.execute(select(TriggerFiring).where(TriggerFiring.trigger_id == trigger_id)
                             .order_by(TriggerFiring.decided_at.desc()).limit(limit))).scalars().all()
    return [FiringOut.model_validate(r) for r in rows]


@control_router.post("/triggers/{trigger_id}/run", response_model=EventOut, status_code=202,
                     openapi_extra=capability("Run a trigger's agent now, through the trigger's rules and the "
                                              "wallet check", "spend", "automation.operate", idempotent=False))
async def run_trigger_now(trigger_id: UUID, request: Request, user: User = Depends(get_current_user),
                          control_db: AsyncSession = Depends(get_control_db),
                          db: AsyncSession = Depends(get_acting_tenant_db)) -> EventOut:
    _require(user, OPERATE_ROLES, "run triggers")
    company_id = await acting_company_id(request, user, control_db)
    trigger = await _trigger_or_404(db, company_id, trigger_id)
    if not trigger.enabled:
        raise HTTPException(status_code=409, detail="The trigger is off; turn it on to run it")
    row, _ = await store.emit(db, company_id, events_mod.Envelope(
        type="manual.fired", source=f"user:{user.id}", trust="internal", subject=f"trigger:{trigger.id}",
        dedupe_key=f"manual:{trigger.id}:{uuid.uuid4().hex}",
        data={"trigger_id": str(trigger.id), "trigger_name": trigger.name, "requested_by": str(user.id)}))
    return EventOut.model_validate(row)


# ── Events ─────────────────────────────────────────────────────────────────

@control_router.get("/events", response_model=List[EventOut],
                    openapi_extra=capability("The business's event log, newest first", "read", "automation.read"))
async def list_events(request: Request, type: Optional[str] = Query(None, description="A type or prefix.*"),
                      status: Optional[str] = Query(None, description="received | routed | parked | dead"),
                      since: Optional[datetime] = None, until: Optional[datetime] = None,
                      before: Optional[UUID] = Query(None, description="Page: events older than this one"),
                      limit: int = Query(50, ge=1, le=200), user: User = Depends(get_current_user),
                      control_db: AsyncSession = Depends(get_control_db),
                      db: AsyncSession = Depends(get_acting_tenant_db)) -> List[EventOut]:
    company_id = await acting_company_id(request, user, control_db)
    query = select(Event).where(Event.company_id == company_id)
    if type:
        query = query.where(Event.type.startswith(type[:-1]) if type.endswith(".*") else Event.type == type)
    if status:
        query = query.where(Event.status == status)
    if since:
        query = query.where(Event.time >= triggers_mod._naive_utc(since))
    if until:
        query = query.where(Event.time <= triggers_mod._naive_utc(until))
    if before:
        query = query.where(Event.id < before)  # UUIDv7: ids sort by the time they were made
    rows = (await db.execute(query.order_by(Event.id.desc()).limit(limit))).scalars().all()
    return [EventOut.model_validate(r) for r in rows]


@control_router.get("/events/{event_id}", response_model=EventDetail,
                    openapi_extra=capability("One event with what each trigger decided and the runs it started",
                                             "read", "automation.read"))
async def get_event(event_id: UUID, request: Request, user: User = Depends(get_current_user),
                    control_db: AsyncSession = Depends(get_control_db),
                    db: AsyncSession = Depends(get_acting_tenant_db)) -> EventDetail:
    from src.ai.orm import ExecutionRun

    company_id = await acting_company_id(request, user, control_db)
    event = await _event_or_404(db, company_id, event_id)
    firings = (await db.execute(select(TriggerFiring).where(TriggerFiring.event_id == event_id)
                                .order_by(TriggerFiring.decided_at))).scalars().all()
    runs = (await db.execute(select(ExecutionRun).where(
        ExecutionRun.company_id == company_id, ExecutionRun.event_id == event_id)
        .order_by(ExecutionRun.created_at))).scalars().all()
    detail = EventDetail.model_validate(event)
    detail.data, detail.data_ref = event.data or {}, event.data_ref
    detail.firings = [FiringOut.model_validate(f) for f in firings]
    detail.runs = [RunRef(id=r.id, status=str(getattr(r.status, "value", r.status)), entity_id=r.entity_id,
                          trigger_id=r.trigger_id, created_at=r.created_at) for r in runs]
    return detail


@control_router.post("/events/{event_id}/replay", response_model=EventOut, status_code=202,
                     openapi_extra=capability("Route a dead or held event again; a trigger that already decided "
                                              "about it does not decide twice", "spend", "automation.operate"))
async def replay_event(event_id: UUID, request: Request, user: User = Depends(get_current_user),
                       control_db: AsyncSession = Depends(get_control_db),
                       db: AsyncSession = Depends(get_acting_tenant_db)) -> EventOut:
    _require(user, OPERATE_ROLES, "replay events")
    company_id = await acting_company_id(request, user, control_db)
    event = await _event_or_404(db, company_id, event_id)
    if not await router_mod.replay(db, company_id, event.id):
        raise HTTPException(status_code=409, detail=f"Only a dead or held event is replayed; this one is {event.status}")
    return EventOut.model_validate(await db.get(Event, event_id))


# ── Waiting runs ───────────────────────────────────────────────────────────

@control_router.get("/waits", response_model=List[WaitOut],
                    openapi_extra=capability("Runs waiting for an event, soonest deadline first", "read",
                                             "automation.read"))
async def list_waits(request: Request, user: User = Depends(get_current_user),
                     control_db: AsyncSession = Depends(get_control_db),
                     db: AsyncSession = Depends(get_acting_tenant_db)) -> List[WaitOut]:
    from src.ai.orm import ExecutionRun, HierarchicalEntity
    from src.automation import waits as waits_mod

    company_id = await acting_company_id(request, user, control_db)
    rows = await waits_mod.list_waiting(db, company_id)
    runs = dict((await db.execute(select(ExecutionRun.id, ExecutionRun.entity_id).where(
        ExecutionRun.id.in_([w.run_id for w in rows])))).all()) if rows else {}
    names = dict((await db.execute(select(HierarchicalEntity.id, HierarchicalEntity.name).where(
        HierarchicalEntity.id.in_(set(runs.values()))))).all()) if runs else {}
    out = []
    for wait in rows:
        item = WaitOut.model_validate(wait)
        item.entity_id = runs.get(wait.run_id)
        item.entity_name = names.get(item.entity_id)
        out.append(item)
    return out


@control_router.post("/waits/{wait_id}/cancel", response_model=WaitOut,
                     openapi_extra=capability("Stop a run's wait: the run goes on without the event", "spend",
                                              "automation.operate"))
async def cancel_wait(wait_id: UUID, request: Request, user: User = Depends(get_current_user),
                      control_db: AsyncSession = Depends(get_control_db),
                      db: AsyncSession = Depends(get_acting_tenant_db)) -> WaitOut:
    from src.automation import waits as waits_mod

    _require(user, OPERATE_ROLES, "cancel waits")
    company_id = await acting_company_id(request, user, control_db)
    wait = await db.get(Wait, wait_id)
    if wait is None or wait.company_id != company_id:
        raise HTTPException(status_code=404, detail="Wait not found")
    if wait.status != "waiting":
        raise HTTPException(status_code=409, detail=f"This wait is already {wait.status}")
    await waits_mod.close(db, control_db, company_id, wait.id, "cancelled")
    await _commit(db, control_db)
    await waits_mod.enqueue_resume(company_id, wait.run_id, f"{wait.id}:cancel")
    return WaitOut.model_validate(wait)


# ── Scopes and health ──────────────────────────────────────────────────────

async def _set_scope(db: AsyncSession, control_db: AsyncSession, company_id: UUID, scope: str,
                     enable: bool) -> int:
    marker = f"scope:{scope}"
    query = select(Trigger).where(Trigger.company_id == company_id, Trigger.scope == scope)
    query = query.where(Trigger.paused_reason == marker) if enable else query.where(Trigger.enabled.is_(True))
    changed = 0
    for trigger in (await db.execute(query)).scalars().all():
        await triggers_mod.update(db, control_db, company_id, trigger, {"enabled": enable})
        trigger.paused_reason = None if enable else marker
        changed += 1
    await _commit(db, control_db)
    return changed


@control_router.post("/scopes/{scope}/pause", response_model=ScopeResult,
                     openapi_extra=capability("Pause every trigger of one department or process", "write_internal",
                                              "automation.operate"))
async def pause_scope(scope: str, request: Request, user: User = Depends(get_current_user),
                      control_db: AsyncSession = Depends(get_control_db),
                      db: AsyncSession = Depends(get_acting_tenant_db)) -> ScopeResult:
    _require(user, OPERATE_ROLES, "pause triggers")
    company_id = await acting_company_id(request, user, control_db)
    return ScopeResult(scope=scope, changed=await _set_scope(db, control_db, company_id, scope, False))


@control_router.post("/scopes/{scope}/resume", response_model=ScopeResult,
                     openapi_extra=capability("Resume the triggers a scope pause turned off (not ones turned off "
                                              "by hand)", "write_internal", "automation.operate"))
async def resume_scope(scope: str, request: Request, user: User = Depends(get_current_user),
                       control_db: AsyncSession = Depends(get_control_db),
                       db: AsyncSession = Depends(get_acting_tenant_db)) -> ScopeResult:
    _require(user, OPERATE_ROLES, "resume triggers")
    company_id = await acting_company_id(request, user, control_db)
    return ScopeResult(scope=scope, changed=await _set_scope(db, control_db, company_id, scope, True))


@control_router.get("/health", response_model=HealthOut,
                    openapi_extra=capability("How the business's automation is doing: dead and held events, missed "
                                             "schedules, triggers that keep failing", "read", "automation.read"))
async def automation_health(request: Request, user: User = Depends(get_current_user),
                            control_db: AsyncSession = Depends(get_control_db),
                            db: AsyncSession = Depends(get_acting_tenant_db)) -> HealthOut:
    company_id = await acting_company_id(request, user, control_db)
    day_ago = datetime.utcnow() - timedelta(hours=24)

    async def count(query) -> int:
        return (await db.execute(query)).scalar() or 0

    events = select(func.count()).select_from(Event).where(Event.company_id == company_id)
    firings = select(func.count()).select_from(TriggerFiring).join(Trigger, Trigger.id == TriggerFiring.trigger_id) \
        .where(Trigger.company_id == company_id)
    triggers_total = select(func.count()).select_from(Trigger).where(Trigger.company_id == company_id)
    problems = (await db.execute(
        select(Trigger.id, Trigger.name, func.count(TriggerFiring.id), func.max(TriggerFiring.decided_at))
        .join(TriggerFiring, TriggerFiring.trigger_id == Trigger.id)
        .where(Trigger.company_id == company_id, TriggerFiring.outcome.in_(PROBLEM_OUTCOMES),
               TriggerFiring.decided_at >= day_ago)
        .group_by(Trigger.id, Trigger.name).order_by(func.count(TriggerFiring.id).desc()).limit(10))).all()
    failing = []
    for trigger_id, name, n, _ in problems:
        last = (await db.execute(select(TriggerFiring).where(TriggerFiring.trigger_id == trigger_id)
                                 .order_by(TriggerFiring.decided_at.desc()).limit(1))).scalar_one()
        failing.append(FailingTrigger(trigger_id=trigger_id, name=name, problems=n, last_outcome=last.outcome,
                                      last_reason=last.reason))
    upcoming = (await db.execute(
        select(Trigger).where(Trigger.company_id == company_id, Trigger.enabled.is_(True),
                              Trigger.next_fire_at.isnot(None))
        .order_by(Trigger.next_fire_at).limit(5))).scalars().all()
    return HealthOut(
        automation_state=await automation_state_for(company_id, control_db),
        started_24h=await count(firings.where(TriggerFiring.outcome == guards.STARTED,
                                              TriggerFiring.decided_at >= day_ago)),
        upcoming=[UpcomingRun(trigger_id=t.id, name=t.name, kind=t.kind, next_fire_at=t.next_fire_at,
                              created_by_kind=t.created_by_kind) for t in upcoming],
        triggers_enabled=await count(triggers_total.where(Trigger.enabled.is_(True))),
        triggers_total=await count(triggers_total),
        dead_events=await count(events.where(Event.status == "dead")),
        parked_events=await count(events.where(Event.status == "parked")),
        oldest_parked_at=(await db.execute(select(func.min(Event.received_at)).where(
            Event.company_id == company_id, Event.status == "parked"))).scalar(),
        waiting_runs=await count(select(func.count()).select_from(Wait).where(
            Wait.company_id == company_id, Wait.status == "waiting")),
        queued_firings=await count(firings.where(TriggerFiring.outcome == guards.QUEUED,
                                                 TriggerFiring.run_id.is_(None))),
        missed_schedules_24h=await count(firings.where(TriggerFiring.outcome == guards.SKIPPED_MISSED,
                                                       TriggerFiring.decided_at >= day_ago)),
        failing_triggers=failing,
    )


FilterTestOut.model_rebuild()

"""The automation API: ``/api/v1/automation/*`` (tech spec §7.12, Appendix C).

Every endpoint is public-API-first and carries the capability annotations
Pragya will read (tech spec §20, PR-2: ``x-hb-summary``, ``x-hb-effect``,
``x-hb-permission``, ``x-hb-approval``, ``x-hb-idempotent``, ``x-hb-scope``).

This module holds the business's automation settings (decision D47): its
limits — none unless set — and whether its automation runs, plus the
platform-wide defaults for staff. The control room (triggers, events,
replay, health) is ``control_room.py``, mounted with it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.auth.roles import Role
from src.automation import limits as limits_mod
from src.common.tenancy.session import acting_company_id, get_control_db

tenant_router = APIRouter(prefix="/api/v1/automation", tags=["Automation"])
admin_router = APIRouter(prefix="/api/v1/admin/automation", tags=["Automation (platform)"])

# Who may change what (functional spec §2.1): owner and admin set limits; the
# operator may pause; platform staff may do both for any business they see.
EDIT_ROLES = {Role.APP_ADMIN, Role.PARTNER_ADMIN, Role.TENANT_ADMIN}
PAUSE_ROLES = EDIT_ROLES | {Role.TENANT_USER, Role.APP_USER, Role.PARTNER_USER}


def capability(summary: str, effect: str, permission: str, *, scope: str = "tenant",
               approval: str = "none", idempotent: bool = True) -> Dict[str, Any]:
    """OpenAPI extensions of one endpoint (PR-2)."""
    return {"x-hb-summary": summary, "x-hb-effect": effect, "x-hb-permission": permission,
            "x-hb-approval": approval, "x-hb-idempotent": idempotent, "x-hb-scope": scope}


class LimitInfo(BaseModel):
    key: str
    label: str
    help: str
    kind: str
    choices: List[str] = []
    unit: str = ""
    default: Optional[str] = None


class AutomationSettings(BaseModel):
    company_id: UUID
    automation_state: str
    paused_reason: Optional[str] = None
    # The business time zone schedules use (changed with PATCH /api/v1/companies/{id}).
    timezone: str
    # What applies now; what the business set (absent = inherited, null = no limit);
    # the platform's defaults.
    effective: Dict[str, Any]
    business: Dict[str, Any]
    platform: Dict[str, Any]
    catalogue: List[LimitInfo]


class LimitsUpdate(BaseModel):
    limits: Dict[str, Any] = Field(
        default_factory=dict,
        description="Limit name → a value, or null for no limit. A name left out inherits the platform's default.")


class PauseRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


def _catalogue() -> List[LimitInfo]:
    return [LimitInfo(key=l.key, label=l.label, help=l.help, kind=l.kind, choices=list(l.choices),
                      unit=l.unit, default=l.default) for l in limits_mod.CATALOGUE]


async def _settings_row(db: AsyncSession, company_id: Optional[UUID]):
    from src.automation.models import AutomationLimitsRow

    column = AutomationLimitsRow.company_id
    condition = column.is_(None) if company_id is None else column == company_id
    return (await db.execute(select(AutomationLimitsRow).where(condition))).scalar_one_or_none()


async def _view(db: AsyncSession, company_id: UUID) -> AutomationSettings:
    platform = await limits_mod.stored_values(db, None)
    business = await limits_mod.stored_values(db, company_id)
    from src.common.timezones import company_timezone_name

    row = await _settings_row(db, company_id)
    return AutomationSettings(
        company_id=company_id,
        automation_state=row.automation_state if row else "running",
        paused_reason=row.paused_reason if row else None,
        timezone=await company_timezone_name(company_id, db),
        effective=limits_mod.resolve(platform, business).as_dict(),
        business=business, platform=platform, catalogue=_catalogue(),
    )


def _require(user: User, roles: set) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="Not authorized to change automation settings")


@tenant_router.get("/settings", response_model=AutomationSettings,
            openapi_extra=capability("The business's automation limits (none unless set) and whether its "
                                     "automation is running", "read", "automation.read"))
async def get_settings(request: Request, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_control_db)) -> AutomationSettings:
    return await _view(db, await acting_company_id(request, user, db))


@tenant_router.put("/settings/limits", response_model=AutomationSettings,
            openapi_extra=capability("Set the business's automation limits: a value, null for no limit, or "
                                     "leave a limit out to inherit the platform's", "write_internal",
                                     "automation.configure"))
async def put_limits(body: LimitsUpdate, request: Request, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_control_db)) -> AutomationSettings:
    _require(user, EDIT_ROLES)
    company_id = await acting_company_id(request, user, db)
    try:
        await limits_mod.save(db, company_id, body.limits, user.id)
    except limits_mod.LimitsError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return await _view(db, company_id)


async def _set_state(db: AsyncSession, company_id: Optional[UUID], state: str, reason: Optional[str],
                     user: User) -> None:
    """Pause or resume one business's automation (kill switch, functional spec §3.5)."""
    from datetime import datetime

    from src.automation.models import AutomationLimitsRow
    from src.common.tenancy.models import TenantDirectoryEntry

    row = await _settings_row(db, company_id)
    if row is None:
        row = AutomationLimitsRow(company_id=company_id, limits={})
        db.add(row)
    row.automation_state = state
    row.paused_reason = reason if state == "paused" else None
    row.updated_by, row.updated_at = user.id, datetime.utcnow()
    if company_id is not None:
        # The tenant directory keeps the same state for split mode (tech spec §6.1).
        entry = await db.get(TenantDirectoryEntry, company_id)
        if entry is not None:
            entry.automation_state = state
    await db.commit()
    limits_mod.forget_state(company_id)  # None: the platform row — every business's cached state
    if state == "running":
        await _release(company_id)


async def _release(company_id: Optional[UUID]) -> None:
    """After a resume: the event worker routes what was held, oldest first (else its sweep will)."""
    import logging

    from src.common.job_queue import EVENT_QUEUE, enqueue_job, tenant_arg

    try:
        await enqueue_job("release_parked", company_id=tenant_arg(company_id), _queue_name=EVENT_QUEUE)
    except Exception as error:  # Redis away: the sweep every 30 s releases them
        logging.getLogger(__name__).warning("release of held events not queued: %s", error)


@tenant_router.post("/pause", response_model=AutomationSettings,
             openapi_extra=capability("Pause all of the business's automation: new events are held, schedules "
                                      "do not fire, running work finishes", "write_internal", "automation.pause"))
async def pause(body: PauseRequest, request: Request, user: User = Depends(get_current_user),
                db: AsyncSession = Depends(get_control_db)) -> AutomationSettings:
    _require(user, PAUSE_ROLES)
    company_id = await acting_company_id(request, user, db)
    await _set_state(db, company_id, "paused", body.reason or f"paused by {user.email}", user)
    return await _view(db, company_id)


@tenant_router.post("/resume", response_model=AutomationSettings,
             openapi_extra=capability("Resume the business's automation; held events run in order",
                                      "write_internal", "automation.pause"))
async def resume(request: Request, user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_control_db)) -> AutomationSettings:
    _require(user, PAUSE_ROLES)
    company_id = await acting_company_id(request, user, db)
    await _set_state(db, company_id, "running", None, user)
    return await _view(db, company_id)


# ── Platform defaults (HireBuddha staff) ───────────────────────────────────

class PlatformLimits(BaseModel):
    platform: Dict[str, Any]
    catalogue: List[LimitInfo]
    # "paused" stops automation for every business (emergency stop).
    automation_state: str = "running"
    paused_reason: Optional[str] = None


async def _platform_view(db: AsyncSession) -> PlatformLimits:
    row = await _settings_row(db, None)
    return PlatformLimits(platform=await limits_mod.stored_values(db, None), catalogue=_catalogue(),
                          automation_state=row.automation_state if row else "running",
                          paused_reason=row.paused_reason if row else None)


def _require_platform_admin(user: User) -> None:
    if user.role != Role.APP_ADMIN:
        raise HTTPException(status_code=403, detail="Platform administrators only")


@admin_router.get("/limits", response_model=PlatformLimits,
                  openapi_extra=capability("Platform-wide default automation limits (none unless set)", "read",
                                           "platform.automation", scope="platform"))
async def get_platform_limits(user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_control_db)) -> PlatformLimits:
    _require_platform_admin(user)
    return await _platform_view(db)


@admin_router.put("/limits", response_model=PlatformLimits,
                  openapi_extra=capability("Set the platform-wide default automation limits; a business's own "
                                           "values still win", "write_internal", "platform.automation",
                                           scope="platform"))
async def put_platform_limits(body: LimitsUpdate, user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_control_db)) -> PlatformLimits:
    _require_platform_admin(user)
    try:
        await limits_mod.save(db, None, body.limits, user.id)
    except limits_mod.LimitsError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return await _platform_view(db)


@admin_router.post("/pause", response_model=PlatformLimits,
                   openapi_extra=capability("Emergency stop: pause automation for every business", "write_internal",
                                            "platform.automation", scope="platform"))
async def pause_platform(body: PauseRequest, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_control_db)) -> PlatformLimits:
    _require_platform_admin(user)
    await _set_state(db, None, "paused", body.reason or f"emergency stop by {user.email}", user)
    return await _platform_view(db)


@admin_router.post("/resume", response_model=PlatformLimits,
                   openapi_extra=capability("End the emergency stop; businesses paused on their own stay paused",
                                            "write_internal", "platform.automation", scope="platform"))
async def resume_platform(user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_control_db)) -> PlatformLimits:
    _require_platform_admin(user)
    await _set_state(db, None, "running", None, user)
    return await _platform_view(db)


# What main.py mounts (router_mounts.mount_optional takes a module's ``router``):
# the settings above, and the control room (triggers, events, health).
from src.automation.control_room import control_router  # noqa: E402 — it uses the roles above

router = APIRouter()
router.include_router(tenant_router)
router.include_router(control_router)
router.include_router(admin_router)

"""The Connections API (Phase 14 WS5 5.3, 5.8; tech spec §10.5; functional spec §6).

Business (the caller's own company; owners and admins change, everyone sees):

    GET    /api/v1/connectors                              what can be connected
    GET    /api/v1/connections                             the business's connections
    POST   /api/v1/connections/start                       begin connecting (redirect, embedded sign-up or form)
    GET    /api/v1/connections/pending/{pending_id}        the accounts to choose from
    POST   /api/v1/connections/pending/{pending_id}/finalize
    POST   /api/v1/connections/embedded-signup/complete    WhatsApp: the browser's sign-up code
    POST   /api/v1/connections/form                        a mailbox, an API key, an MCP server
    GET    /api/v1/connections/{id}                        detail, activity, what depends on it
    POST   /api/v1/connections/{id}/test
    POST   /api/v1/connections/{id}/reconnect
    PUT    /api/v1/connections/{id}/grants                 who may use it
    GET    /api/v1/connections/{id}/impact                 what disconnecting stops
    DELETE /api/v1/connections/{id}

Providers and platform services:

    GET    /oauth/callback/{provider}                      the provider sends the browser back here
    POST   /internal/v1/tokens                             the token broker (X-Internal-Token)

Platform staff (``app_admin``):

    GET    /api/v1/admin/connectors                        with each provider review (E09-S11)
    PATCH  /api/v1/admin/connectors/{id}                   switch Available / Preview / Unavailable, record a review
    GET    /api/v1/admin/unrouted-events
"""
from __future__ import annotations

import hmac
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker, get_current_user
from src.auth.models import User
from src.auth.roles import ADMIN_ROLES
from src.automation.api import capability
from src.common.tenancy.session import get_control_db
from src.connections import service
from src.connections.catalog import catalog_rows, connector_view
from src.connections.models import CATALOG_STATUSES, ConnectorCatalogEntry, UnroutedEvent
from src.connections.providers import ProviderError
from src.connections.webhooks import router as webhook_router

router = APIRouter(tags=["Connections"])
router.include_router(webhook_router)

staff_only = RoleChecker(["app_admin"])


class Grant(BaseModel):
    principal_kind: str = Field(description="all_agents, entity (one agent) or app")
    principal_id: Optional[uuid.UUID] = None
    actions: List[str] = Field(default_factory=lambda: ["*"])


class StartRequest(BaseModel):
    connector_id: str
    return_path: Optional[str] = Field(None, description="Where the browser returns, e.g. /connections")


class FinalizeRequest(BaseModel):
    accounts: List[str] = Field(min_length=1, description="external_id of each account to connect")
    grants: Optional[List[Grant]] = Field(None, description="Default: all agents")


class FormRequest(BaseModel):
    connector_id: str
    fields: Dict[str, Any]
    display_name: Optional[str] = None
    grants: Optional[List[Grant]] = None


class EmbeddedSignupRequest(BaseModel):
    state: str
    code: str
    waba_id: Optional[str] = None
    phone_number_id: Optional[str] = None


class GrantsRequest(BaseModel):
    grants: List[Grant]


class TokenRequest(BaseModel):
    company_id: uuid.UUID
    connection_id: uuid.UUID
    principal_kind: str
    principal_id: uuid.UUID
    action: Optional[str] = None
    run_id: Optional[uuid.UUID] = None


class ConnectorUpdate(BaseModel):
    status_override: Optional[str] = Field(None, description="available, preview, unavailable, planned; null clears")
    approval: Optional[Dict[str, Any]] = None
    clear_override: bool = False


def _manager(user: User) -> None:
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Owners and admins manage connections")


def _grants(grants: Optional[List[Grant]]) -> Optional[List[Dict[str, Any]]]:
    return [g.model_dump(mode="json") for g in grants] if grants is not None else None


async def _call(coro: Any) -> Any:
    try:
        return await coro
    except service.NoSuchConnection as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except service.ConnectionProblem as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.get("/api/v1/connectors", openapi_extra=capability(
    "What the business can connect: each connector's status, actions, the events it delivers and its form.",
    "read", "any signed-in user"))
async def connectors(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_control_db)):
    return [connector_view(row) for row in await catalog_rows(db)]


@router.get("/api/v1/connections", openapi_extra=capability(
    "The business's connections with their health, expiry and who may use them (never a secret).",
    "read", "any signed-in user"))
async def list_connections(user: User = Depends(get_current_user)):
    return await service.list_connections(user.company_id)


@router.post("/api/v1/connections/start", openapi_extra=capability(
    "Begin connecting an account: a provider sign-in address, Embedded Signup parameters, or a form.",
    "write_external", "owner, admin", idempotent=False))
async def start(body: StartRequest, user: User = Depends(get_current_user)):
    _manager(user)
    return await _call(service.start(user.company_id, user.id, body.connector_id, return_path=body.return_path))


@router.get("/oauth/callback/{provider}", include_in_schema=False)
async def oauth_callback(provider: str, request: Request):
    return RedirectResponse(await service.callback(provider, dict(request.query_params)), status_code=302)


@router.get("/api/v1/connections/pending/{pending_id}", openapi_extra=capability(
    "The accounts a sign-in returned, to choose which to connect.", "read", "owner, admin"))
async def pending(pending_id: str, user: User = Depends(get_current_user)):
    _manager(user)
    return await _call(service.pending_view(user.company_id, pending_id))


@router.post("/api/v1/connections/pending/{pending_id}/finalize", openapi_extra=capability(
    "Connect the chosen accounts with who may use them; tests each and subscribes to its events.",
    "write_external", "owner, admin", idempotent=False))
async def finalize(pending_id: str, body: FinalizeRequest, user: User = Depends(get_current_user)):
    _manager(user)
    return await _call(service.finalize(user.company_id, user.id, pending_id, body.accounts,
                                        grants=_grants(body.grants)))


@router.post("/api/v1/connections/embedded-signup/complete", openapi_extra=capability(
    "WhatsApp: turn the browser's Embedded Signup code into the numbers to choose from.",
    "write_external", "owner, admin", idempotent=False))
async def embedded_signup(body: EmbeddedSignupRequest, user: User = Depends(get_current_user)):
    _manager(user)
    return await _call(service.complete_embedded_signup(user.company_id, body.state, body.model_dump()))


@router.post("/api/v1/connections/form", openapi_extra=capability(
    "Connect a mailbox, an API-key service or an MCP server from a form; the secret is sealed.",
    "write_external", "owner, admin", idempotent=False))
async def form(body: FormRequest, user: User = Depends(get_current_user)):
    _manager(user)
    return await _call(service.create_from_form(user.company_id, user.id, body.connector_id, body.fields,
                                                grants=_grants(body.grants), display_name=body.display_name))


@router.get("/api/v1/connections/{connection_id}", openapi_extra=capability(
    "A connection's detail: permissions, health, expiry, who may use it, what depends on it, activity.",
    "read", "any signed-in user"))
async def get_connection(connection_id: uuid.UUID, user: User = Depends(get_current_user)):
    try:
        return await service.detail(user.company_id, connection_id)
    except service.ConnectionProblem:
        raise HTTPException(status_code=404, detail="There is no such connection.")


@router.post("/api/v1/connections/{connection_id}/test", openapi_extra=capability(
    "Check the connection still works.", "read", "owner, admin", idempotent=False))
async def test_connection(connection_id: uuid.UUID, user: User = Depends(get_current_user)):
    _manager(user)
    return await _call(service.test(user.company_id, connection_id, actor_id=user.id))


@router.post("/api/v1/connections/{connection_id}/reconnect", openapi_extra=capability(
    "Sign in again to the same account; the connection keeps its grants and history.",
    "write_external", "owner, admin", idempotent=False))
async def reconnect(connection_id: uuid.UUID, body: Optional[StartRequest] = None,
                    user: User = Depends(get_current_user)):
    _manager(user)
    detail = await get_connection(connection_id, user)
    return await _call(service.start(user.company_id, user.id, detail["connector_id"],
                                     return_path=body.return_path if body else None, reconnect_id=connection_id))


@router.put("/api/v1/connections/{connection_id}/grants", openapi_extra=capability(
    "Who may use the connection: all agents, chosen agents, chosen apps.", "write_internal", "owner, admin"))
async def set_grants(connection_id: uuid.UUID, body: GrantsRequest, user: User = Depends(get_current_user)):
    _manager(user)
    return await _call(service.set_grants(user.company_id, connection_id, _grants(body.grants), actor_id=user.id))


@router.get("/api/v1/connections/{connection_id}/impact", openapi_extra=capability(
    "What stops if the connection is removed: the agents and apps using it, the triggers listening to it.",
    "read", "any signed-in user"))
async def impact(connection_id: uuid.UUID, user: User = Depends(get_current_user)):
    return await _call(service.impact(user.company_id, connection_id))


@router.delete("/api/v1/connections/{connection_id}", openapi_extra=capability(
    "Disconnect: revoke at the provider, delete the secret, pause the triggers that listen to it.",
    "destructive", "owner, admin", approval="human", idempotent=True))
async def revoke(connection_id: uuid.UUID, user: User = Depends(get_current_user)):
    _manager(user)
    return await _call(service.revoke(user.company_id, connection_id, actor_id=user.id))


def require_internal(x_internal_token: str = Header(default="")) -> None:
    from src.common.config import settings

    if not settings.internal_events_enabled:
        raise HTTPException(status_code=503, detail="INTERNAL_TOKEN is not set to a real secret")
    if not hmac.compare_digest(x_internal_token.encode(), settings.INTERNAL_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Internal-Token")


@router.post("/internal/v1/tokens", include_in_schema=False, dependencies=[Depends(require_internal)])
async def issue_token(body: TokenRequest):
    try:
        token = await service.issue_token(body.company_id, body.connection_id, principal_kind=body.principal_kind,
                                          principal_id=body.principal_id, action=body.action, run_id=body.run_id)
    except service.NotGranted as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except service.NoSuchConnection as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except service.ConnectionProblem as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"access_token": token.access_token, "expires_at": token.expires_at.isoformat() if token.expires_at else None,
            "extra": token.extra}


# ── Platform staff ──────────────────────────────────────────────────────────

def _admin_view(row: ConnectorCatalogEntry) -> Dict[str, Any]:
    return {**connector_view(row), "yaml_status": row.status, "status_override": row.status_override,
            "approval": row.approval or {}, "oauth_app_ref": row.oauth_app_ref,
            "synced_at": row.synced_at.isoformat() if row.synced_at else None}


@router.get("/api/v1/admin/connectors", openapi_extra=capability(
    "Every connector with its provider review (verification, expiry, limits) and status.",
    "read", "app_admin", scope="platform"))
async def admin_connectors(_: User = Depends(staff_only), db: AsyncSession = Depends(get_control_db)):
    return [_admin_view(row) for row in await catalog_rows(db)]


@router.patch("/api/v1/admin/connectors/{connector_id}", openapi_extra=capability(
    "Switch a connector Available / Preview / Unavailable / Coming soon, or record its provider review.",
    "write_internal", "app_admin", scope="platform"))
async def admin_update_connector(connector_id: str, body: ConnectorUpdate, _: User = Depends(staff_only),
                                 db: AsyncSession = Depends(get_control_db)):
    row = await db.get(ConnectorCatalogEntry, connector_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such connector")
    if body.clear_override:
        row.status_override = None
    elif body.status_override is not None:
        if body.status_override not in CATALOG_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {CATALOG_STATUSES}")
        row.status_override = body.status_override
    if body.approval is not None:
        row.approval = {**(row.approval or {}), **body.approval}
    await db.commit()
    return _admin_view(row)


@router.get("/api/v1/admin/unrouted-events", openapi_extra=capability(
    "Provider webhooks for accounts no business has connected (kept 7 days; payload hashes only).",
    "read", "app_admin", scope="platform"))
async def unrouted_events(limit: int = 100, _: User = Depends(staff_only), db: AsyncSession = Depends(get_control_db)):
    rows = (await db.execute(select(UnroutedEvent).order_by(UnroutedEvent.received_at.desc())
                             .limit(min(max(limit, 1), 500)))).scalars().all()
    return [{"id": str(r.id), "provider": r.provider, "external_account_id": r.external_account_id,
             "event_type": r.event_type, "payload_sha256": r.payload_sha256, "payload_bytes": r.payload_bytes,
             "received_at": r.received_at.isoformat()} for r in rows]

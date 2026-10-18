"""Webhook endpoints a company's admins register for their providers (GW-01).

    POST   /api/v1/webhook-endpoints        register one; the secret is returned once
    GET    /api/v1/webhook-endpoints        the company's endpoints (no secrets)
    DELETE /api/v1/webhook-endpoints/{id}   revoke one; its URL then answers 404

A provider that issues its own signing secret (a Meta app secret, a Twilio auth
token, a LinkedIn or TikTok client secret) is registered with that secret; for
the others the platform generates one. Either way it is stored encrypted and
never returned again.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker
from src.auth.models import User
from src.common.database import get_db
from src.common.security import encrypt_api_key
from src.gateway.models import WebhookEndpoint
from src.voice.public_urls import callback_url

router = APIRouter(prefix="/api/v1/webhook-endpoints", tags=["Webhooks"])

company_admin = RoleChecker(["tenant_admin", "partner_admin"])   # app_admin always passes

Source = Literal["github", "facebook", "instagram", "linkedin", "twitter", "tiktok", "youtube",
                 "twilio", "email", "crm", "pinterest", "generic"]


class EndpointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Source
    name: str = Field(min_length=1, max_length=255)
    entity_id: Optional[uuid.UUID] = None
    # The provider's own signing secret, when it issues one; else one is generated.
    secret: Optional[str] = Field(default=None, min_length=16, max_length=512)


class EndpointOut(BaseModel):
    id: uuid.UUID
    source: str
    name: str
    entity_id: Optional[uuid.UUID]
    is_active: bool
    url: str
    created_at: Optional[datetime]
    last_received_at: Optional[datetime]


class EndpointCreated(EndpointOut):
    secret: str = Field(description="Shown once; configure it at the provider.")


def _out(row: WebhookEndpoint) -> dict:
    return {
        "id": row.id, "source": row.source, "name": row.name, "entity_id": row.entity_id,
        "is_active": row.is_active, "url": callback_url(f"/webhook/inbound/{row.id}"),
        "created_at": row.created_at, "last_received_at": row.last_received_at,
    }


@router.post("", response_model=EndpointCreated, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    body: EndpointCreate,
    current_user: User = Depends(company_admin),
    db: AsyncSession = Depends(get_db),
):
    if body.entity_id is not None:
        from src.ai.orm.entity import HierarchicalEntity
        owner = (await db.execute(
            select(HierarchicalEntity.company_id).where(HierarchicalEntity.id == body.entity_id)
        )).scalar_one_or_none()
        if owner != current_user.company_id:
            raise HTTPException(status_code=404, detail="Agent not found")
    secret = body.secret or secrets.token_urlsafe(32)
    row = WebhookEndpoint(
        company_id=current_user.company_id, source=body.source, name=body.name,
        secret_encrypted=encrypt_api_key(secret), entity_id=body.entity_id,
        created_by=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _endpoint_triggers(db, row, current_user, bind=True)
    return {**_out(row), "secret": secret}


async def _endpoint_triggers(db: AsyncSession, row: WebhookEndpoint, user: User, *, bind: bool) -> None:
    """An endpoint bound to an agent runs it through a trigger (Phase 14 WS3): made
    with the endpoint, turned off when the endpoint is revoked."""
    from src.automation import gateway
    from src.common.tenancy.session import tenant_session

    if not gateway.enabled() or (bind and row.entity_id is None):
        return
    async with tenant_session(row.company_id) as tenant_db:
        if bind:
            await gateway.add_endpoint_trigger(tenant_db, db, row, user.id)
        else:
            await gateway.remove_endpoint_triggers(tenant_db, db, row.company_id, row.id)
        await tenant_db.commit()
    await db.commit()


@router.get("", response_model=list[EndpointOut])
async def list_endpoints(
    current_user: User = Depends(company_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(WebhookEndpoint).where(WebhookEndpoint.company_id == current_user.company_id)
        .order_by(WebhookEndpoint.created_at, WebhookEndpoint.id)
    )).scalars().all()
    return [_out(r) for r in rows]


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_endpoint(
    endpoint_id: uuid.UUID,
    current_user: User = Depends(company_admin),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id,
                                      WebhookEndpoint.company_id == current_user.company_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    row.is_active = False
    await db.commit()
    await _endpoint_triggers(db, row, current_user, bind=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""The platform API's side of the Data API (tech spec §9.3; plan WS4 4.7):

* ``POST /api/v1/records/token`` — a signed-in person's 15-minute user token
  for the Data API (the HireBuddha screens use it);
* ``/api/v1/data-keys`` — a business's app and outside-system keys: create
  (the key is shown once), list, revoke. Owners and admins;
* ``/api/v1/records/settings`` — the owner's policy for schema changes
  (auto-approve agents' simple additions).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.automation.api import capability
from src.common.tenancy.session import acting_company_id, get_control_db
from src.data_api import tokens
from src.schema_engine import engine as schema
from src.billing.features import require_feature

router = APIRouter(tags=["Records"])


async def _location(request: Request, user: User, db: AsyncSession) -> Any:
    company_id = await acting_company_id(request, user, db)
    try:
        _, location = await schema.business_engine(company_id)
    except schema.RecordsUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    return company_id, location


@router.post("/api/v1/records/token", dependencies=[Depends(require_feature("feature.records"))], openapi_extra=capability(
    "A short-lived token for the business's records (Data API)", "read", "records.read"))
async def records_token(request: Request, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    company_id, location = await _location(request, user, db)
    return {"token": await tokens.mint_user_token(user, company_id, location.key),
            "expires_in": int(tokens.USER_TTL.total_seconds()), "base_url": "/data/v1", "tenant": location.key}


class KeyCreate(BaseModel):
    name: str = Field(..., max_length=120)
    scopes: Dict[str, Any] = Field(..., description='{"objects": {"contact": ["read", "create"]}, "reports": false}')
    external: bool = False


class KeyOut(BaseModel):
    id: UUID
    name: str
    prefix: str
    scopes: Dict[str, Any]
    external: bool
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class KeyCreated(KeyOut):
    key: str = Field(description="Shown once; store it in the app's secrets")


def _admin(user: User) -> None:
    if user.role not in tokens.ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Owners and admins manage data keys")


def _out(row: Any) -> Dict[str, Any]:
    return {"id": row.id, "name": row.name, "prefix": row.prefix, "scopes": row.scopes, "external": row.external,
            "created_at": row.created_at, "last_used_at": row.last_used_at, "revoked_at": row.revoked_at}


@router.post("/api/v1/data-keys", dependencies=[Depends(require_feature("feature.records.data_api_keys"))], response_model=KeyCreated, status_code=201, openapi_extra=capability(
    "Create an app key for the business's records; the key is shown once", "write_internal", "records.keys",
    approval="human", idempotent=False))
async def create_key(body: KeyCreate, request: Request, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    from src.schema_engine.models import ApiKey

    _admin(user)
    company_id, location = await _location(request, user, db)
    try:
        scopes = tokens.validate_scopes(body.scopes)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    key, prefix = tokens.new_key(location.key)
    engine, _ = await schema.business_engine(company_id)
    async with schema.session(engine) as tdb:
        row = ApiKey(id=uuid.uuid4(), company_id=company_id, name=body.name, prefix=prefix,
                     key_hash=tokens.key_hash(key), scopes=scopes, external=body.external,
                     created_by=f"user:{user.id}", created_at=datetime.utcnow())
        tdb.add(row)
        await tdb.commit()
        return {**_out(row), "key": key}


@router.get("/api/v1/data-keys", response_model=List[KeyOut], openapi_extra=capability(
    "The business's app keys (never the keys themselves)", "read", "records.keys"))
async def list_keys(request: Request, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_control_db)) -> List[Dict[str, Any]]:
    from src.schema_engine.models import ApiKey

    _admin(user)
    company_id, _ = await _location(request, user, db)
    engine, _ = await schema.business_engine(company_id)
    async with schema.session(engine) as tdb:
        rows = (await tdb.execute(select(ApiKey).where(ApiKey.company_id == company_id)
                                  .order_by(ApiKey.created_at.desc()))).scalars().all()
        return [_out(r) for r in rows]


@router.delete("/api/v1/data-keys/{key_id}", status_code=204, response_class=Response, response_model=None,
               openapi_extra=capability("Revoke an app key at once", "destructive", "records.keys",
                                        approval="human"))
async def revoke_key(key_id: UUID, request: Request, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_control_db)) -> Response:
    from src.schema_engine.models import ApiKey

    _admin(user)
    company_id, _ = await _location(request, user, db)
    engine, _ = await schema.business_engine(company_id)
    async with schema.session(engine) as tdb:
        row = await tdb.get(ApiKey, key_id)
        if row is None or row.company_id != company_id:
            raise HTTPException(status_code=404, detail="Key not found")
        row.revoked_at = row.revoked_at or datetime.utcnow()
        await tdb.commit()
    return Response(status_code=204)


class RecordsSettingsIn(BaseModel):
    agents_auto_approve_additive: Optional[bool] = Field(
        None, description="An agent's change that only adds (an object, an optional field, an index) applies "
                          "without a person; anything else an agent proposes still waits")
    scratch_retention_days: Optional[int] = Field(
        None, ge=1, le=30, description="Days scratch code is kept unless promoted (null: the platform's default)")
    public_api_access: Optional[bool] = Field(
        None, description="Keys made for the public (a website's form) work only while this is on")


@router.get("/api/v1/records/settings", openapi_extra=capability(
    "The owner's policy for changes to the business's data structure", "read", "records.settings"))
async def records_settings(request: Request, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    from src.schema_engine import approvals

    company_id, _ = await _location(request, user, db)
    engine, _ = await schema.business_engine(company_id)
    return await approvals.settings_for(engine, company_id)


@router.put("/api/v1/records/settings", openapi_extra=capability(
    "Change the owner's policy for changes to the business's data structure", "write_internal",
    "records.settings", approval="human"))
async def save_records_settings(body: RecordsSettingsIn, request: Request, user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    from src.schema_engine import approvals

    _admin(user)
    company_id, _ = await _location(request, user, db)
    engine, _ = await schema.business_engine(company_id)
    try:
        return await approvals.save_settings(engine, company_id, **body.model_dump(exclude_unset=True),
                                             updated_by=f"user:{user.id}")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None

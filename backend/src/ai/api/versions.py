"""Entity versions API — drafts, files, test runs and publishing (R2 §6.3, EP-10).

    GET    /ai/entities/{id}/versions                         every version, newest first
    POST   /ai/entities/{id}/versions                         a draft: base + changes
    GET    /ai/entities/{id}/versions/{vid}                   definition and file manifest
    GET    /ai/entities/{id}/versions/{vid}/assets/{path}     one file's body
    PUT    /ai/entities/{id}/versions/{vid}/assets/{path}     add or replace a draft's file
    DELETE /ai/entities/{id}/versions/{vid}/assets/{path}     remove a draft's file
    POST   /ai/entities/{id}/versions/{vid}/test-run          run the entity as that version
    POST   /ai/entities/{id}/versions/{vid}/publish           make it the head (admins; D13)

Reads follow the entity's visibility. Writes need the entity in the caller's
companies; a template only ``app_admin`` may change (PO-23). Published
versions are immutable: changing one is a 409. Each route works in the
acting company's database (``X-Company-Id``; Phase 14 WS2) — the template
library's is the platform company's.
"""
from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.governance.entity_assets import AssetRejected, VersionConflict, delete_asset, put_asset
from src.ai.governance.publication import PublicationRefused
from src.ai.schemas.execution import ExecutionRunCreate, ExecutionRunResponse
from src.ai.schemas.versions import (
    AssetBody,
    AssetInfo,
    AssetPut,
    EntityVersionDetail,
    EntityVersionSummary,
    VersionDraftCreate,
    VersionTestRun,
)
from src.ai.service import AIService
from src.ai.services import version_authoring as authoring
from src.auth.dependencies import RoleChecker, get_current_user
from src.auth.models import User
from src.auth.roles import ADMIN_ROLES, Role
from src.common.tenancy.session import get_acting_tenant_db

router = APIRouter(prefix="/ai/entities", tags=["Entity versions"])


def _refuse(exc: Exception) -> NoReturn:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, VersionConflict):
        raise HTTPException(status_code=409, detail=str(exc))
    raise HTTPException(status_code=422, detail=str(exc))


async def _entity(db: AsyncSession, entity_id: UUID, user: User, *, write: bool = False) -> Any:
    entity = await AIService(db).get_entity(entity_id, user.company_id, user.role)
    if write and entity.is_template and user.role != Role.APP_ADMIN:
        raise HTTPException(status_code=403, detail="Only a platform administrator changes a template")
    return entity


def _summary(version: Any, entity: Any, asset_count: int) -> dict[str, Any]:
    out = EntityVersionSummary.model_validate(version).model_dump()
    out.update(is_head=version.id == entity.active_version_id, asset_count=asset_count)
    return out


@router.get("/{entity_id}/versions", response_model=list[EntityVersionSummary])
async def list_versions(entity_id: UUID, db: AsyncSession = Depends(get_acting_tenant_db),
                        user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    entity = await _entity(db, entity_id, user)
    return [_summary(v, entity, n) for v, n in await authoring.list_versions(db, entity.id)]


@router.get("/{entity_id}/versions/{version_id}", response_model=EntityVersionDetail)
async def get_version(entity_id: UUID, version_id: UUID, db: AsyncSession = Depends(get_acting_tenant_db),
                      user: User = Depends(get_current_user)) -> dict[str, Any]:
    entity = await _entity(db, entity_id, user)
    try:
        version = await authoring.get_version(db, entity.id, version_id)
    except LookupError as exc:
        _refuse(exc)
    assets = await authoring.list_assets(db, version.id)
    return {**_summary(version, entity, len(assets)), "snapshot": version.snapshot,
            "assets": [AssetInfo.model_validate(a).model_dump() for a in assets]}


@router.post("/{entity_id}/versions", response_model=EntityVersionDetail, status_code=201)
async def create_draft(entity_id: UUID, body: VersionDraftCreate, db: AsyncSession = Depends(get_acting_tenant_db),
                       user: User = Depends(get_current_user)) -> dict[str, Any]:
    entity = await _entity(db, entity_id, user, write=True)
    try:
        async with db.begin_nested():  # a refusal undoes this request's writes only
            draft = await authoring.create_draft(
                db, entity, body.changes.model_dump(mode="json", exclude_unset=True),
                base_version_id=body.base_version_id, user_id=user.id,
            )
    except (LookupError, VersionConflict, authoring.NotAVersionField) as exc:
        _refuse(exc)
    await db.commit()
    return await get_version(entity_id, draft.id, db, user)


@router.get("/{entity_id}/versions/{version_id}/assets/{path:path}", response_model=AssetBody)
async def read_asset(entity_id: UUID, version_id: UUID, path: str, db: AsyncSession = Depends(get_acting_tenant_db),
                     user: User = Depends(get_current_user)) -> Any:
    entity = await _entity(db, entity_id, user)
    try:
        await authoring.get_version(db, entity.id, version_id)
        return await authoring.get_asset(db, version_id, path)
    except LookupError as exc:
        _refuse(exc)


@router.put("/{entity_id}/versions/{version_id}/assets/{path:path}", response_model=AssetInfo)
async def write_asset(entity_id: UUID, version_id: UUID, path: str, body: AssetPut,
                      db: AsyncSession = Depends(get_acting_tenant_db), user: User = Depends(get_current_user)) -> Any:
    entity = await _entity(db, entity_id, user, write=True)
    try:
        async with db.begin_nested():
            await authoring.get_version(db, entity.id, version_id)
            asset = await put_asset(db, version_id, path, body.body)
    except (LookupError, VersionConflict, AssetRejected) as exc:
        _refuse(exc)
    await db.commit()
    return asset


@router.delete("/{entity_id}/versions/{version_id}/assets/{path:path}", status_code=204, response_class=Response, response_model=None)
async def remove_asset(entity_id: UUID, version_id: UUID, path: str, db: AsyncSession = Depends(get_acting_tenant_db),
                       user: User = Depends(get_current_user)) -> None:
    entity = await _entity(db, entity_id, user, write=True)
    try:
        async with db.begin_nested():
            await authoring.get_version(db, entity.id, version_id)
            if not await delete_asset(db, version_id, path):
                raise LookupError(f"no asset {path!r} in version {version_id}")
    except (LookupError, VersionConflict) as exc:
        _refuse(exc)
    await db.commit()


@router.post("/{entity_id}/versions/{version_id}/test-run", response_model=ExecutionRunResponse)
async def test_run(entity_id: UUID, version_id: UUID, body: VersionTestRun, db: AsyncSession = Depends(get_acting_tenant_db),
                   user: User = Depends(get_current_user)) -> Any:
    entity = await _entity(db, entity_id, user, write=True)
    try:
        request = ExecutionRunCreate(entity_id=entity.id, input_data=body.input_data)
    except ValueError as exc:  # reserved run-input keys (P3.2)
        raise HTTPException(status_code=422, detail=str(exc))
    return await AIService(db).trigger_execution(
        request, user.company_id, user.id, user_role=user.role, entity_version_id=version_id,
    )


@router.post("/{entity_id}/versions/{version_id}/publish", response_model=EntityVersionDetail)
async def publish(entity_id: UUID, version_id: UUID, db: AsyncSession = Depends(get_acting_tenant_db),
                  user: User = Depends(RoleChecker(ADMIN_ROLES))) -> dict[str, Any]:
    entity = await _entity(db, entity_id, user, write=True)
    try:
        async with db.begin_nested():
            head = await authoring.publish(db, entity, version_id, user_id=user.id)
    except PublicationRefused as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc), "failed_checks": exc.failed})
    except (LookupError, VersionConflict, authoring.NotAVersionField) as exc:
        _refuse(exc)
    await db.commit()
    from src.voice.agent_cache_bus import announce_agent_changed
    await announce_agent_changed(entity.id, entity.company_id)  # the next call runs it (VT-16)
    return await get_version(entity_id, head.id, db, user)

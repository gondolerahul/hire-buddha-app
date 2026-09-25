"""
Campaign-creation helpers used by ``src/ai/campaign_router.py``:
contact uploads (.csv/.xlsx) and mobile_conference validation/assignment.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.mobile.contact_parser import PREVIEW_ROWS, ContactFileError, parse_contact_file, validate_contacts
from src.mobile.models import CampaignAssignee, ContactUpload
from src.mobile.service import MOBILE_ROLES

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_TTL = timedelta(hours=24)
CROSS_TENANT_ROLES = {"app_admin", "partner_admin"}


async def store_contact_upload(db: AsyncSession, user: User, file: UploadFile) -> Dict[str, Any]:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise ContactFileError("file_too_large", "File is larger than 10 MB")
    report = validate_contacts(parse_contact_file(file.filename or "", content))

    upload = ContactUpload(
        company_id=user.company_id,
        uploaded_by=user.id,
        filename=(file.filename or "contacts")[:255],
        file_type=report.file_type,
        total_rows=report.total_rows,
        valid_rows=report.valid_rows,
        invalid_rows=report.invalid_rows,
        duplicate_rows=report.duplicate_rows,
        columns=report.columns,
        phone_column=report.phone_column,
        valid_contacts=report.valid_contacts,
        errors=report.errors,
        expires_at=datetime.utcnow() + UPLOAD_TTL,
    )
    db.add(upload)
    await db.commit()
    logger.info(f"Stored contact upload {upload.id}: {report.valid_rows}/{report.total_rows} valid")
    return {
        "upload_id": str(upload.id),
        "file_type": report.file_type,
        "total_rows": report.total_rows,
        "valid_rows": report.valid_rows,
        "invalid_rows": report.invalid_rows,
        "duplicate_rows": report.duplicate_rows,
        "columns": report.columns,
        "phone_column": report.phone_column,
        "errors": report.errors,
        "preview": report.preview,
        "expires_at": upload.expires_at.isoformat() + "Z",
    }


async def recent_uploads(db: AsyncSession, user: User, limit: int = 5) -> List[Dict[str, Any]]:
    """This user's uploads that can still become a campaign: not used, not expired.

    Backs "Recent · Reuse" on the app's first create step. An upload is single-use and
    kept for a day, so this is the file a rep checked and backed out of, not history.
    """
    rows = (await db.execute(
        select(ContactUpload)
        .where(
            ContactUpload.uploaded_by == user.id,
            ContactUpload.company_id == user.company_id,
            ContactUpload.consumed_at.is_(None),
            ContactUpload.expires_at > datetime.utcnow(),
            ContactUpload.valid_rows > 0,
        )
        .order_by(ContactUpload.created_at.desc())
        .limit(limit)
    )).scalars().all()
    return [{
        "upload_id": str(u.id),
        "filename": u.filename,
        "created_at": u.created_at.isoformat() + "Z",
        "file_type": u.file_type,
        "total_rows": u.total_rows,
        "valid_rows": u.valid_rows,
        "invalid_rows": u.invalid_rows,
        "duplicate_rows": u.duplicate_rows,
        "columns": u.columns or [],
        "phone_column": u.phone_column,
        "errors": u.errors or [],
        "preview": (u.valid_contacts or [])[:PREVIEW_ROWS],
        "expires_at": u.expires_at.isoformat() + "Z",
    } for u in rows]


async def prepare_campaign_contacts(
    db: AsyncSession,
    user: User,
    company_id: UUID,
    contact_list: Optional[List[Dict[str, Any]]],
    contact_upload_id: Optional[UUID],
) -> Tuple[List[Dict[str, Any]], Optional[ContactUpload]]:
    if contact_upload_id:
        upload = await db.get(ContactUpload, contact_upload_id)
        allowed = upload is not None and (
            upload.company_id == company_id
            or (user.role in CROSS_TENANT_ROLES and upload.uploaded_by == user.id)
        )
        if not allowed:
            raise HTTPException(status_code=404, detail={"code": "upload_not_found", "message": "Contact upload not found"})
        if upload.consumed_at is not None:
            raise HTTPException(status_code=409, detail={"code": "upload_already_used",
                                                         "message": "This upload was already used for a campaign"})
        if upload.expires_at < datetime.utcnow():
            raise HTTPException(status_code=410, detail={"code": "upload_expired",
                                                         "message": "This upload has expired; upload the file again"})
        if not upload.valid_contacts:
            raise HTTPException(status_code=422, detail={"code": "no_valid_contacts",
                                                         "message": "The upload has no valid contacts"})
        return list(upload.valid_contacts), upload
    if contact_list:
        return contact_list, None
    raise HTTPException(status_code=422, detail={"code": "contacts_required",
                                                 "message": "Provide contact_upload_id or contact_list"})


async def validate_mobile_campaign(
    db: AsyncSession,
    user: User,
    agent,
    assignee_user_ids: Optional[List[UUID]],
) -> Tuple[str, List[UUID]]:
    """Returns (provider of the agent's DID, assignee ids)."""
    from src.voice.phone_pool_models import PhoneNumber

    if user.role not in CROSS_TENANT_ROLES and agent.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.status != "ACTIVE":
        raise HTTPException(status_code=409, detail={"code": "agent_not_active", "message": "The agent is not ACTIVE"})

    numbers = (await db.execute(
        select(PhoneNumber).where(
            PhoneNumber.agent_id == agent.id,
            PhoneNumber.status == "assigned",
            PhoneNumber.is_active == True,  # noqa: E712
        )
    )).scalars().all()
    if not numbers:
        raise HTTPException(status_code=409, detail={
            "code": "agent_has_no_did",
            "message": "Assign a phone number to this agent before creating a mobile campaign",
        })
    provider = next((n.provider for n in numbers if n.provider == "tata_tele"), numbers[0].provider)

    requested = list(dict.fromkeys(assignee_user_ids or []))
    if user.role == "tenant_user":
        if requested and requested != [user.id]:
            raise HTTPException(status_code=403, detail={"code": "admin_only",
                                                         "message": "Only tenant admins can assign other reps"})
        return provider, [user.id]
    if not requested:
        if user.role in MOBILE_ROLES and user.company_id == agent.company_id:
            return provider, [user.id]
        raise HTTPException(status_code=422, detail={"code": "assignees_required",
                                                     "message": "Assign at least one rep"})

    reps = (await db.execute(
        select(User.id).where(
            User.id.in_(requested),
            User.company_id == agent.company_id,
            User.is_active == True,  # noqa: E712
            User.role.in_(MOBILE_ROLES),
        )
    )).scalars().all()
    missing = set(requested) - set(reps)
    if missing:
        raise HTTPException(status_code=422, detail={
            "code": "invalid_assignees",
            "message": f"{len(missing)} assignee(s) are not active tenant users of this company",
        })
    return provider, requested


async def finalize_mobile_campaign(db: AsyncSession, campaign, assignee_ids: List[UUID],
                                   upload: Optional[ContactUpload]) -> None:
    for uid in assignee_ids:
        db.add(CampaignAssignee(campaign_id=campaign.id, user_id=uid))
    if upload is not None:
        upload.consumed_at = datetime.utcnow()
    await db.commit()

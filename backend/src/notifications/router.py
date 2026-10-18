"""``/api/v1/notifications``: a person's own notifications (Phase 14 WS3 3.11)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.automation.api import capability
from src.common.tenancy.session import get_control_db
from src.notifications.models import Notification

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    severity: str
    title: str
    body: Optional[str] = None
    link: Optional[str] = None
    created_at: datetime
    read_at: Optional[datetime] = None


class NotificationList(BaseModel):
    unread: int
    items: List[NotificationOut]


@router.get("", response_model=NotificationList,
            openapi_extra=capability("Your notifications, newest first, with how many are unread", "read",
                                     "notifications.read"))
async def my_notifications(unread_only: bool = False, limit: int = Query(30, ge=1, le=200),
                           user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_control_db)) -> NotificationList:
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    rows = (await db.execute(query.order_by(Notification.created_at.desc()).limit(limit))).scalars().all()
    unread = (await db.execute(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)))).scalar() or 0
    return NotificationList(unread=unread, items=[NotificationOut.model_validate(r) for r in rows])


@router.post("/{notification_id}/read", response_model=NotificationOut,
             openapi_extra=capability("Mark one of your notifications read", "write_internal", "notifications.read"))
async def mark_read(notification_id: UUID, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_control_db)) -> NotificationOut:
    row = await db.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    if row.read_at is None:
        row.read_at = datetime.utcnow()
        await db.commit()
    return NotificationOut.model_validate(row)


@router.post("/read-all", response_model=NotificationList,
             openapi_extra=capability("Mark all your notifications read", "write_internal", "notifications.read"))
async def mark_all_read(user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_control_db)) -> NotificationList:
    await db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
                     .values(read_at=datetime.utcnow()))
    await db.commit()
    return await my_notifications(unread_only=False, limit=30, user=user, db=db)

"""The business's conversations screen (META-E4, META-E5).

* ``GET  /api/v1/conversations``                — conversations, those a person has first
* ``POST /api/v1/conversations/{id}/hand-back`` — the team is done: the assistant answers again
* ``GET  /api/v1/whatsapp/opt-ins``             — who agreed to (or refused) messages the business starts
* ``POST /api/v1/whatsapp/opt-ins``             — record one, with where it came from
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.common.tenancy.session import get_tenant_db
from src.messaging import rules
from src.messaging.models import MessagingConversation, MessagingOptIn

router = APIRouter(tags=["Conversations"])

_TEAM = ("tenant_admin", "tenant_user")


def _team(user: User) -> None:
    if str(user.role) not in _TEAM:
        raise HTTPException(status_code=403, detail="Only the business's own team handles its conversations")


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _conversation_view(c: MessagingConversation) -> Dict[str, Any]:
    return {"id": str(c.id), "channel": c.channel, "account_id": c.account_id, "contact_id": c.contact_id,
            "with_person": c.handed_off_at is not None, "handed_off_at": _iso(c.handed_off_at),
            "handoff_reason": c.handoff_reason, "handed_back_at": _iso(c.handed_back_at),
            "last_inbound_at": _iso(c.last_inbound_at), "last_ai_at": _iso(c.last_ai_at)}


@router.get("/api/v1/conversations")
async def conversations(with_person: bool = Query(False, description="Only those a person has taken over"),
                        db: AsyncSession = Depends(get_tenant_db), current_user: User = Depends(get_current_user)):
    _team(current_user)
    query = select(MessagingConversation).where(MessagingConversation.company_id == current_user.company_id)
    if with_person:
        query = query.where(MessagingConversation.handed_off_at.is_not(None))
    rows = (await db.execute(query.order_by(MessagingConversation.handed_off_at.desc().nulls_last(),
                                            MessagingConversation.updated_at.desc()).limit(200))).scalars().all()
    return {"conversations": [_conversation_view(c) for c in rows]}


@router.post("/api/v1/conversations/{conversation_id}/hand-back")
async def hand_back(conversation_id: UUID, db: AsyncSession = Depends(get_tenant_db),
                    current_user: User = Depends(get_current_user)):
    """The AI assistant answers the customer again; its next reply says first that it is an AI."""
    _team(current_user)
    conversation = await rules.hand_back(db, current_user.company_id, conversation_id, current_user.id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="No such conversation")
    await db.commit()
    return _conversation_view(conversation)


class OptInRequest(BaseModel):
    contact: str = Field(..., min_length=6, max_length=32, description="The customer's WhatsApp number")
    status: str = Field(..., pattern="^(in|out)$")
    source: str = Field(..., min_length=2, max_length=60,
                        description="Where it came from: website form, checkout, in person, import …")
    evidence: Optional[str] = Field(None, max_length=500, description="What shows it (a form id, a quote, a date)")


@router.get("/api/v1/whatsapp/opt-ins")
async def opt_ins(contact: Optional[str] = None, db: AsyncSession = Depends(get_tenant_db),
                  current_user: User = Depends(get_current_user)):
    _team(current_user)
    query = select(MessagingOptIn).where(MessagingOptIn.company_id == current_user.company_id,
                                         MessagingOptIn.channel == "whatsapp")
    if contact:
        query = query.where(MessagingOptIn.contact_id == rules.normal_number(contact))
    rows = (await db.execute(query.order_by(MessagingOptIn.recorded_at.desc()).limit(500))).scalars().all()
    return {"opt_ins": [{"contact": o.contact_id, "status": o.status, "source": o.source, "evidence": o.evidence,
                         "recorded_by": o.recorded_by, "recorded_at": _iso(o.recorded_at)} for o in rows]}


@router.post("/api/v1/whatsapp/opt-ins", status_code=201)
async def record_opt_in(body: OptInRequest, db: AsyncSession = Depends(get_tenant_db),
                        current_user: User = Depends(get_current_user)):
    """A customer agreed to (or refused) WhatsApp messages the business starts: templates need ``in``."""
    _team(current_user)
    if len(rules.normal_number(body.contact)) < 6:
        raise HTTPException(status_code=422, detail="contact is a phone number with its country code")
    await rules.record_opt(db, current_user.company_id, body.contact, body.status, source=body.source.strip(),
                           evidence=(body.evidence or "").strip() or None, by=f"user:{current_user.id}")
    await db.commit()
    return {"contact": rules.normal_number(body.contact), "status": body.status}

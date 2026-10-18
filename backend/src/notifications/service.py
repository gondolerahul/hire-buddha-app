"""Telling the people of a business (functional spec §3.6).

``notify`` writes one in-app notification per recipient — the business's
owners and admins, or for operational items its operators too — and e-mails
each through the platform's mail integration (``smtp-system``; without one
the notification is still in the app). A ``dedupe_key`` seen before for a
person is not sent again. Sending never fails the caller: a notification is
best effort, the event log and the Control Room keep the facts.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Any, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.notifications.models import Notification

logger = logging.getLogger(__name__)

ADMINS = ("tenant_admin", "partner_admin", "app_admin")
OPERATORS = ADMINS + ("tenant_user", "partner_user", "app_user")
AUDIENCES = {"admins": ADMINS, "operators": OPERATORS}


async def recipients(db: Any, company_id: Any, audience: str) -> List[Any]:
    """The business's active, verified people of the audience's roles."""
    from src.auth.models import User

    roles: Sequence[str] = AUDIENCES[audience]
    return list((await db.execute(select(User).where(
        User.company_id == company_id, User.is_active.is_(True), User.role.in_(roles)))).scalars().all())


def _email_body(title: str, body: Optional[str], link: Optional[str]) -> str:
    from src.common.config import settings

    url = f"{settings.FRONTEND_URL.rstrip('/')}{link}" if link else None
    return (f"<html><body><h2>{html.escape(title)}</h2>"
            + (f"<p>{html.escape(body)}</p>" if body else "")
            + (f'<p><a href="{html.escape(url)}">Open in HireBuddha</a></p>' if url else "")
            + "<p style='color:#888'>You receive this because you run this business on HireBuddha.</p>"
            + "</body></html>")


async def notify(company_id: Any, *, kind: str, title: str, dedupe_key: str, body: Optional[str] = None,
                 link: Optional[str] = None, audience: str = "admins", severity: str = "warning",
                 email: bool = True) -> int:
    """Tell the business's people; returns how many were told (new rows). Never raises."""
    from src.common.email import email_service
    from src.common.tenancy.session import control_session

    try:
        async with control_session() as db:
            people = await recipients(db, company_id, audience)
            told = []
            for person in people:
                row_id = (await db.execute(
                    insert(Notification).values(company_id=company_id, user_id=person.id, kind=kind,
                                                severity=severity, title=title[:300], body=body, link=link,
                                                dedupe_key=dedupe_key[:300], created_at=datetime.utcnow())
                    .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
                    .returning(Notification.id))).scalar()
                if row_id is not None:
                    told.append((row_id, person.email))
            await db.commit()
            if email:
                for row_id, address in told:
                    if not address:
                        continue
                    try:
                        sent = await email_service.async_send_email(address, f"HireBuddha: {title}",
                                                                    _email_body(title, body, link))
                    except Exception:  # noqa: BLE001 - the in-app notification stands
                        sent = False
                    if sent:
                        row = await db.get(Notification, row_id)
                        row.emailed_at = datetime.utcnow()
                if told:
                    await db.commit()
            return len(told)
    except Exception:
        logger.exception("notification %s for company %s not recorded", kind, company_id)
        return 0

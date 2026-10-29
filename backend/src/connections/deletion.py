"""A provider's request to delete a person's data (META-E1, META-07).

Meta calls two URLs of HireBuddha's Meta app with a ``signed_request``
(``<signature>.<payload>``: an HMAC-SHA256 of the payload under the app secret):

* **Deauthorise** (``/webhook/provider/meta/deauthorize``): the person removed
  HireBuddha from their Facebook account. The connections they made — Pages,
  Instagram accounts, WhatsApp numbers — are disconnected.
* **Data deletion** (``/webhook/provider/meta/data-deletion``): the person asks
  for their data to be deleted. The same connections are disconnected, which
  deletes their tokens and routes and the events stored from them (SH-E1); the
  answer is a confirmation code and the URL of a public page that says, in
  plain words, what was done.

The connections are found by the app-scoped user id recorded when they were
made (``settings.meta_user_id``), across every business's database. The
request is kept (``provider_deletion_requests``) with the person's id hashed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

META_CONNECTORS = ("facebook_pages", "instagram_business", "whatsapp_business")


class BadSignedRequest(ValueError):
    """Not a signed request from HireBuddha's Meta app."""


def _b64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def parse_signed_request(signed_request: Any, app_secret: str) -> Dict[str, Any]:
    """The payload of Meta's ``signed_request``, its signature checked."""
    if not app_secret:
        raise BadSignedRequest("the Meta app has no secret")
    try:
        signature, payload = str(signed_request or "").split(".", 1)
        expected = hmac.new(app_secret.encode(), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(signature), expected):
            raise BadSignedRequest("the signature does not match")
        data = json.loads(_b64url(payload))
    except (ValueError, TypeError) as error:
        raise BadSignedRequest(str(error)) from None
    if not isinstance(data, dict) or str(data.get("algorithm", "")).upper() != "HMAC-SHA256" \
            or not data.get("user_id"):
        raise BadSignedRequest("not a person's signed request")
    return data


async def person_connections(person: str) -> List[Tuple[Any, Any]]:
    """``(company_id, connection_id)`` of every live Meta connection the person made."""
    from sqlalchemy import select

    from src.common.tenancy.session import tenant_scopes, tenant_session
    from src.connections.models import Connection

    found: List[Tuple[Any, Any]] = []
    for scope in await tenant_scopes():
        async with tenant_session(scope) as db:
            rows = (await db.execute(select(Connection.company_id, Connection.id).where(
                Connection.connector_id.in_(META_CONNECTORS), Connection.status != "revoked",
                Connection.settings["meta_user_id"].astext == person))).all()
        found.extend((row[0], row[1]) for row in rows)
    return found


async def disconnect_person(person: str, *, reason: str) -> int:
    """Disconnect what the person connected; returns how many connections."""
    from src.connections import service

    done = 0
    for company_id, connection_id in await person_connections(person):
        try:
            await service.revoke(company_id, connection_id, actor_kind="provider", reason=reason)
            done += 1
        except service.NoSuchConnection:
            continue
        except Exception:  # noqa: BLE001 - one business's failure does not stop the others
            logger.exception("connection %s not disconnected for a Meta %s", connection_id, reason)
    return done


async def delete_person(provider: str, person: str) -> Tuple[str, int]:
    """Meta's data deletion request: disconnect and delete, keep the request; ``(code, connections)``."""
    from src.common.tenancy.session import control_session
    from src.connections.models import ProviderDeletionRequest

    count = await disconnect_person(person, reason="data_deletion_request")
    code = f"HB{secrets.token_hex(6).upper()}"
    now = datetime.utcnow()
    async with control_session() as db:
        db.add(ProviderDeletionRequest(code=code, provider=provider,
                                       person_sha256=hashlib.sha256(person.encode()).hexdigest(),
                                       status="completed" if count else "nothing_found", connections=count,
                                       completed_at=now, detail={"connectors": list(META_CONNECTORS)}))
        await db.commit()
    return code, count


def status_url(code: str) -> str:
    from src.common.config import settings
    from src.voice.public_urls import callback_url

    base = settings.CONNECTIONS_PUBLIC_URL.rstrip("/") if settings.CONNECTIONS_PUBLIC_URL else callback_url("")
    return f"{base.rstrip('/')}/webhook/provider/meta/data-deletion/{code}"


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>HireBuddha data deletion request</title>
<style>body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:40rem;margin:2rem auto;
padding:0 1rem;line-height:1.55;color:#1f2328;background:#fff}}code{{font-size:1.05em}}</style></head>
<body><h1>Data deletion request</h1>{body}
<p>How HireBuddha deletes data: <a href="{policy}">{policy}</a>. Questions: {contact}.</p></body></html>"""


async def status_page(code: str) -> Tuple[int, str]:
    """``(HTTP status, HTML)`` of the public status page for a confirmation code."""
    from src.common.config import settings
    from src.common.tenancy.session import control_session
    from src.connections.models import ProviderDeletionRequest

    async with control_session() as db:
        row = await db.get(ProviderDeletionRequest, str(code))
    links = {"policy": html.escape(settings.DATA_DELETION_URL), "contact": html.escape(settings.PRIVACY_CONTACT_EMAIL)}
    if row is None:
        return 404, _PAGE.format(body="<p>HireBuddha has no deletion request with this confirmation code.</p>",
                                 **links)
    received = row.received_at.strftime("%d %B %Y, %H:%M UTC") if row.received_at else ""
    if row.status == "completed":
        done = (f"<p><strong>Done.</strong> HireBuddha disconnected the {row.connections} Facebook Page, Instagram "
                "or WhatsApp connection(s) made with your Facebook account, deleted their access tokens, and "
                "deleted the messages, comments and other events it had stored from them. Copies in HireBuddha's "
                "encrypted backups are erased as those backups expire, as its privacy policy describes.</p>")
    else:
        done = ("<p><strong>Nothing to delete.</strong> HireBuddha holds no connection made with your Facebook "
                "account.</p>")
    body = (f"<p>Confirmation code: <code>{html.escape(row.code)}</code></p>"
            f"<p>Received from Meta: {html.escape(received)}</p>{done}")
    return 200, _PAGE.format(body=body, **links)

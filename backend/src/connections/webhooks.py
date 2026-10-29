"""App-level provider webhooks (Phase 14 WS5 5.5, tech spec §10.6; E09-S10).

    GET  /webhook/provider/meta       Meta's subscription check (hub.challenge)
    POST /webhook/provider/meta       Pages, Instagram and WhatsApp deliveries
    POST /webhook/provider/github     GitHub App deliveries

Providers sign these with HireBuddha's own app secret (Meta: the app secret;
GitHub: the App's webhook secret), so one endpoint serves every business. Each
delivery names the outside account (a Page, an Instagram account, a WhatsApp
number, a GitHub installation); ``external_account_routes`` says which
business owns it, and the delivery becomes an event in that business's
database (the event types of tech spec Appendix B: ``social.comment.created``,
``social.message.received``, ``whatsapp.message.received``,
``github.pull_request.merged`` …; subject ``connection:<id>``),
routed by its triggers. A delivery for an account no business has connected
is recorded in ``unrouted_events`` (its payload's hash only) for staff, and
acknowledged so the provider does not retry.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import delete, select

from src.connections.models import Connection, ExternalAccountRoute, UnroutedEvent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Provider webhooks"])

UNROUTED_KEEP_DAYS = 7
MAX_DATA_BYTES = 200 * 1024


async def _app(ref: str) -> Any:
    from src.common.tenancy.session import control_session
    from src.connections.apps import provider_app

    async with control_session() as db:
        return await provider_app(db, ref)


def _signed(secret: Optional[str], body: bytes, header: Optional[str]) -> bool:
    if not secret or not header:
        return False
    from src.gateway.webhook_signatures import SignedRequest, verify_signature

    return verify_signature("github", secret, SignedRequest(headers={"x-hub-signature-256": header}, body=body))


async def _route(provider: str, account_id: str) -> Optional[ExternalAccountRoute]:
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        return await db.get(ExternalAccountRoute, (provider, account_id))


async def _unrouted(provider: str, account_id: Optional[str], event_type: Optional[str], body: bytes) -> None:
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        db.add(UnroutedEvent(provider=provider, external_account_id=account_id, event_type=event_type,
                             payload_sha256=hashlib.sha256(body).hexdigest(), payload_bytes=len(body)))
        await db.commit()


async def _deliver(route: ExternalAccountRoute, event_type: str, dedupe_key: str, data: Dict[str, Any]) -> bool:
    """Store the event in the owning business's database and nudge its router."""
    from src.automation import store
    from src.automation.events import Envelope
    from src.common.tenancy.session import tenant_session

    body = json.dumps(data, default=str)
    if len(body) > MAX_DATA_BYTES:
        data = {k: data[k] for k in ("connection_id", "account_id", "field", "action") if k in data}
        data["too_large_bytes"] = len(body)
    async with tenant_session(route.company_id) as db:
        connection = await db.get(Connection, route.connection_id)
        if connection is None or connection.status == "revoked":
            return False
        row, created = await store.record(db, route.company_id, Envelope(
            type=event_type, source=f"provider:{route.provider}", trust="verified",
            dedupe_key=dedupe_key[:512], subject=f"connection:{connection.id}",
            data={**data, "connection_id": str(connection.id), "connector_id": connection.connector_id}))
        await db.commit()
    if created:
        await store.nudge(route.company_id, row.id)
    return True


def _slug(text: Any) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in str(text or "").lower()).strip("_")
    return cleaned[:60] or "unknown"


# ── Meta ────────────────────────────────────────────────────────────────────

_VERBS = {"add": "created", "edited": "updated", "edit": "updated", "remove": "deleted", "hide": "hidden"}


def _social_type(platform: str, field: str, value: Dict[str, Any]) -> str:
    """Appendix B's names: ``social.comment.created``, ``social.mention.created`` …"""
    if platform == "instagram":
        item = {"comments": "comment", "mentions": "mention", "live_comments": "comment",
                "story_insights": "story"}.get(field, field)
        return f"social.{_slug(item)}.created" if item in ("comment", "mention") else f"social.{_slug(item)}.updated"
    if field == "mention":
        return "social.mention.created"
    item = _slug(value.get("item") or field)
    verb = _VERBS.get(str(value.get("verb") or "add"), _slug(value.get("verb")))
    return f"social.{item}.{verb}"


def meta_deliveries(payload: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
    """``(account id, event type, data)`` for each item in a Meta delivery (Appendix B):
    Page and Instagram comments, mentions and posts → ``social.<item>.<verb>``;
    Messenger / Instagram messages → ``social.message.received``; WhatsApp
    messages and statuses → ``whatsapp.message.received`` / ``whatsapp.status.updated``.
    ``data.platform`` says which (``facebook``, ``instagram``, ``whatsapp``)."""
    platform = {"page": "facebook", "instagram": "instagram",
                "whatsapp_business_account": "whatsapp"}.get(payload.get("object"))
    if platform is None:
        return []
    out: List[Tuple[str, str, Dict[str, Any]]] = []
    for entry in payload.get("entry", []) or []:
        account = str(entry.get("id") or "")
        base = {"platform": platform, "time": entry.get("time")}
        for change in entry.get("changes", []) or []:
            field = _slug(change.get("field"))
            value = change.get("value") or {}
            if platform == "whatsapp":  # a WhatsApp number is the account, not the WABA
                target = str((value.get("metadata") or {}).get("phone_number_id") or account)
                for message in value.get("messages", []) or []:
                    out.append((target, "whatsapp.message.received",
                                {**base, "account_id": target, "field": field, "message": message,
                                 "contacts": value.get("contacts", [])}))
                for status in value.get("statuses", []) or []:
                    out.append((target, "whatsapp.status.updated",
                                {**base, "account_id": target, "field": field, "status": status}))
                continue
            if field == "messages" and platform == "instagram":
                out.append((account, "social.message.received", {**base, "account_id": account, "field": field,
                                                                 "value": value}))
                continue
            out.append((account, _social_type(platform, field, value),
                        {**base, "account_id": account, "field": field, "value": value}))
        for message in entry.get("messaging", []) or []:  # Messenger / Instagram DMs
            out.append((account, "social.message.received", {**base, "account_id": account, "field": "messages",
                                                             "value": message}))
    return out


def github_event_type(event: str, payload: Dict[str, Any]) -> str:
    """Appendix B's names: ``github.pull_request.opened|merged|closed``,
    ``github.issue.opened``, ``github.check.completed``, ``github.push`` …"""
    action = _slug(payload.get("action")) if payload.get("action") else None
    if event == "pull_request" and action == "closed":
        return "github.pull_request." + ("merged" if (payload.get("pull_request") or {}).get("merged") else "closed")
    if event in ("issues", "issue_comment"):
        return f"github.{'issue' if event == 'issues' else 'issue_comment'}.{action or 'updated'}"
    if event in ("check_suite", "check_run"):
        return f"github.check.{action or 'updated'}"
    if event in ("push", "create", "delete", "release", "installation", "installation_repositories"):
        return f"github.{event}" + (f".{action}" if action and event.startswith("installation") else "")
    return f"github.{event}" + (f".{action}" if action else "")


@router.get("/webhook/provider/meta", include_in_schema=False)
async def meta_verify(request: Request):
    params = request.query_params
    try:
        app = await _app("oauth-app-meta")
    except Exception:  # noqa: BLE001
        return PlainTextResponse("not configured", status_code=404)
    expected = app.secret("verify_token")
    if params.get("hub.mode") == "subscribe" and expected and params.get("hub.verify_token") == expected:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("forbidden", status_code=403)


@router.post("/webhook/provider/meta")
async def meta_webhook(request: Request):
    body = await request.body()
    try:
        app = await _app("oauth-app-meta")
    except Exception:  # noqa: BLE001
        return JSONResponse({"status": "not_configured"}, status_code=404)
    if not _signed(app.client_secret, body, request.headers.get("x-hub-signature-256")):
        return JSONResponse({"status": "invalid_signature"}, status_code=401)
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return JSONResponse({"status": "bad_payload"}, status_code=400)
    delivered = unrouted = 0
    for account_id, event_type, data in meta_deliveries(payload):
        dedupe = "meta:" + hashlib.sha256(json.dumps([account_id, event_type, data], sort_keys=True,
                                                     default=str).encode()).hexdigest()
        route = await _route("meta", account_id)
        if route is None or not await _deliver(route, event_type, dedupe, data):
            await _unrouted("meta", account_id, event_type, body)
            unrouted += 1
        else:
            delivered += 1
    return {"status": "ok", "delivered": delivered, "unrouted": unrouted}


async def _meta_person(request: Request) -> Any:
    """The person a Meta callback names, from its verified ``signed_request``,
    or the response to send instead."""
    from src.connections.deletion import BadSignedRequest, parse_signed_request

    try:
        app = await _app("oauth-app-meta")
    except Exception:  # noqa: BLE001
        return JSONResponse({"status": "not_configured"}, status_code=404)
    form = await request.form()
    try:
        return str(parse_signed_request(form.get("signed_request"), app.client_secret or "")["user_id"])
    except BadSignedRequest:
        return JSONResponse({"status": "invalid_signed_request"}, status_code=400)


@router.post("/webhook/provider/meta/deauthorize")
async def meta_deauthorize(request: Request):
    """The person removed HireBuddha from their Facebook account (META-E1): their connections end."""
    from src.connections.deletion import disconnect_person

    person = await _meta_person(request)
    if not isinstance(person, str):
        return person
    return {"status": "ok", "disconnected": await disconnect_person(person, reason="deauthorized")}


@router.post("/webhook/provider/meta/data-deletion")
async def meta_data_deletion(request: Request):
    """Meta's data deletion request callback (META-E1, META-07): the person's
    connections are disconnected and their data deleted; Meta shows the person
    the code and the status page."""
    from src.connections.deletion import delete_person, status_url

    person = await _meta_person(request)
    if not isinstance(person, str):
        return person
    code, _ = await delete_person("meta", person)
    return {"url": status_url(code), "confirmation_code": code}


@router.get("/webhook/provider/meta/data-deletion/{code}", include_in_schema=False)
async def meta_data_deletion_status(code: str):
    """The public page behind a confirmation code: what was deleted, in plain words."""
    from fastapi.responses import HTMLResponse

    from src.connections.deletion import status_page

    status, page = await status_page(code)
    return HTMLResponse(page, status_code=status)


# ── GitHub ──────────────────────────────────────────────────────────────────

@router.post("/webhook/provider/github")
async def github_webhook(request: Request):
    body = await request.body()
    try:
        app = await _app("oauth-app-github")
    except Exception:  # noqa: BLE001
        return JSONResponse({"status": "not_configured"}, status_code=404)
    if not _signed(app.secret("webhook_secret"), body, request.headers.get("x-hub-signature-256")):
        return JSONResponse({"status": "invalid_signature"}, status_code=401)
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return JSONResponse({"status": "bad_payload"}, status_code=400)
    event = _slug(request.headers.get("x-github-event"))
    installation = str((payload.get("installation") or {}).get("id") or "")
    delivery = request.headers.get("x-github-delivery") or hashlib.sha256(body).hexdigest()
    route = await _route("github", installation) if installation else None
    if route is None:
        await _unrouted("github", installation or None, f"github.{event}", body)
        return {"status": "unrouted"}
    if event == "installation" and payload.get("action") == "deleted":
        await _installation_removed(route)
    elif event == "installation" and payload.get("action") in ("suspend", "unsuspend"):
        await _installation_suspended(route, payload["action"] == "suspend")
    elif event == "installation_repositories":
        await _repositories_changed(route, payload)
    data = {"account_id": installation, "action": payload.get("action"),
            "repository": (payload.get("repository") or {}).get("full_name"),
            "sender": (payload.get("sender") or {}).get("login"), "payload": payload}
    delivered = await _deliver(route, github_event_type(event, payload), f"github:{delivery}", data)
    if delivered and event == "pull_request":
        try:  # a review merged or closed in GitHub (WS6 code lanes)
            from src.code_lanes.github import sync_from_webhook

            await sync_from_webhook(route.company_id, event, payload)
        except Exception:  # noqa: BLE001 - the event is stored; the review catches up on approval
            logger.warning("code review not synced from GitHub", exc_info=True)
    return {"status": "ok" if delivered else "unrouted"}


async def _installation_removed(route: ExternalAccountRoute) -> None:
    """The App was uninstalled at GitHub: the connection is gone."""
    from src.common.tenancy.session import control_session, tenant_session

    async with tenant_session(route.company_id) as db:
        connection = await db.get(Connection, route.connection_id)
        if connection is not None:
            connection.status = "revoked"
            connection.health = {**(connection.health or {}), "last_error": "the GitHub App was uninstalled"}
            await db.commit()
    async with control_session() as db:
        await db.execute(delete(ExternalAccountRoute).where(ExternalAccountRoute.connection_id == route.connection_id))
        await db.commit()


async def _installation_suspended(route: ExternalAccountRoute, suspended: bool) -> None:
    """The account suspended the App, or lifted the suspension (GH-E1). While
    suspended the connection issues no token, so agents stop with a reason
    instead of failing on every call."""
    from src.common.tenancy.session import tenant_session
    from src.connections.models import ConnectionAudit

    async with tenant_session(route.company_id) as db:
        connection = await db.get(Connection, route.connection_id)
        if connection is None or connection.status == "revoked":
            return
        health = dict(connection.health or {})
        if suspended:
            connection.status = "error"
            health.update(suspended_at=datetime.utcnow().isoformat(),
                          last_error="the account suspended HireBuddha's GitHub App")
        elif health.pop("suspended_at", None) is not None:  # only a suspension this hook recorded is lifted
            connection.status = "active"
            health["last_error"] = None
        connection.health = health
        db.add(ConnectionAudit(company_id=route.company_id, connection_id=connection.id,
                               action="suspended" if suspended else "unsuspended", actor_kind="system"))
        await db.commit()


async def _repositories_changed(route: ExternalAccountRoute, payload: Dict[str, Any]) -> None:
    """Repositories taken from (or given back to) the installation (GH-E1): the
    connection's ``repositories_removed`` says which, and code lanes name them
    when GitHub refuses a call on one."""
    from src.common.tenancy.session import tenant_session
    from src.connections.models import ConnectionAudit

    removed = [r["full_name"] for r in payload.get("repositories_removed") or [] if r.get("full_name")]
    added = {r["full_name"] for r in payload.get("repositories_added") or [] if r.get("full_name")}
    if not removed and not added:
        return
    async with tenant_session(route.company_id) as db:
        connection = await db.get(Connection, route.connection_id)
        if connection is None:
            return
        settings = dict(connection.settings or {})
        gone = [name for name in settings.get("repositories_removed") or [] if name not in added]
        gone += [name for name in removed if name not in gone]
        settings["repositories_removed"] = gone
        if payload.get("repository_selection"):
            settings["repository_selection"] = payload["repository_selection"]
        connection.settings = settings
        if removed:
            db.add(ConnectionAudit(company_id=route.company_id, connection_id=connection.id,
                                   action="repositories_removed", actor_kind="system",
                                   detail={"repositories": removed}))
        await db.commit()


async def prune_unrouted(now: Optional[datetime] = None) -> int:
    """Forget unrouted deliveries after ``UNROUTED_KEEP_DAYS`` (event worker cron)."""
    from src.common.tenancy.session import control_session

    cutoff = (now or datetime.utcnow()) - timedelta(days=UNROUTED_KEEP_DAYS)
    async with control_session() as db:
        result = await db.execute(delete(UnroutedEvent).where(UnroutedEvent.received_at < cutoff))
        await db.commit()
    return result.rowcount or 0

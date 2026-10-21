"""The Connection Service (Phase 14 WS5 5.3, tech spec §10.5; functional spec §6).

The connect flow:

1. ``start`` — the browser is sent to the provider (OAuth 2.0 with PKCE, the
   GitHub App installation), handed Embedded Signup parameters (WhatsApp) or
   a form (mailbox, API key, MCP). OAuth state lives 10 minutes in Redis
   (``oauth:state:<state>``) with the PKCE verifier sealed under the
   business's DEK.
2. ``callback`` — the provider returns; the code is exchanged, the accounts
   the person may choose are listed and kept 10 minutes as a **pending
   result** (``oauth:pending:<id>``, their tokens sealed) while the browser
   goes to the "choose accounts" step.
3. ``finalize`` — the chosen accounts become connections: the secret sealed
   (``connection_secrets``), who may use it (``connection_grants``), the
   account's route (``external_account_routes``: one business per account —
   another business's account is refused with a neutral message), the
   provider's webhook subscription, a test call and ``connection.connected``.

Afterwards: ``test``, ``set_grants``, ``impact`` (what depends on it),
``revoke`` (at the provider; the secret deleted; routes removed; dependent
triggers paused; ``connection.revoked``), and the **token broker**
``issue_token`` — the only way a tool or app gets a credential: the grant is
checked, the token refreshed first when it is about to expire, and every
issue audited. ``refresh_due`` (the event worker's cron) refreshes tokens
before they expire, warns owners of expiries that cannot be refreshed, and on
failure marks the connection ``needs_reconnect``, pauses its triggers and
emits ``connection.needs_reconnect``.

Secrets never leave this module except in an ``AccessToken`` handed to the
caller that asked; they are not logged, traced or put in events.
"""
from __future__ import annotations

import base64
import json
import logging
import secrets as pysecrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urlencode

from sqlalchemy import Text, cast, delete, or_, select, update

from src.connections import crypto
from src.connections.catalog import CONNECTABLE, catalog_row, spec
from src.connections.models import (
    Connection, ConnectionAudit, ConnectionGrant, ConnectionSecret, ExternalAccountRoute,
)
from src.connections.providers import AccessToken, ProviderError, provider_for
from src.connections.providers.base import Account, pkce_pair

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 600
FORM_AUTH = frozenset({"api_key", "mailbox", "mcp"})
BROWSER_AUTH = frozenset({"oauth2", "github_app"})
# Neutral on purpose (functional spec §6.5): it does not say which business has it.
ACCOUNT_TAKEN = "This account is already connected to another HireBuddha business. Contact support to move it."


class ConnectionProblem(RuntimeError):
    """A connection request that cannot be done; the message is safe to show."""


class NoSuchConnection(ConnectionProblem):
    """No connection of this business has that id — another business's included (404, not 409)."""


class NotGranted(PermissionError):
    """The caller (agent, app) has not been granted this connection."""


# ── Redis state ─────────────────────────────────────────────────────────────

def _redis() -> Any:
    from src.common.redis_client import shared_redis

    return shared_redis()


async def _put(key: str, value: Dict[str, Any]) -> None:
    await _redis().set(key, json.dumps(value, default=str), ex=STATE_TTL_SECONDS)


async def _take(key: str) -> Optional[Dict[str, Any]]:
    raw = await _redis().getdel(key)
    return json.loads(raw) if raw else None


async def _peek(key: str) -> Optional[Dict[str, Any]]:
    raw = await _redis().get(key)
    return json.loads(raw) if raw else None


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


async def _seal_blob(company_id: Any, row_id: str, value: Any) -> Dict[str, Any]:
    from src.common.tenancy.session import tenant_session

    async with tenant_session(company_id) as db:
        version, nonce, ciphertext = await crypto.seal_secret(db, company_id, row_id, {"v": value})
        await db.commit()
    return {"version": version, "nonce": _b64(nonce), "ciphertext": _b64(ciphertext)}


async def _open_blob(company_id: Any, row_id: str, blob: Dict[str, Any]) -> Any:
    from src.common.tenancy.session import tenant_session

    async with tenant_session(company_id) as db:
        opened = await crypto.open_secret(db, company_id, row_id, blob["version"],
                                          base64.b64decode(blob["nonce"]), base64.b64decode(blob["ciphertext"]))
    return opened["v"]


# ── Small helpers ───────────────────────────────────────────────────────────

def redirect_uri(provider: str) -> str:
    from src.common.config import settings
    from src.voice.public_urls import callback_url

    base = settings.CONNECTIONS_PUBLIC_URL.rstrip("/") if settings.CONNECTIONS_PUBLIC_URL else callback_url("")
    return f"{base}/oauth/callback/{provider}"


def frontend_url(path: Optional[str], **query: Any) -> str:
    from src.common.config import settings

    path = path if path and path.startswith("/") and not path.startswith("//") else settings.CONNECTIONS_RETURN_PATH
    clean = {k: v for k, v in query.items() if v is not None}
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}{'?' + urlencode(clean, quote_via=quote) if clean else ''}"


async def _connector(connector_id: str, *, connectable: bool = True) -> Tuple[Any, Any]:
    """The catalog row and HireBuddha's app for it (``None`` for form connectors)."""
    from src.common.tenancy.session import control_session
    from src.connections.apps import AppNotConfigured, provider_app

    async with control_session() as db:
        row = await catalog_row(db, connector_id)
        if row is None:
            raise ConnectionProblem(f"There is no connector {connector_id!r}.")
        if connectable and row.effective_status not in CONNECTABLE:
            raise ConnectionProblem(f"{row.display_name} cannot be connected yet.")
        app = None
        if row.oauth_app_ref:
            try:
                app = await provider_app(db, row.oauth_app_ref)
            except AppNotConfigured as error:
                if connectable:
                    raise ConnectionProblem(f"{row.display_name} is not set up on this platform yet.") from error
    return row, app


async def _audit(db: Any, company_id: Any, connection_id: Any, action: str, *, actor_kind: str = "system",
                 actor_id: Any = None, run_id: Any = None, detail: Optional[Dict[str, Any]] = None) -> None:
    db.add(ConnectionAudit(company_id=company_id, connection_id=connection_id, action=action,
                           actor_kind=actor_kind, actor_id=actor_id, run_id=run_id, detail=detail))


async def _emit(company_id: Any, event_type: str, connection: Any, data: Dict[str, Any]) -> None:
    from src.automation import store
    from src.automation.events import Envelope
    from src.common.tenancy.session import tenant_session

    try:
        async with tenant_session(company_id) as db:
            await store.emit(db, company_id, Envelope(
                type=event_type, source="connections", trust="internal",
                dedupe_key=f"{event_type}:{connection.id}:{datetime.utcnow().isoformat()}",
                subject=f"connection:{connection.id}",
                data={"connection_id": str(connection.id), "connector_id": connection.connector_id,
                      "display_name": connection.display_name, **data}))
    except Exception:  # noqa: BLE001 - the connection change stands without its event
        logger.warning("event %s for connection %s not stored", event_type, connection.id, exc_info=True)


def _grant_rows(connection_id: Any, grants: Optional[Iterable[Dict[str, Any]]]) -> List[ConnectionGrant]:
    rows: List[ConnectionGrant] = []
    for grant in grants if grants is not None else [{"principal_kind": "all_agents"}]:
        kind = grant.get("principal_kind")
        if kind not in ("all_agents", "entity", "app"):
            raise ConnectionProblem(f"who may use it: {kind!r} is not all_agents, entity or app")
        principal = grant.get("principal_id")
        if (kind == "all_agents") != (principal is None):
            raise ConnectionProblem("all_agents takes no principal_id; entity and app need one")
        rows.append(ConnectionGrant(connection_id=connection_id, principal_kind=kind,
                                    principal_id=uuid.UUID(str(principal)) if principal else None,
                                    actions=list(grant.get("actions") or ["*"])))
    return rows


async def _secret(db: Any, connection: Any) -> Dict[str, Any]:
    row = await db.get(ConnectionSecret, connection.id)
    if row is None:
        return {}
    return await crypto.open_secret(db, connection.company_id, connection.id, row.dek_version, row.nonce,
                                    row.ciphertext)


async def _store_secret(db: Any, connection: Any, secret: Dict[str, Any]) -> None:
    version, nonce, ciphertext = await crypto.seal_secret(db, connection.company_id, connection.id, secret)
    row = await db.get(ConnectionSecret, connection.id)
    if row is None:
        db.add(ConnectionSecret(connection_id=connection.id, dek_version=version, nonce=nonce,
                                ciphertext=ciphertext))
    else:
        row.dek_version, row.nonce, row.ciphertext, row.updated_at = version, nonce, ciphertext, datetime.utcnow()


def view(connection: Any, grants: Optional[List[Any]] = None) -> Dict[str, Any]:
    out = {
        "id": str(connection.id), "connector_id": connection.connector_id,
        "display_name": connection.display_name, "external_account_id": connection.external_account_id,
        "external_account_name": connection.external_account_name, "status": connection.status,
        "scopes": list(connection.scopes_granted or []),
        "token_expires_at": connection.token_expires_at.isoformat() if connection.token_expires_at else None,
        "health": connection.health or {}, "settings": _public_settings(connection.settings),
        "connected_at": connection.connected_at.isoformat() if connection.connected_at else None,
        "last_used_at": connection.last_used_at.isoformat() if connection.last_used_at else None,
    }
    if grants is not None:
        out["grants"] = [{"principal_kind": g.principal_kind,
                          "principal_id": str(g.principal_id) if g.principal_id else None,
                          "actions": list(g.actions or [])} for g in grants]
    return out


def _public_settings(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {k: v for k, v in (settings or {}).items() if not k.endswith(("secret", "password", "token"))}


# ── 1. Start ────────────────────────────────────────────────────────────────

async def start(company_id: Any, user_id: Any, connector_id: str, *, return_path: Optional[str] = None,
                reconnect_id: Any = None) -> Dict[str, Any]:
    row, app = await _connector(connector_id)
    if row.auth_type in FORM_AUTH:
        return {"kind": "form", "connector_id": row.id, "form": [f.model_dump() for f in spec(row.id).form]}
    provider = provider_for(row.provider)
    state = pysecrets.token_urlsafe(32)
    verifier, challenge = pkce_pair() if provider.uses_pkce else (None, None)
    await _put(f"oauth:state:{state}", {
        "company_id": str(company_id), "user_id": str(user_id) if user_id else None, "connector_id": row.id,
        "return_path": return_path, "reconnect_id": str(reconnect_id) if reconnect_id else None,
        "verifier": await _seal_blob(company_id, f"state:{state}", verifier) if verifier else None,
    })
    if row.auth_type == "meta_embedded_signup":
        from src.connections.providers.meta import embedded_signup_params

        return {"kind": "embedded_signup", "connector_id": row.id, "params": embedded_signup_params(app, state)}
    url = await provider.authorize_url(app, row, state=state, redirect_uri=redirect_uri(row.provider),
                                       code_challenge=challenge)
    return {"kind": "redirect", "connector_id": row.id, "url": url}


# ── 2. Callback → pending result ───────────────────────────────────────────

async def _pending_from(state_data: Dict[str, Any], state: str, params: Dict[str, Any]) -> str:
    company_id = state_data["company_id"]
    row, app = await _connector(state_data["connector_id"])
    provider = provider_for(row.provider)
    verifier = await _open_blob(company_id, f"state:{state}", state_data["verifier"]) \
        if state_data.get("verifier") else None
    accounts = await provider.exchange(app, row, params, redirect_uri=redirect_uri(row.provider),
                                       code_verifier=verifier)
    pending_id = uuid.uuid4().hex
    await _put(f"oauth:pending:{pending_id}", {
        "company_id": company_id, "user_id": state_data.get("user_id"), "connector_id": row.id,
        "reconnect_id": state_data.get("reconnect_id"), "return_path": state_data.get("return_path"),
        "accounts": [{**a.public(), "scopes": a.scopes,
                      "expires_at": a.expires_at.isoformat() if a.expires_at else None} for a in accounts],
        "sealed": await _seal_blob(company_id, f"pending:{pending_id}", [a.secret for a in accounts]),
    })
    return pending_id


async def callback(provider_name: str, params: Dict[str, Any]) -> str:
    """Where the browser goes next: the "choose accounts" step, or back with an error."""
    state = str(params.get("state") or "")
    data = await _take(f"oauth:state:{state}") if state else None
    if data is None:
        return frontend_url(None, error="The sign-in took too long or was already used. Please try again.")
    try:
        row, _ = await _connector(data["connector_id"])
        if row.provider != provider_name:
            raise ConnectionProblem("This sign-in came back from a different provider.")
        pending_id = await _pending_from(data, state, params)
    except (ConnectionProblem, ProviderError) as error:
        return frontend_url(data.get("return_path"), error=str(error), connector=data.get("connector_id"))
    return frontend_url(data.get("return_path"), pending=pending_id, connector=data["connector_id"])


async def complete_embedded_signup(company_id: Any, state: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """WhatsApp: the browser's Embedded Signup finished; its code makes a pending result."""
    data = await _take(f"oauth:state:{state}")
    if data is None or data["company_id"] != str(company_id):
        raise ConnectionProblem("The sign-up took too long or was already used. Please try again.")
    pending_id = await _pending_from(data, state, params)
    return await pending_view(company_id, pending_id)


async def pending_view(company_id: Any, pending_id: str) -> Dict[str, Any]:
    data = await _peek(f"oauth:pending:{pending_id}")
    if data is None or data["company_id"] != str(company_id):
        raise ConnectionProblem("This connection request has expired. Please connect again.")
    row, _ = await _connector(data["connector_id"], connectable=False)
    taken = await _taken(company_id, row.provider, [a["external_id"] for a in data["accounts"]])
    return {"pending_id": pending_id, "connector_id": row.id, "display_name": row.display_name,
            "reconnect_id": data.get("reconnect_id"),
            "accounts": [{**{k: a[k] for k in ("external_id", "name", "settings")},
                          "available": a["external_id"] not in taken} for a in data["accounts"]]}


async def _taken(company_id: Any, provider: str, external_ids: List[str]) -> set:
    """Of ``external_ids``, those another business owns."""
    from src.common.tenancy.session import control_session

    ids = [i for i in external_ids if i]
    if not ids:
        return set()
    async with control_session() as db:
        rows = (await db.execute(select(ExternalAccountRoute.external_account_id).where(
            ExternalAccountRoute.provider == provider, ExternalAccountRoute.external_account_id.in_(ids),
            ExternalAccountRoute.company_id != uuid.UUID(str(company_id))))).scalars().all()
    return set(rows)


# ── 3. Finalize ─────────────────────────────────────────────────────────────

async def finalize(company_id: Any, user_id: Any, pending_id: str, account_ids: List[str], *,
                   grants: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    data = await _peek(f"oauth:pending:{pending_id}")
    if data is None or data["company_id"] != str(company_id):
        raise ConnectionProblem("This connection request has expired. Please connect again.")
    wanted = [a for a in data["accounts"] if a["external_id"] in set(account_ids)]
    if not wanted:
        raise ConnectionProblem("Choose at least one account.")
    secrets = await _open_blob(company_id, f"pending:{pending_id}", data["sealed"])
    by_id = {a["external_id"]: s for a, s in zip(data["accounts"], secrets)}
    row, app = await _connector(data["connector_id"])
    made, refused = [], []
    for item in wanted:
        account = Account(external_id=item["external_id"], name=item["name"], secret=by_id[item["external_id"]],
                          settings=item.get("settings") or {}, scopes=item.get("scopes") or [],
                          expires_at=datetime.fromisoformat(item["expires_at"]) if item.get("expires_at") else None)
        try:
            made.append(await _connect(company_id, user_id, row, app, account, grants,
                                       reconnect_id=data.get("reconnect_id")))
        except ConnectionProblem as error:
            refused.append({"external_id": account.external_id, "name": account.name, "reason": str(error)})
    await _redis().delete(f"oauth:pending:{pending_id}")
    return {"connections": made, "refused": refused}


async def create_from_form(company_id: Any, user_id: Any, connector_id: str, fields: Dict[str, Any], *,
                           grants: Optional[List[Dict[str, Any]]] = None,
                           display_name: Optional[str] = None) -> Dict[str, Any]:
    row, app = await _connector(connector_id)
    if row.auth_type not in FORM_AUTH:
        raise ConnectionProblem(f"{row.display_name} is connected through its own sign-in, not a form.")
    try:
        account = await provider_for(row.provider).from_form(row, fields)
    except ProviderError as error:
        raise ConnectionProblem(str(error)) from error
    if display_name:
        account.name = display_name
    return await _connect(company_id, user_id, row, app, account, grants)


async def _claim_route(company_id: Any, provider: str, external_id: str, connection_id: Any) -> None:
    from sqlalchemy.dialects.postgresql import insert

    from src.common.tenancy.directory import directory
    from src.common.tenancy.session import control_session

    if not external_id:
        return
    location = await directory.find(company_id)
    async with control_session() as db:
        owner = (await db.execute(
            insert(ExternalAccountRoute).values(
                provider=provider, external_account_id=external_id, company_id=uuid.UUID(str(company_id)),
                tenant_key=location.key if location else None, connection_id=connection_id)
            .on_conflict_do_update(
                index_elements=["provider", "external_account_id"],
                set_={"connection_id": connection_id},
                where=ExternalAccountRoute.company_id == uuid.UUID(str(company_id)))
            .returning(ExternalAccountRoute.company_id))).scalar_one_or_none()
        await db.commit()
    if owner is None:
        raise ConnectionProblem(ACCOUNT_TAKEN)


async def _connect(company_id: Any, user_id: Any, row: Any, app: Any, account: Account,
                   grants: Optional[List[Dict[str, Any]]], *, reconnect_id: Any = None) -> Dict[str, Any]:
    from src.common.tenancy.session import tenant_session

    company = uuid.UUID(str(company_id))
    provider = provider_for(row.provider)
    async with tenant_session(company) as db:
        existing = None
        if reconnect_id:
            existing = await db.get(Connection, uuid.UUID(str(reconnect_id)))
            if existing is None or existing.company_id != company:
                raise ConnectionProblem("The connection to reconnect is gone.")
            if account.external_id and existing.external_account_id and existing.external_account_id != account.external_id:
                raise ConnectionProblem("Sign in with the same account to reconnect it.")
        elif account.external_id:
            existing = (await db.execute(select(Connection).where(
                Connection.company_id == company, Connection.connector_id == row.id,
                Connection.external_account_id == account.external_id,
                Connection.status != "revoked"))).scalars().first()
        connection = existing or Connection(id=uuid.uuid4(), company_id=company, connector_id=row.id,
                                            display_name=account.name, connected_by=user_id)
        await _claim_route(company, row.provider, account.external_id, connection.id)
        connection.external_account_id = account.external_id or None
        connection.external_account_name = account.name
        connection.scopes_granted = list(account.scopes or row.scopes or [])
        connection.token_expires_at = account.expires_at
        connection.status = "active"
        connection.settings = {**(connection.settings or {}), **account.settings}
        connection.health = {}
        if existing is None:
            db.add(connection)
            await db.flush()
            db.add_all(_grant_rows(connection.id, grants))
        else:
            connection.version = (connection.version or 1) + 1
        await _store_secret(db, connection, account.secret)
        await _audit(db, company, connection.id, "reconnected" if existing else "connected", actor_kind="user",
                     actor_id=user_id, detail={"external_account": account.external_id})
        await db.commit()
        try:
            extra = await provider.after_connect(app, row, connection.settings, account.secret)
        except ProviderError as error:
            extra = {"setup_error": str(error)}
        if extra:
            connection.settings = {**connection.settings, **extra}
            await db.commit()
        grant_rows = (await db.execute(select(ConnectionGrant).where(ConnectionGrant.connection_id == connection.id))
                      ).scalars().all()
        result = view(connection, list(grant_rows))
    result["test"] = await test(company, connection.id, actor_kind="system")
    await _emit(company, "connection.connected" if not reconnect_id else "connection.reconnected", connection,
                {"external_account_name": account.name})
    return result


# ── Using and managing a connection ────────────────────────────────────────

async def _load(db: Any, company_id: Any, connection_id: Any) -> Connection:
    connection = await db.get(Connection, uuid.UUID(str(connection_id)))
    if connection is None or connection.company_id != uuid.UUID(str(company_id)):
        raise NoSuchConnection("There is no such connection.")
    return connection


async def list_connections(company_id: Any) -> List[Dict[str, Any]]:
    from src.common.tenancy.session import tenant_session

    company = uuid.UUID(str(company_id))
    async with tenant_session(company) as db:
        rows = (await db.execute(select(Connection).where(Connection.company_id == company)
                                 .order_by(Connection.connected_at.desc()))).scalars().all()
        grants = (await db.execute(select(ConnectionGrant).where(
            ConnectionGrant.connection_id.in_([r.id for r in rows])))).scalars().all() if rows else []
    by_connection: Dict[Any, List[Any]] = {}
    for grant in grants:
        by_connection.setdefault(grant.connection_id, []).append(grant)
    return [view(row, by_connection.get(row.id, [])) for row in rows]


async def detail(company_id: Any, connection_id: Any, *, audit_limit: int = 50) -> Dict[str, Any]:
    from src.common.tenancy.session import tenant_session

    async with tenant_session(company_id) as db:
        connection = await _load(db, company_id, connection_id)
        grants = (await db.execute(select(ConnectionGrant).where(ConnectionGrant.connection_id == connection.id))
                  ).scalars().all()
        audit = (await db.execute(select(ConnectionAudit).where(ConnectionAudit.connection_id == connection.id)
                                  .order_by(ConnectionAudit.at.desc()).limit(audit_limit))).scalars().all()
        out = view(connection, list(grants))
    out["activity"] = [{"action": a.action, "actor_kind": a.actor_kind,
                        "actor_id": str(a.actor_id) if a.actor_id else None,
                        "run_id": str(a.run_id) if a.run_id else None, "at": a.at.isoformat(),
                        "detail": a.detail} for a in audit]
    out["impact"] = await impact(company_id, connection_id)
    return out


async def test(company_id: Any, connection_id: Any, *, actor_kind: str = "user", actor_id: Any = None) -> Dict[str, Any]:
    from src.common.tenancy.session import tenant_session

    async with tenant_session(company_id) as db:
        connection = await _load(db, company_id, connection_id)
        row, app = await _connector(connection.connector_id, connectable=False)
        secret = await _secret(db, connection)
        now = datetime.utcnow().isoformat()
        try:
            result = await provider_for(row.provider).test(app, row, connection.settings or {}, secret)
            connection.health = {**(connection.health or {}), "last_check_at": now, "last_ok_at": now,
                                 "last_error": None}
            if result.get("tools") is not None:
                connection.settings = {**(connection.settings or {}), "tools": result["tools"]}
            await _audit(db, company_id, connection.id, "test_ok", actor_kind=actor_kind, actor_id=actor_id,
                         detail={"detail": str(result.get("detail"))[:300]})
        except Exception as error:  # noqa: BLE001 - a failed test is a result
            result = {"ok": False, "detail": str(error)[:300]}
            connection.health = {**(connection.health or {}), "last_check_at": now, "last_error": result["detail"]}
            await _audit(db, company_id, connection.id, "test_failed", actor_kind=actor_kind, actor_id=actor_id,
                         detail={"detail": result["detail"]})
        await db.commit()
    return {k: v for k, v in result.items() if k != "tools"}


async def set_grants(company_id: Any, connection_id: Any, grants: List[Dict[str, Any]], *,
                     actor_id: Any = None) -> Dict[str, Any]:
    from src.common.tenancy.session import tenant_session

    async with tenant_session(company_id) as db:
        connection = await _load(db, company_id, connection_id)
        rows = _grant_rows(connection.id, grants)
        await db.execute(delete(ConnectionGrant).where(ConnectionGrant.connection_id == connection.id))
        db.add_all(rows)
        await _audit(db, company_id, connection.id, "grants_changed", actor_kind="user", actor_id=actor_id,
                     detail={"grants": [{"principal_kind": r.principal_kind,
                                         "principal_id": str(r.principal_id) if r.principal_id else None,
                                         "actions": r.actions} for r in rows]})
        await db.commit()
        return view(connection, rows)


async def _dependent_triggers(db: Any, connection_id: Any) -> List[Any]:
    from src.automation.models import Trigger

    needle = f"connection:{connection_id}"
    return list((await db.execute(select(Trigger).where(
        or_(cast(Trigger.filter, Text).contains(needle), cast(Trigger.input_template, Text).contains(needle),
            cast(Trigger.filter, Text).contains(str(connection_id)))))).scalars().all())


async def impact(company_id: Any, connection_id: Any) -> Dict[str, Any]:
    """What stops if the connection goes: the agents that may use it, the
    triggers that listen to it (and, with WS6, the apps)."""
    from src.ai.orm.entity import HierarchicalEntity
    from src.common.tenancy.session import tenant_session

    async with tenant_session(company_id) as db:
        connection = await _load(db, company_id, connection_id)
        grants = (await db.execute(select(ConnectionGrant).where(ConnectionGrant.connection_id == connection.id))
                  ).scalars().all()
        entity_ids = [g.principal_id for g in grants if g.principal_kind == "entity"]
        names = dict((await db.execute(select(HierarchicalEntity.id, HierarchicalEntity.name).where(
            HierarchicalEntity.id.in_(entity_ids)))).all()) if entity_ids else {}
        triggers = await _dependent_triggers(db, connection.id)
    return {
        "all_agents": any(g.principal_kind == "all_agents" for g in grants),
        "agents": [{"id": str(i), "name": names.get(i)} for i in entity_ids],
        "apps": [str(g.principal_id) for g in grants if g.principal_kind == "app"],
        "triggers": [{"id": str(t.id), "name": t.name, "enabled": t.enabled} for t in triggers],
    }


async def _pause_triggers(db: Any, connection_id: Any) -> List[str]:
    paused = []
    for trigger in await _dependent_triggers(db, connection_id):
        if trigger.enabled:
            trigger.enabled = False
            paused.append(trigger.name)
    return paused


async def revoke(company_id: Any, connection_id: Any, *, actor_id: Any = None) -> Dict[str, Any]:
    from src.common.tenancy.session import control_session, tenant_session

    async with tenant_session(company_id) as db:
        connection = await _load(db, company_id, connection_id)
        row, app = await _connector(connection.connector_id, connectable=False)
        secret = await _secret(db, connection)
        provider_error = None
        try:
            await provider_for(row.provider).revoke(app, row, connection.settings or {}, secret)
        except Exception as error:  # noqa: BLE001 - disconnecting here must not depend on the provider
            provider_error = str(error)[:300]
        await db.execute(delete(ConnectionSecret).where(ConnectionSecret.connection_id == connection.id))
        connection.status = "revoked"
        paused = await _pause_triggers(db, connection.id)
        await _audit(db, company_id, connection.id, "revoked", actor_kind="user", actor_id=actor_id,
                     detail={"provider_error": provider_error, "triggers_paused": paused})
        await db.commit()
    async with control_session() as db:
        await db.execute(delete(ExternalAccountRoute).where(ExternalAccountRoute.connection_id == connection.id))
        await db.commit()
    await _emit(company_id, "connection.revoked", connection, {"triggers_paused": paused})
    return {"revoked": True, "triggers_paused": paused, "provider_error": provider_error}


# ── The token broker ────────────────────────────────────────────────────────

def _granted(grants: List[Any], principal_kind: str, principal_id: Any, action: Optional[str]) -> bool:
    for grant in grants:
        allowed = grant.principal_kind == "all_agents" and principal_kind == "entity" or (
            grant.principal_kind == principal_kind and str(grant.principal_id) == str(principal_id))
        if allowed and ("*" in (grant.actions or []) or (action and action in grant.actions)):
            return True
    return False


async def issue_token(company_id: Any, connection_id: Any, *, principal_kind: str, principal_id: Any,
                      action: Optional[str] = None, run_id: Any = None) -> AccessToken:
    """A usable credential for one granted caller (refreshed first when about to expire)."""
    from src.common.config import settings
    from src.common.tenancy.session import tenant_session

    async with tenant_session(company_id) as db:
        connection = await _load(db, company_id, connection_id)
        grants = (await db.execute(select(ConnectionGrant).where(ConnectionGrant.connection_id == connection.id))
                  ).scalars().all()
        if not _granted(list(grants), principal_kind, principal_id, action):
            await _audit(db, company_id, connection.id, "refused", actor_kind=principal_kind,
                         actor_id=principal_id, run_id=run_id, detail={"action": action})
            await db.commit()
            raise NotGranted(f"{connection.display_name} is not shared with this {principal_kind}")
        if connection.status not in ("active", "expiring"):
            raise ConnectionProblem(f"{connection.display_name} needs to be reconnected ({connection.status}).")
        row, app = await _connector(connection.connector_id, connectable=False)
        provider = provider_for(row.provider)
        secret = await _secret(db, connection)
        window = timedelta(seconds=settings.CONNECTION_REFRESH_WINDOW_SECONDS)
        if connection.token_expires_at and connection.token_expires_at - window < datetime.utcnow():
            secret = await _refresh_one(db, connection, row, app, secret)
        token = await provider.access(app, row, connection.settings or {}, secret)
        connection.last_used_at = datetime.utcnow()
        await _audit(db, company_id, connection.id, "token_issued", actor_kind=principal_kind,
                     actor_id=principal_id, run_id=run_id, detail={"action": action} if action else None)
        await db.commit()
    if token.expires_at is None:
        token.expires_at = connection.token_expires_at
    return token


async def system_credential(company_id: Any, connection_id: Any, *, purpose: str) -> AccessToken:
    """The platform's own use of a connection — a poller reading new mail, a
    webhook subscription check — not an agent's or an app's: no grant applies,
    and the use is audited with its purpose."""
    from src.common.config import settings
    from src.common.tenancy.session import tenant_session

    async with tenant_session(company_id) as db:
        connection = await _load(db, company_id, connection_id)
        if connection.status not in ("active", "expiring"):
            raise ConnectionProblem(f"{connection.display_name} needs to be reconnected ({connection.status}).")
        row, app = await _connector(connection.connector_id, connectable=False)
        secret = await _secret(db, connection)
        window = timedelta(seconds=settings.CONNECTION_REFRESH_WINDOW_SECONDS)
        if connection.token_expires_at and connection.token_expires_at - window < datetime.utcnow():
            secret = await _refresh_one(db, connection, row, app, secret)
        token = await provider_for(row.provider).access(app, row, connection.settings or {}, secret)
        await _audit(db, company_id, connection.id, "used", actor_kind="system", detail={"purpose": purpose})
        await db.commit()
    return token


async def business_key(company_id: Any, *, provider: Optional[str] = None, sku: Optional[str] = None,
                       model: Optional[str] = None) -> Optional[str]:
    """The business's own key for a provider the platform integrates (a
    ``provider_api_key`` connection matching the SKU, model or provider), or
    ``None``. What ``ConfigService`` uses before the platform's key (WS5 5.7, D40)."""
    from src.common.tenancy.session import tenant_session

    if company_id is None or not (provider or sku or model):
        return None
    try:
        async with tenant_session(company_id) as db:
            rows = (await db.execute(select(Connection).where(
                Connection.company_id == uuid.UUID(str(company_id)), Connection.connector_id == "provider_api_key",
                Connection.status.in_(("active", "expiring"))).order_by(Connection.connected_at.desc()))
            ).scalars().all()
    except Exception:  # noqa: BLE001 - a database before WS5's tables, or a tenant not ready
        return None
    for field, wanted in (("service_sku", sku), ("model_name", model), ("provider", provider)):
        if not wanted:
            continue
        for row in rows:
            if (row.settings or {}).get(field) == wanted:
                token = await system_credential(company_id, row.id, purpose=f"provider_key:{wanted}")
                return token.access_token
    return None


async def record_health(company_id: Any, connection_id: Any, *, error: Optional[str] = None) -> None:
    """Note a check's outcome on the connection (``health``)."""
    from src.common.tenancy.session import tenant_session

    now = datetime.utcnow().isoformat()
    async with tenant_session(company_id) as db:
        connection = await db.get(Connection, uuid.UUID(str(connection_id)))
        if connection is None:
            return
        connection.health = {**(connection.health or {}), "last_check_at": now,
                             **({"last_error": error} if error else {"last_ok_at": now, "last_error": None})}
        await db.commit()


async def connections_for(company_id: Any, connector_ids: Iterable[str], *, principal_kind: str,
                          principal_id: Any, account: Optional[str] = None) -> List[Dict[str, Any]]:
    """The caller's usable connections of these connectors (newest first); with
    ``account``, only one whose account name or id matches."""
    from src.common.tenancy.session import tenant_session

    company = uuid.UUID(str(company_id))
    async with tenant_session(company) as db:
        rows = (await db.execute(select(Connection).where(
            Connection.company_id == company, Connection.connector_id.in_(list(connector_ids)),
            Connection.status.in_(("active", "expiring"))).order_by(Connection.connected_at.desc()))).scalars().all()
        found = []
        for row in rows:
            grants = (await db.execute(select(ConnectionGrant).where(ConnectionGrant.connection_id == row.id))
                      ).scalars().all()
            if not _granted(list(grants), principal_kind, principal_id, None):
                continue
            if account and account not in (row.external_account_name, row.external_account_id, row.display_name):
                continue
            found.append(view(row))
    return found


# ── Refresh and expiry (the event worker's cron) ───────────────────────────

async def _refresh_one(db: Any, connection: Any, row: Any, app: Any, secret: Dict[str, Any]) -> Dict[str, Any]:
    provider = provider_for(row.provider)
    try:
        result = await provider.refresh(app, row, connection.settings or {}, secret)
    except Exception as error:  # noqa: BLE001
        await _refresh_failed(db, connection, str(error))
        raise ConnectionProblem(f"{connection.display_name} could not be refreshed and needs to be reconnected.") from error
    if result is None:
        return secret
    secret, expires_at = result
    await _store_secret(db, connection, secret)
    connection.token_expires_at = expires_at
    connection.status = "active"
    connection.health = {**(connection.health or {}), "refresh_failures": 0, "last_refresh_at": datetime.utcnow().isoformat()}
    await _audit(db, connection.company_id, connection.id, "refreshed")
    return secret


async def _refresh_failed(db: Any, connection: Any, error: str) -> None:
    from src.notifications.service import notify

    connection.status = "needs_reconnect"
    connection.health = {**(connection.health or {}), "last_error": error[:300],
                         "refresh_failures": int((connection.health or {}).get("refresh_failures", 0)) + 1}
    paused = await _pause_triggers(db, connection.id)
    await _audit(db, connection.company_id, connection.id, "refresh_failed",
                 detail={"error": error[:300], "triggers_paused": paused})
    await db.commit()
    await _emit(connection.company_id, "connection.needs_reconnect", connection, {"triggers_paused": paused})
    await notify(connection.company_id, kind="connection_needs_reconnect",
                 title=f"{connection.display_name} needs to be reconnected",
                 body=(f"HireBuddha could not refresh its access. {len(paused)} trigger(s) are paused until it is "
                       "reconnected." if paused else "HireBuddha could not refresh its access."),
                 dedupe_key=f"connection:{connection.id}:reconnect:{datetime.utcnow().date()}",
                 link=f"/connections/{connection.id}")


async def refresh_due(company_id: Any = None) -> Dict[str, Any]:
    """Refresh what expires within the window; warn about expiries that cannot be refreshed."""
    from src.common.config import settings
    from src.common.tenancy.session import tenant_session
    from src.notifications.service import notify

    now = datetime.utcnow()
    soon = now + timedelta(seconds=settings.CONNECTION_REFRESH_WINDOW_SECONDS)
    warn_before = now + timedelta(days=settings.CONNECTION_EXPIRY_WARNING_DAYS)
    done = {"refreshed": 0, "failed": 0, "warned": 0}
    async with tenant_session(company_id) as db:
        query = select(Connection).where(Connection.status.in_(("active", "expiring")),
                                         Connection.token_expires_at.is_not(None),
                                         Connection.token_expires_at < warn_before)
        if company_id is not None:
            query = query.where(Connection.company_id == uuid.UUID(str(company_id)))
        for connection in (await db.execute(query)).scalars().all():
            row, app = await _connector(connection.connector_id, connectable=False)
            secret = await _secret(db, connection)
            if secret.get("refresh_token") and connection.token_expires_at < soon:
                try:
                    await _refresh_one(db, connection, row, app, secret)
                    await db.commit()
                    done["refreshed"] += 1
                except ConnectionProblem:
                    done["failed"] += 1
                continue
            if secret.get("refresh_token"):
                continue  # refreshed when it is closer
            if not (connection.health or {}).get("warned_expiry_at"):
                connection.status = "expiring"
                connection.health = {**(connection.health or {}), "warned_expiry_at": now.isoformat()}
                await db.commit()
                await notify(connection.company_id, kind="connection_expiring",
                             title=f"{connection.display_name} expires on {connection.token_expires_at:%d %b %Y}",
                             body="Reconnect it before then so the agents and triggers using it keep working.",
                             dedupe_key=f"connection:{connection.id}:expiring",
                             link=f"/connections/{connection.id}")
                done["warned"] += 1
    return done

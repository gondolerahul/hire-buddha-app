"""App users: the people who sign in to a business's apps (Phase 14 WS6 6.10, tech spec §11.6).

Not HireBuddha users: each app has its own (``platform.app_users``), with
roles (``app_roles``: the objects and operations each may use, and whether
it sees only its **own rows**). They sign in at the Data API:

| Method | Path | |
|--------|------|-|
| POST | ``/v1/auth/login`` | ``{tenant, app, email, password}`` → access + refresh token |
| POST | ``/v1/auth/magic-link`` | ``{tenant, app, email, return_url}`` → a sign-in link by e-mail |
| POST | ``/v1/auth/magic-link/verify`` | ``{token}`` → access + refresh token |
| POST | ``/v1/auth/refresh`` | ``{refresh_token}`` → new pair (the old refresh token stops working) |
| POST | ``/v1/auth/logout`` | ``{refresh_token}`` |
| GET | ``/v1/auth/me`` | the signed-in user, app and roles |

Passwords are Argon2id. Access tokens (``APP_USER_ACCESS_MINUTES``) are JWTs
signed with the business's **app-auth key** — 256 random bits kept in
``app_auth_keys`` sealed under the business's DEK (so shredding the KEK ends
every app session too). Refresh tokens are random, stored hashed, rotated on
use. Magic links go through the platform's mail (``email_service``) to a
``return_url`` on one of the app's own hostnames.

**Row policies.** A role with ``own_rows`` sees, changes and creates only
records whose owner field is the user: the object names that field in the
blueprint (``row_policy: {"owner_field": "owner_email", "match": "email"}``,
or ``"match": "id"``). An object without one is closed to such a role.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit

from jose import JWTError, jwt
from sqlalchemy import select, update

from src.data_api import tokens

ALGORITHM = "HS256"
KEY_CACHE_SECONDS = 600
_keys: Dict[Tuple[str, int], Tuple[bytes, float]] = {}
_current: Dict[str, Tuple[int, float]] = {}


class AuthProblem(Exception):
    """A sign-in that failed (401) or was refused (400/403); the message is safe to show."""

    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


def _hasher() -> Any:
    from argon2 import PasswordHasher

    return PasswordHasher()   # Argon2id, the library's defaults (RFC 9106 second recommendation)


def hash_password(password: str) -> str:
    if len(password or "") < 8:
        raise AuthProblem("a password is at least 8 characters", 400)
    return _hasher().hash(password)


def verify_password(stored: Optional[str], password: str) -> bool:
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

    if not stored:
        _hasher().hash("timing-equaliser")
        return False
    try:
        return _hasher().verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ── The app-auth key ────────────────────────────────────────────────────────

def _aad(company_id: Any, version: int) -> str:
    return f"app-auth:{company_id}:{version}"


async def signing_key(db: Any, company_id: Any, version: Optional[int] = None) -> Tuple[int, bytes]:
    """The business's app-auth key (version, bytes): the given version, else the current one (made on first use)."""
    from src.apps.models import AppAuthKey
    from src.connections.crypto import open_secret, seal_secret

    cid = str(company_id)
    now = time.monotonic()
    if version is None:
        cached = _current.get(cid)
        if cached and cached[1] > now:
            version = cached[0]
    if version is not None:
        hit = _keys.get((cid, version))
        if hit and hit[1] > now:
            return version, hit[0]
    query = select(AppAuthKey).where(AppAuthKey.company_id == uuid.UUID(cid))
    query = query.where(AppAuthKey.version == version) if version is not None else \
        query.where(AppAuthKey.retired_at.is_(None)).order_by(AppAuthKey.version.desc())
    row = (await db.execute(query.limit(1))).scalar_one_or_none()
    if row is None:
        if version is not None:
            raise AuthProblem("the token was signed with a key this business no longer has")
        latest = (await db.execute(select(AppAuthKey.version).where(AppAuthKey.company_id == uuid.UUID(cid))
                                   .order_by(AppAuthKey.version.desc()).limit(1))).scalar()
        key = secrets.token_bytes(32)
        version = (latest or 0) + 1
        dek_version, nonce, ciphertext = await seal_secret(db, cid, _aad(cid, version),
                                                           {"k": base64.b64encode(key).decode()})
        db.add(AppAuthKey(company_id=uuid.UUID(cid), version=version, dek_version=dek_version, nonce=nonce,
                          ciphertext=ciphertext))
        await db.commit()
    else:
        version = row.version
        opened = await open_secret(db, cid, _aad(cid, row.version), row.dek_version, row.nonce, row.ciphertext)
        key = base64.b64decode(opened["k"])
    _keys[(cid, version)] = (key, now + KEY_CACHE_SECONDS)
    _current[cid] = (version, now + KEY_CACHE_SECONDS)
    return version, key


def forget_keys(company_id: Any = None) -> None:
    if company_id is None:
        _keys.clear()
        _current.clear()
        return
    for key in [k for k in _keys if k[0] == str(company_id)]:
        _keys.pop(key, None)
    _current.pop(str(company_id), None)


async def rotate_signing_key(db: Any, company_id: Any) -> int:
    """A new app-auth key; the old one is retired (its tokens stop at once)."""
    from src.apps.models import AppAuthKey

    await db.execute(update(AppAuthKey).where(AppAuthKey.company_id == uuid.UUID(str(company_id)),
                                              AppAuthKey.retired_at.is_(None)).values(retired_at=datetime.utcnow()))
    await db.commit()
    forget_keys(company_id)
    version, _ = await signing_key(db, company_id)
    return version


# ── Roles → what a token may do ─────────────────────────────────────────────

async def grants_for(db: Any, user: Any) -> Tuple[Dict[str, List[str]], FrozenSet[str], List[str]]:
    """``(objects → operations, objects limited to own rows, role names)`` of a user.
    An object one role grants without ``own_rows`` is not limited."""
    from src.apps.models import AppRole, AppUserRole

    roles = (await db.execute(select(AppRole).join(AppUserRole, AppUserRole.role_id == AppRole.id)
                              .where(AppUserRole.app_user_id == user.id))).scalars().all()
    objects: Dict[str, set] = {}
    limited, open_ = set(), set()
    for role in roles:
        perms = role.permissions or {}
        for name, ops in (perms.get("objects") or {}).items():
            objects.setdefault(name, set()).update(tokens.OPERATIONS if ops in ("*", ["*"]) else ops)
            (limited if perms.get("own_rows") else open_).add(name)
    return ({k: sorted(v) for k, v in objects.items()}, frozenset(limited - open_), sorted(r.name for r in roles))


# ── Tokens ──────────────────────────────────────────────────────────────────

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _issue(db: Any, user: Any, app: Any, tenant_key: str) -> Dict[str, Any]:
    from src.apps.models import AppUserSession
    from src.common.config import settings

    objects, own, roles = await grants_for(db, user)
    version, key = await signing_key(db, user.company_id)
    now = int(time.time())
    ttl = settings.APP_USER_ACCESS_MINUTES * 60
    access = jwt.encode({"aud": f"data-api:{tenant_key}", "sub": f"app_user:{user.id}", "typ": "app_user",
                         "cid": str(user.company_id), "tk": tenant_key, "app": app.name, "aid": str(app.id),
                         "email": user.email, "obj": objects, "own": sorted(own), "tv": user.token_version,
                         "iat": now, "exp": now + ttl}, key, algorithm=ALGORITHM, headers={"kid": f"app:{version}"})
    refresh = "hbr_" + secrets.token_urlsafe(32)
    db.add(AppUserSession(company_id=user.company_id, app_user_id=user.id, token_hash=_hash(refresh),
                          expires_at=datetime.utcnow() + timedelta(days=settings.APP_USER_REFRESH_DAYS)))
    user.last_login_at = datetime.utcnow()
    await db.commit()
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer", "expires_in": ttl,
            "roles": roles}


async def _business(tenant: Optional[str]) -> Tuple[Any, Any, str]:
    """``(company_id, engine, tenant key)`` of the business a sign-in names (or the pinned one)."""
    from src.data_api.app import _company_for_tenant, _pinned
    from src.schema_engine import engine as schema

    pinned = _pinned()
    tenant_key = pinned or (tenant or "").strip()
    if not tenant_key or (pinned and tenant and tenant != pinned):
        raise AuthProblem("name the business (tenant)", 400)
    try:
        company_id = await _company_for_tenant(tenant_key)
    except tokens.Unauthorized:
        raise AuthProblem("unknown business") from None
    engine, _ = await schema.business_engine(company_id)
    return company_id, engine, tenant_key


async def _app(db: Any, company_id: Any, name: str) -> Any:
    from src.apps.models import App

    app = (await db.execute(select(App).where(App.company_id == company_id, App.name == (name or "").strip().lower()))
           ).scalar_one_or_none()
    if app is None or app.status == "archived":
        raise AuthProblem("unknown app")
    return app


async def _user(db: Any, app: Any, email: str) -> Any:
    from src.apps.models import AppUser

    return (await db.execute(select(AppUser).where(AppUser.app_id == app.id,
                                                   AppUser.email == (email or "").strip().lower()))
            ).scalar_one_or_none()


async def login(tenant: Optional[str], app_name: str, email: str, password: str) -> Dict[str, Any]:
    from src.schema_engine import engine as schema

    company_id, engine, tenant_key = await _business(tenant)
    async with schema.session(engine) as db:
        app = await _app(db, company_id, app_name)
        user = await _user(db, app, email)
        if not verify_password(user.password_hash if user else None, password or "") or user.status != "active":
            raise AuthProblem("wrong e-mail or password")
        return await _issue(db, user, app, tenant_key)


async def refresh(refresh_token: str) -> Dict[str, Any]:
    """A new pair for a refresh token, which is used up. The business is found from the session row."""
    company_id, engine, tenant_key, session_id = await _find_session(refresh_token)
    from src.apps.models import App, AppUser, AppUserSession
    from src.schema_engine import engine as schema

    async with schema.session(engine) as db:
        row = await db.get(AppUserSession, session_id)
        if row is None or row.revoked_at is not None or row.expires_at < datetime.utcnow():
            raise AuthProblem("sign in again")
        row.revoked_at = datetime.utcnow()
        user = await db.get(AppUser, row.app_user_id)
        app = await db.get(App, user.app_id) if user else None
        if user is None or user.status != "active" or app is None or app.status == "archived":
            await db.commit()
            raise AuthProblem("sign in again")
        return await _issue(db, user, app, tenant_key)


async def _find_session(refresh_token: str) -> Tuple[Any, Any, str, Any]:
    """The business and session row of a refresh token: the pinned business, or each business in turn.
    Refresh tokens name no business, so an instance serving several looks in each (local development)."""
    from src.apps.models import AppUserSession
    from src.common.tenancy.directory import directory
    from src.data_api.app import _company_for_tenant, _pinned
    from src.schema_engine import engine as schema

    if not (refresh_token or "").startswith("hbr_"):
        raise AuthProblem("sign in again")
    digest = _hash(refresh_token)
    pinned = _pinned()
    companies = [await _company_for_tenant(pinned)] if pinned else await directory.ready_company_ids()
    for company_id in companies:
        try:
            engine, location = await schema.business_engine(company_id)
        except Exception:  # noqa: BLE001 - a business without records
            continue
        async with schema.session(engine) as db:
            found = (await db.execute(select(AppUserSession.id).where(AppUserSession.token_hash == digest,
                                                                      AppUserSession.company_id == company_id))
                     ).scalar()
        if found is not None:
            return company_id, engine, location.key, found
    raise AuthProblem("sign in again")


async def logout(refresh_token: str) -> None:
    from src.apps.models import AppUserSession
    from src.schema_engine import engine as schema

    try:
        _, engine, _, session_id = await _find_session(refresh_token)
    except AuthProblem:
        return
    async with schema.session(engine) as db:
        row = await db.get(AppUserSession, session_id)
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.utcnow()
            await db.commit()


def _allowed_return(app: Any, url: str) -> bool:
    """A sign-in link goes back only to the app itself (its hostnames), or to localhost in development."""
    from src.common.config import settings

    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("https", "http") or not host:
        return False
    if parts.scheme == "http" and host not in ("localhost", "127.0.0.1"):
        return False
    if host in ("localhost", "127.0.0.1"):
        return (settings.PLATFORM_PROFILE or "local") == "local"
    return host in set((app.settings or {}).get("hostnames") or [])


async def request_magic_link(tenant: Optional[str], app_name: str, email: str, return_url: str) -> None:
    """E-mail a sign-in link (15 minutes, once). Silent when the address may not sign in."""
    from src.common.config import settings
    from src.schema_engine import engine as schema

    company_id, engine, tenant_key = await _business(tenant)
    async with schema.session(engine) as db:
        app = await _app(db, company_id, app_name)
        if not _allowed_return(app, return_url):
            raise AuthProblem("return_url must be one of the app's own addresses", 400)
        user = await _user(db, app, email)
        if user is None or user.status == "disabled":
            return
        version, key = await signing_key(db, company_id)
    now = int(time.time())
    token = jwt.encode({"aud": f"data-api:{tenant_key}", "sub": f"app_user:{user.id}", "typ": "app_magic",
                        "cid": str(company_id), "tk": tenant_key, "tv": user.token_version,
                        "jti": secrets.token_urlsafe(12), "iat": now,
                        "exp": now + settings.APP_USER_MAGIC_LINK_MINUTES * 60},
                       key, algorithm=ALGORITHM, headers={"kid": f"app:{version}"})
    separator = "&" if "?" in return_url else "?"
    link = f"{return_url}{separator}{urlencode({'hb_magic': token})}"
    await _send_link(user.email, app.display_name, link)


async def _send_link(email: str, app_name: str, link: str) -> None:
    import logging

    from src.common.config import settings
    from src.common.email import email_service

    body = (f"<html><body><p>Sign in to <strong>{app_name}</strong>:</p><p><a href=\"{link}\">Sign in</a></p>"
            "<p>The link works once, for 15 minutes. If you did not ask for it, ignore this e-mail.</p></body></html>")
    sent = await email_service.async_send_email(email, f"Sign in to {app_name}", body)
    if not sent and settings.EMAIL_LINKS_IN_LOG:
        logging.getLogger(__name__).warning("EMAIL_LINKS_IN_LOG: app sign-in link for %s: %s", email, link)


async def verify_magic_link(token: str) -> Dict[str, Any]:
    from src.apps.models import App, AppUser
    from src.schema_engine import engine as schema

    claims, company_id, engine = await _verified(token, expected_type="app_magic")
    try:
        from src.common.redis_client import shared_redis

        first = await shared_redis().set(f"hb:app_magic:{claims['jti']}", "1", nx=True, ex=3600)
        if not first:
            raise AuthProblem("this sign-in link was already used")
    except AuthProblem:
        raise
    except Exception:  # noqa: BLE001 - no Redis: the link's 15 minutes still bound it
        pass
    async with schema.session(engine) as db:
        user = await db.get(AppUser, uuid.UUID(claims["sub"].split(":", 1)[1]))
        if user is None or user.status == "disabled" or user.token_version != claims.get("tv"):
            raise AuthProblem("this sign-in link no longer works")
        if user.status == "invited":
            user.status = "active"
        app = await db.get(App, user.app_id)
        return await _issue(db, user, app, claims["tk"])


async def _verified(token: str, *, expected_type: str) -> Tuple[Dict[str, Any], Any, Any]:
    from src.data_api.app import _pinned
    from src.schema_engine import engine as schema

    try:
        unverified = jwt.get_unverified_claims(token)
        header = jwt.get_unverified_header(token)
    except JWTError:
        raise AuthProblem("invalid token") from None
    if unverified.get("typ") != expected_type:
        raise AuthProblem("invalid token")
    pinned = _pinned()
    if pinned and unverified.get("tk") != pinned:
        raise AuthProblem("the token is for another business")
    kid = str(header.get("kid") or "")
    if not kid.startswith("app:") or not kid[4:].isdigit():
        raise AuthProblem("invalid token")
    company_id = uuid.UUID(str(unverified.get("cid")))
    engine, location = await schema.business_engine(company_id)
    if location.key != unverified.get("tk"):
        raise AuthProblem("the token is for another business")
    async with schema.session(engine) as db:
        _, key = await signing_key(db, company_id, int(kid[4:]))
    try:
        claims = jwt.decode(token, key, algorithms=[ALGORITHM], audience=f"data-api:{location.key}")
    except JWTError as error:
        raise AuthProblem(f"invalid token: {error}") from None
    return claims, company_id, engine


async def caller_for(token: str) -> tokens.Caller:
    """The Data API caller behind an app user's access token."""
    from src.apps.models import AppUser
    from src.schema_engine import engine as schema

    claims, company_id, engine = await _verified(token, expected_type="app_user")
    async with schema.session(engine) as db:
        user = await db.get(AppUser, uuid.UUID(claims["sub"].split(":", 1)[1]))
    if user is None or user.status != "active" or user.token_version != claims.get("tv"):
        raise tokens.Unauthorized("the app user's session ended; sign in again")
    return tokens.Caller(company_id=company_id, tenant_key=claims["tk"], actor=claims["sub"], kind="app_user",
                         objects=tokens.permissions(claims.get("obj") or {}), reports=False, schema="none",
                         own_rows=frozenset(claims.get("own") or []),
                         owner={"id": str(user.id), "email": user.email}, app=claims.get("app"))


async def me(caller: tokens.Caller) -> Dict[str, Any]:
    from src.apps.models import AppUser
    from src.schema_engine import engine as schema

    engine, _ = await schema.business_engine(caller.company_id)
    async with schema.session(engine) as db:
        user = await db.get(AppUser, uuid.UUID(caller.actor.split(":", 1)[1]))
        _, own, roles = await grants_for(db, user)
    return {"id": str(user.id), "email": user.email, "name": user.name, "app": caller.app, "roles": roles,
            "objects": {k: sorted(v) for k, v in caller.objects.items()}, "own_rows": sorted(own)}


# ── Row policies ────────────────────────────────────────────────────────────

DENY = ("", "")


def row_scope(caller: tokens.Caller, blueprint: Dict[str, Any], object_name: str) -> Optional[Tuple[str, str]]:
    """``None``: every row; ``(field, value)``: only rows whose ``field`` is ``value``;
    :data:`DENY`: none (the role is limited to its own rows and the object names no owner field)."""
    if caller.kind != "app_user" or object_name not in caller.own_rows:
        return None
    policy = (blueprint["objects"].get(object_name) or {}).get("row_policy") or {}
    field = policy.get("owner_field")
    if not field:
        return DENY
    return field, (caller.owner or {}).get("email" if policy.get("match", "email") == "email" else "id") or ""

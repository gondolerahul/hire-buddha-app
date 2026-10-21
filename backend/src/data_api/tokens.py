"""Who calls the Data API, and what they may do (tech spec §9.3).

* **User token** — a HireBuddha user's platform session exchanged for a
  15-minute token: owners and admins may do everything (and apply schema
  changes); other people may read, create, update and archive records.
* **Run token** — an agent's run (≤ 2 h): the objects and operations its
  ``capabilities.records`` declares; an agent's schema change waits for a person.
* **App key** — ``hbk_<env>_<tenant key>_<random>``, stored hashed in
  ``api_keys``: the objects and operations of its scopes. (The tenant key in
  the key lets one Data API serve several businesses locally.)

Tokens are JWTs signed by the platform's token signer (W4-1,
``src.common.platform.signing``): HS256 with ``DATA_API_SIGNING_KEY`` locally,
RS256 with the Key Vault key ``data-api-signing`` on Azure, whose public keys
the Data API serves at ``/data/.well-known/jwks.json``. A token's header names
the key that signed it (``kid``); a token signed any other way is refused.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, FrozenSet, Optional, Tuple

from jose import JWTError, jwt

OPERATIONS = ("read", "create", "update", "delete")
ADMIN_ROLES = ("tenant_admin", "partner_admin", "app_admin")
USER_TTL = timedelta(minutes=15)
RUN_TTL = timedelta(hours=2)


class Unauthorized(Exception):
    """No valid credentials (401) — the message says what is wrong."""


@dataclass(frozen=True)
class Caller:
    company_id: uuid.UUID
    tenant_key: str
    actor: str                       # user:<id> | run:<id> | key:<id> | app_user:<id>
    kind: str                        # user | run | key | app_user
    objects: Dict[str, FrozenSet[str]] = field(default_factory=dict)  # object (or *) → operations
    reports: bool = False
    schema: str = "none"             # none | propose | apply
    entity_id: Optional[uuid.UUID] = None
    external: bool = False           # an outside system's key (its own, lower rate)
    # An app user (WS6 6.10): the objects its roles limit to its own rows, who it is, its app.
    own_rows: FrozenSet[str] = frozenset()
    owner: Optional[Dict[str, str]] = None
    app: Optional[str] = None

    def may(self, object_name: str, operation: str) -> bool:
        allowed = self.objects.get(object_name) or self.objects.get("*") or frozenset()
        return operation in allowed

    def readable(self, names: Any) -> list:
        return [n for n in names if self.may(n, "read")]


def permissions(objects: Dict[str, Any]) -> Dict[str, FrozenSet[str]]:
    """``{"contact": ["read", "create"], "*": "*"}`` as object → operations."""
    out = {}
    for name, ops in (objects or {}).items():
        ops = OPERATIONS if ops in ("*", ["*"]) else ops
        out[str(name)] = frozenset(op for op in (ops or []) if op in OPERATIONS)
    return out


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


async def _encode(claims: Dict[str, Any], ttl: timedelta) -> str:
    from src.common.platform.signing import get_signer

    signer = get_signer()
    now = int(time.time())  # not utcnow().timestamp(): a naive datetime is read as local time
    payload = {**claims, "iat": now, "exp": now + int(ttl.total_seconds())}
    kid = await signer.key_id()
    header = {"alg": signer.algorithm, "typ": "JWT", "kid": kid}
    signing_input = (_b64url(json.dumps(header, separators=(",", ":")).encode()) + "."
                     + _b64url(json.dumps(payload, separators=(",", ":"), default=str).encode()))
    signature, signed_by = await signer.sign(signing_input.encode())
    if signed_by != kid:  # the key rotated between reading its id and signing: once more, with the new id
        return await _encode(claims, ttl)
    return f"{signing_input}.{_b64url(signature)}"


async def mint_user_token(user: Any, company_id: Any, tenant_key: str) -> str:
    admin = getattr(user, "role", None) in ADMIN_ROLES
    return await _encode({"aud": f"data-api:{tenant_key}", "sub": f"user:{user.id}", "typ": "user",
                          "cid": str(company_id), "tk": tenant_key, "obj": {"*": list(OPERATIONS)},
                          "rep": True, "sch": "apply" if admin else "none"}, USER_TTL)


def records_capability(entity: Any) -> Dict[str, Any]:
    """An agent's ``capabilities.records``: ``{"objects": {"contact": ["read", …]}, "reports": bool,
    "schema_changes": "none" | "propose"}`` (none when absent)."""
    caps = getattr(entity, "capabilities", None)
    records = (caps or {}).get("records") if isinstance(caps, dict) else None
    return records if isinstance(records, dict) else {}


async def mint_run_token(run_id: Any, entity: Any, company_id: Any, tenant_key: str) -> str:
    records = records_capability(entity)
    schema = "propose" if records.get("schema_changes") == "propose" else "none"
    return await _encode({"aud": f"data-api:{tenant_key}", "sub": f"run:{run_id}", "typ": "run", "cid": str(company_id),
                          "tk": tenant_key, "ent": str(getattr(entity, "id", "")), "obj": records.get("objects") or {},
                          "rep": bool(records.get("reports")), "sch": schema}, RUN_TTL)


async def decode(token: str, *, tenant_key: Optional[str] = None) -> Caller:
    from src.common.platform.signing import get_signer

    signer = get_signer()
    try:
        header = jwt.get_unverified_header(token)
        claims = jwt.get_unverified_claims(token)
        audience = claims.get("aud")
        if tenant_key and audience != f"data-api:{tenant_key}":
            raise Unauthorized("the token is for another business")
        if header.get("alg") != signer.algorithm:
            raise Unauthorized(f"invalid token: signed with {header.get('alg')}, not {signer.algorithm}")
        key = await signer.verification_key(header.get("kid"))
        if key is None:
            raise Unauthorized("invalid token: signed by an unknown key")
        claims = jwt.decode(token, key, algorithms=[signer.algorithm], audience=audience)
    except JWTError as error:
        raise Unauthorized(f"invalid token: {error}") from None
    if not str(claims.get("aud", "")).startswith("data-api:"):
        raise Unauthorized("not a Data API token")
    entity = claims.get("ent")
    return Caller(company_id=uuid.UUID(claims["cid"]), tenant_key=claims["tk"], actor=claims["sub"],
                  kind=claims.get("typ", "user"), objects=permissions(claims.get("obj") or {}),
                  reports=bool(claims.get("rep")), schema=claims.get("sch", "none"),
                  entity_id=uuid.UUID(entity) if entity else None)


# ── App keys ───────────────────────────────────────────────────────────────

def _env() -> str:
    from src.common.config import settings

    return str(getattr(settings, "DATA_API_KEY_ENV", "") or "dev")


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def tenant_of_key(key: str) -> Optional[str]:
    parts = key.split("_", 3)
    return parts[2] if len(parts) == 4 and parts[0] == "hbk" else None


def new_key(tenant_key: str) -> Tuple[str, str]:
    """A new app key and the prefix shown to tell it apart."""
    key = f"hbk_{_env()}_{tenant_key}_{secrets.token_urlsafe(32)}"
    return key, key[: len(f"hbk_{_env()}_{tenant_key}_") + 6]


def validate_scopes(scopes: Any) -> Dict[str, Any]:
    """``{"objects": {"contact": ["create"]}, "reports": false}`` (raises ValueError)."""
    if not isinstance(scopes, dict):
        raise ValueError("scopes is an object")
    objects = scopes.get("objects") or {}
    if not isinstance(objects, dict) or not objects:
        raise ValueError("scopes.objects names at least one object (or *) and its operations")
    for name, ops in objects.items():
        ops = OPERATIONS if ops in ("*", ["*"]) else ops
        if not isinstance(ops, (list, tuple)) or not ops or any(op not in OPERATIONS for op in ops):
            raise ValueError(f"scopes.objects.{name}: operations from {', '.join(OPERATIONS)}")
    return {"objects": {k: (list(OPERATIONS) if v in ("*", ["*"]) else list(v)) for k, v in objects.items()},
            "reports": bool(scopes.get("reports"))}


async def caller_for_key(db: Any, key: str, tenant_key: str, company_id: Any) -> Caller:
    """The caller behind an app key (its last use recorded)."""
    from sqlalchemy import select

    from src.schema_engine.models import ApiKey

    row = (await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash(key)))).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.company_id != company_id:
        raise Unauthorized("unknown or revoked key")
    if (row.scopes or {}).get("public"):
        from src.schema_engine.models import RecordsSettings

        policy = await db.get(RecordsSettings, company_id)
        if not (policy and policy.public_api_access):
            raise Unauthorized("public API access is off for this business (its owner turns it on in settings)")
    row.last_used_at = datetime.utcnow()
    await db.commit()
    scopes = row.scopes or {}
    return Caller(company_id=row.company_id, tenant_key=tenant_key, actor=f"key:{row.id}", kind="key",
                  objects=permissions(scopes.get("objects") or {}), reports=bool(scopes.get("reports")), schema="none",
                  external=bool(row.external))

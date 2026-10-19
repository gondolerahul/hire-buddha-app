"""Envelope encryption of a business's connection secrets (Phase 14 WS5 5.2, tech spec §10.4).

* One **DEK** per business (256 random bits) in ``platform.tenant_keys``,
  wrapped by the business's **KEK** (``src/common/platform/kek``: a local key
  file, or an RSA key in the tenant-keys vault). Unwrapped DEKs are cached in
  memory for ``DEK_CACHE_SECONDS``.
* A secret is a JSON object sealed with AES-256-GCM under the DEK, with the
  row it belongs to (``connection_id``, or a pending result's id) as
  associated data — ciphertext moved to another row does not open.
* **Rotation**: ``rotate_dek`` adds a new version and re-seals every secret
  under it; the old version is retired. **Shredding**: ``shred`` destroys the
  KEK, after which no DEK version — and no secret — opens again.

The KEK's name is ``t-<tenant key>`` for a business with a directory row,
``c-<company hex>`` for one without (one shared database, ``single`` mode).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select, update

__all__ = ["DEK_CACHE_SECONDS", "SecretUnreadable", "kek_name", "open_secret", "rotate_dek", "seal_secret",
           "shred", "forget_cached"]

DEK_CACHE_SECONDS = 600
_NONCE_BYTES = 12
_cache: Dict[Tuple[str, int], Tuple[bytes, float]] = {}


class SecretUnreadable(RuntimeError):
    """A sealed secret that cannot be opened: wrong row, a shredded key, or tampering."""


async def kek_name(company_id: Any) -> str:
    from src.common.platform.kek import tenant_kek_name, validate_key_name
    from src.common.tenancy.directory import directory

    location = await directory.find(company_id)
    if location is not None:
        return tenant_kek_name(location.key)
    return validate_key_name(f"c-{UUID(str(company_id)).hex}")


def forget_cached(company_id: Optional[Any] = None) -> None:
    if company_id is None:
        _cache.clear()
        return
    for key in [k for k in _cache if k[0] == str(company_id)]:
        _cache.pop(key, None)


async def _unwrap(company_id: Any, row: Any) -> bytes:
    from src.common.platform.kek import KeyDestroyed, get_kek

    key = (str(company_id), row.version)
    hit = _cache.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    try:
        dek = await get_kek().unwrap(row.kek_key_id, bytes(row.wrapped_dek))
    except KeyDestroyed as error:
        raise SecretUnreadable(f"the business's key is gone: {error}") from error
    _cache[key] = (dek, time.monotonic() + DEK_CACHE_SECONDS)
    return dek


async def _current_dek(db: Any, company_id: Any) -> Tuple[int, bytes]:
    """The business's current DEK version and key, made on first use."""
    from src.common.platform.kek import get_kek
    from src.connections.models import TenantKey

    row = (await db.execute(
        select(TenantKey).where(TenantKey.company_id == company_id, TenantKey.retired_at.is_(None))
        .order_by(TenantKey.version.desc()).limit(1)
    )).scalar_one_or_none()
    if row is not None:
        return row.version, await _unwrap(company_id, row)
    dek = os.urandom(32)
    wrapped, key_id = await get_kek().wrap(await kek_name(company_id), dek)
    from sqlalchemy.dialects.postgresql import insert

    version = 1 + int((await db.execute(
        select(func.coalesce(func.max(TenantKey.version), 0)).where(TenantKey.company_id == company_id)
    )).scalar())
    created = (await db.execute(
        insert(TenantKey.__table__).values(company_id=company_id, version=version, wrapped_dek=wrapped,
                                           kek_key_id=key_id)
        .on_conflict_do_nothing().returning(TenantKey.__table__.c.version)
    )).first()
    if created is None:  # another process made this version first: use theirs
        return await _current_dek(db, company_id)
    _cache[(str(company_id), version)] = (dek, time.monotonic() + DEK_CACHE_SECONDS)
    return version, dek


async def _dek(db: Any, company_id: Any, version: int) -> bytes:
    from src.connections.models import TenantKey

    row = await db.get(TenantKey, (company_id, version))
    if row is None:
        raise SecretUnreadable(f"no key version {version} for this business")
    return await _unwrap(company_id, row)


def _aad(row_id: Any) -> bytes:
    return str(row_id).encode()


async def seal_secret(db: Any, company_id: Any, row_id: Any, secret: Dict[str, Any]) -> Tuple[int, bytes, bytes]:
    """``(dek_version, nonce, ciphertext)`` of ``secret`` for row ``row_id``."""
    version, dek = await _current_dek(db, company_id)
    nonce = os.urandom(_NONCE_BYTES)
    plaintext = json.dumps(secret, separators=(",", ":"), sort_keys=True).encode()
    return version, nonce, AESGCM(dek).encrypt(nonce, plaintext, _aad(row_id))


async def open_secret(db: Any, company_id: Any, row_id: Any, version: int, nonce: bytes,
                      ciphertext: bytes) -> Dict[str, Any]:
    dek = await _dek(db, company_id, version)
    try:
        plaintext = AESGCM(dek).decrypt(bytes(nonce), bytes(ciphertext), _aad(row_id))
    except InvalidTag as error:
        raise SecretUnreadable("the secret does not open for this row") from error
    return json.loads(plaintext)


async def rotate_dek(db: Any, company_id: Any) -> Dict[str, int]:
    """A new DEK version; every connection secret re-sealed under it; older versions retired.

    Runs in the caller's transaction (commit it). Returns ``{"version", "resealed"}``.
    """
    from src.connections.models import Connection, ConnectionSecret, TenantKey

    rows = (await db.execute(
        select(ConnectionSecret).join(Connection, Connection.id == ConnectionSecret.connection_id)
        .where(Connection.company_id == company_id)
    )).scalars().all()
    opened = [(row, await open_secret(db, company_id, row.connection_id, row.dek_version, row.nonce,
                                      row.ciphertext)) for row in rows]
    # The app-auth keys app users' tokens are signed with (WS6 6.10) are sealed the same way.
    from src.apps.models import AppAuthKey

    app_keys = (await db.execute(select(AppAuthKey).where(AppAuthKey.company_id == company_id))).scalars().all()
    app_opened = [(row, await open_secret(db, company_id, _app_key_aad(company_id, row.version), row.dek_version,
                                          row.nonce, row.ciphertext)) for row in app_keys]
    await db.execute(update(TenantKey).where(TenantKey.company_id == company_id, TenantKey.retired_at.is_(None))
                     .values(retired_at=datetime.utcnow()))
    await db.flush()
    version, _ = await _current_dek(db, company_id)
    for row, secret in opened:
        row.dek_version, row.nonce, row.ciphertext = await seal_secret(db, company_id, row.connection_id, secret)
        row.updated_at = datetime.utcnow()
    for row, secret in app_opened:
        row.dek_version, row.nonce, row.ciphertext = await seal_secret(
            db, company_id, _app_key_aad(company_id, row.version), secret)
    await db.flush()
    return {"version": version, "resealed": len(opened) + len(app_opened)}


def _app_key_aad(company_id: Any, version: int) -> str:
    """What an app-auth key is sealed against (``data_api.app_users``)."""
    return f"app-auth:{company_id}:{version}"


async def shred(company_id: Any) -> None:
    """Destroy the business's KEK: its secrets can never be opened again (offboarding)."""
    from src.common.platform.kek import get_kek

    await get_kek().destroy(await kek_name(company_id))
    forget_cached(company_id)

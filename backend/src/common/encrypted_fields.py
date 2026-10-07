"""Every stored value encrypted with ``common.security.encrypt_api_key`` (AU-24).

``reencrypt_all`` (run by ``scripts/rotate_encryption_key.py``) rewrites exactly
these; ``tests/unit/test_encrypted_fields.py`` fails when a model gains an
encrypted column that is not listed, so a rotation cannot silently skip one.
"""
from __future__ import annotations

import importlib
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select

from src.common.security import decrypt_api_key, encrypt_api_key

# (model module, model class, column)
ENCRYPTED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("src.ai.email_models", "EmailConnection", "encrypted_app_password"),
    ("src.ai.social_models", "SocialConnection", "encrypted_access_token"),
    ("src.ai.social_models", "SocialConnection", "encrypted_refresh_token"),
    ("src.config.models", "IntegrationRegistry", "encrypted_api_key"),
    ("src.gateway.models", "WebhookEndpoint", "secret_encrypted"),
)

# (model module, model class, JSON column, key): a dict of encrypted values
# kept under one key of a JSON column.
ENCRYPTED_JSON: tuple[tuple[str, str, str, str], ...] = (
    ("src.config.models", "IntegrationRegistry", "service_metadata", "secrets_encrypted"),  # Tata
    ("src.ai.social_models", "SocialConnection", "oauth_metadata", "secrets_encrypted"),   # AU-25
)


class RotationError(RuntimeError):
    """A stored value decrypts under neither the old key nor the new one."""


def _rekey(value: str, old: str, new: str, where: str) -> tuple[str, bool]:
    """``value`` under ``new`` in v2, and whether it had to change."""
    if value.startswith("v2:"):
        try:
            decrypt_api_key(value, master=new)
            return value, False          # already v2 under the new key (or an interrupted run)
        except Exception:
            pass
    try:
        plain = decrypt_api_key(value, master=old)
    except Exception:
        try:
            plain = decrypt_api_key(value, master=new)
        except Exception as exc:
            raise RotationError(f"{where}: decrypts under neither key") from exc
    return encrypt_api_key(plain, master=new), True


async def reencrypt_all(db: Any, old_master: str, new_master: str, *,
                        company_id: Optional[UUID] = None) -> dict[str, int]:
    """Re-encrypt every listed value under ``new_master`` (``v2``); flushes, never commits.

    With ``old_master == new_master`` this upgrades pre-AU-24 ciphertexts to v2 in
    place. ``company_id`` limits it to one company (tests). Counts per field.
    """
    counts: dict[str, int] = {}
    for module, name, column in ENCRYPTED_COLUMNS:
        model = getattr(importlib.import_module(module), name)
        query = select(model).where(getattr(model, column).isnot(None))
        if company_id is not None:
            query = query.where(model.company_id == company_id)
        changed = 0
        for row in (await db.execute(query)).scalars().all():
            value, moved = _rekey(getattr(row, column), old_master, new_master,
                                  f"{model.__tablename__}.{column} {row.id}")
            if moved:
                setattr(row, column, value)
                changed += 1
        counts[f"{model.__tablename__}.{column}"] = changed
    for module, name, column, key in ENCRYPTED_JSON:
        model = getattr(importlib.import_module(module), name)
        query = select(model).where(getattr(model, column).isnot(None))
        if company_id is not None:
            query = query.where(model.company_id == company_id)
        changed = 0
        for row in (await db.execute(query)).scalars().all():
            meta = dict(getattr(row, column) or {})
            secrets = dict(meta.get(key) or {})
            if not secrets:
                continue
            moved_any = False
            for k, v in secrets.items():
                if v:
                    secrets[k], moved = _rekey(v, old_master, new_master,
                                               f"{model.__tablename__}.{column}[{key}][{k}] {row.id}")
                    moved_any = moved_any or moved
            if moved_any:
                meta[key] = secrets
                setattr(row, column, meta)       # a new dict, so the change is seen
                changed += 1
        counts[f"{model.__tablename__}.{column}.{key}"] = changed
    await db.flush()
    return counts

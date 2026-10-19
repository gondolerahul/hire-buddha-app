"""A system integration's secret (Phase 14 WS5 5.7, tech spec §10.2).

A registry row's secret is in one of two places:

* ``secret_ref`` — a name in the platform vault, read through the secrets
  adapter (Key Vault on Azure, the environment locally): where every platform
  secret goes (``python -m src.config.move_secrets``);
* ``encrypted_api_key`` — the value encrypted with ``ENCRYPTION_MASTER_KEY``,
  as before, until it is moved.

``registry_secret(entry)`` reads whichever the row has; ``secret_ref`` wins.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def secret_by_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    from src.common.platform.secrets import get_secrets

    return await get_secrets().get(name)


async def registry_secret(entry: Any) -> Optional[str]:
    """The row's secret (its API key, client secret or token), or ``None``."""
    if entry is None:
        return None
    ref = getattr(entry, "secret_ref", None)
    if ref:
        value = await secret_by_name(ref)
        if value is None:
            logger.warning("integration %s: secret %r is not in the vault", getattr(entry, "service_sku", "?"), ref)
        return value
    encrypted = getattr(entry, "encrypted_api_key", None)
    if not encrypted:
        return None
    from src.common.security import decrypt_api_key

    return decrypt_api_key(encrypted)

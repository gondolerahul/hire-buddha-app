"""Tenant key-encryption keys (Phase 14 WS5 5.2, tech spec §10.4).

Each tenant has one **KEK** (``t-<tenant key>``) that never leaves its store;
it wraps the tenant's data-encryption key (DEK), which encrypts the tenant's
connection secrets. Destroying the KEK makes every secret it protected
unreadable (crypto-shredding when a business leaves).

Adapters (``KEK_BACKEND``, default from ``PLATFORM_PROFILE``):

* ``local`` — a random 256-bit key per tenant in a file under
  ``LOCAL_KEK_DIR`` (default ``backend/.local-keys``), AES key wrap
  (RFC 3394). Deleting the file shreds the tenant's secrets on this machine.
* ``azure_keyvault`` — an RSA key per tenant in the tenant-keys vault
  ``AZURE_TENANT_KEYS_VAULT_URL``, wrapped with RSA-OAEP-256, reached with the
  workload identity.
"""
from __future__ import annotations

import re
from typing import Optional, Protocol, Tuple, runtime_checkable

from src.common.platform import AdapterNotAvailable, adapter_name

_KEY_NAME = re.compile(r"^[0-9A-Za-z-]{1,127}$")


class InvalidKeyName(ValueError):
    pass


class KeyDestroyed(LookupError):
    """The tenant's key-encryption key is gone: what it wrapped cannot be opened."""


def validate_key_name(name: str) -> str:
    if not isinstance(name, str) or not _KEY_NAME.match(name):
        raise InvalidKeyName(f"invalid key name {name!r}: letters, digits and hyphens only")
    return name


def tenant_kek_name(tenant_key: str) -> str:
    """The KEK of a tenant: ``t-<tenant key>``."""
    return validate_key_name(f"t-{tenant_key}")


@runtime_checkable
class KeyEncryption(Protocol):
    name: str

    async def ensure_key(self, key_name: str) -> str:
        """Create the key if it does not exist; returns its current key id."""

    async def wrap(self, key_name: str, plaintext_key: bytes) -> Tuple[bytes, str]:
        """``(wrapped, key id)`` of ``plaintext_key`` under the named key."""

    async def unwrap(self, key_id: str, wrapped: bytes) -> bytes:
        """The key ``wrapped`` under ``key_id``; :class:`KeyDestroyed` once that key is gone."""

    async def destroy(self, key_name: str) -> None:
        """Delete the key (and every version of it)."""


_provider: Optional[KeyEncryption] = None


def get_kek() -> KeyEncryption:
    global _provider
    if _provider is None:
        _provider = build_kek(adapter_name("kek"))
    return _provider


def set_kek(provider: Optional[KeyEncryption]) -> None:
    """Replace the process's adapter (tests); ``None`` re-selects from settings."""
    global _provider
    _provider = provider


def build_kek(name: str) -> KeyEncryption:
    from src.common.config import settings

    if name == "local":
        from src.common.platform.kek.local import LocalKeyEncryption

        return LocalKeyEncryption(settings.LOCAL_KEK_DIR or None)
    if name == "azure_keyvault":
        from src.common.platform.kek.azure_keyvault import KeyVaultKeyEncryption

        return KeyVaultKeyEncryption(settings.AZURE_TENANT_KEYS_VAULT_URL,
                                     hardware_protected=settings.TENANT_KEK_HSM)
    raise AdapterNotAvailable(f"KEK_BACKEND={name!r} has no adapter (local, azure_keyvault)")

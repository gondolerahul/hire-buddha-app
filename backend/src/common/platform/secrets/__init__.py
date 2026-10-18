"""Runtime secret lookups by name (Phase 14, tech spec §12.2, §19.3).

Settings reach a process through its environment (in AKS the Key Vault CSI
driver puts them there, ``config._load_settings``). This interface is for
secrets read by name at run time — a system integration's ``secret_ref``
(WS5), a provider app's client secret — so code never holds a vault SDK.

Adapters (``SECRETS_BACKEND``, default from ``PLATFORM_PROFILE``):

* ``env`` — the process environment: ``razorpay-key-id`` is ``RAZORPAY_KEY_ID``.
* ``azure_keyvault`` — Key Vault ``AZURE_KEYVAULT_URL`` with the workload identity.
"""
from __future__ import annotations

import re
import time
from typing import Dict, Optional, Protocol, Tuple, runtime_checkable

from src.common.platform import AdapterNotAvailable, adapter_name

# Key Vault's secret-name rule, used for every adapter so a name works on all.
_SECRET_NAME = re.compile(r"^[0-9A-Za-z-]{1,127}$")
CACHE_SECONDS = 300


class InvalidSecretName(ValueError):
    pass


def validate_secret_name(name: str) -> str:
    if not isinstance(name, str) or not _SECRET_NAME.match(name):
        raise InvalidSecretName(f"invalid secret name {name!r}: letters, digits and hyphens only")
    return name


@runtime_checkable
class SecretsProvider(Protocol):
    name: str

    async def get(self, name: str) -> Optional[str]:
        """The secret's current value, or ``None`` when there is none."""


class CachedSecrets:
    """Wraps an adapter with a short in-process cache: a vault is not asked per call."""

    def __init__(self, inner: SecretsProvider, ttl_seconds: int = CACHE_SECONDS):
        self.inner, self.ttl = inner, ttl_seconds
        self.name = inner.name
        self._values: Dict[str, Tuple[Optional[str], float]] = {}

    async def get(self, name: str) -> Optional[str]:
        validate_secret_name(name)
        hit = self._values.get(name)
        if hit and hit[1] > time.monotonic():
            return hit[0]
        value = await self.inner.get(name)
        self._values[name] = (value, time.monotonic() + self.ttl)
        return value

    def forget(self, name: Optional[str] = None) -> None:
        if name is None:
            self._values.clear()
        else:
            self._values.pop(name, None)


_provider: Optional[CachedSecrets] = None


def get_secrets() -> CachedSecrets:
    global _provider
    if _provider is None:
        _provider = CachedSecrets(build_secrets(adapter_name("secrets")))
    return _provider


def set_secrets(provider: Optional[SecretsProvider]) -> None:
    """Replace the process's provider (tests); ``None`` re-selects from settings."""
    global _provider
    _provider = CachedSecrets(provider) if provider is not None else None


def build_secrets(name: str) -> SecretsProvider:
    from src.common.config import settings

    if name == "env":
        from src.common.platform.secrets.env import EnvSecrets

        return EnvSecrets()
    if name == "azure_keyvault":
        from src.common.platform.secrets.azure_keyvault import KeyVaultSecrets

        return KeyVaultSecrets(settings.AZURE_KEYVAULT_URL)
    raise AdapterNotAvailable(f"SECRETS_BACKEND={name!r} has no adapter (env, azure_keyvault)")

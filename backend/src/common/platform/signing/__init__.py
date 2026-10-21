"""Signing the platform's tokens (Phase 14 W4-1, tech spec §9.3).

Data API user and run tokens are JWTs. Who signs them is an adapter
(``TOKEN_SIGNER``, default from ``PLATFORM_PROFILE``):

* ``hmac`` — HS256 with ``DATA_API_SIGNING_KEY`` (derived from ``SECRET_KEY``
  when unset). Anyone who can check a token can also make one; fine on one
  machine.
* ``azure_keyvault`` — RS256 with the RSA key ``DATA_API_SIGNING_KEY_NAME``
  (default ``data-api-signing``) in the platform vault ``AZURE_KEYVAULT_URL``:
  the private key never leaves Key Vault, which signs each token's digest for
  the workload identity (Key Vault Crypto User); a checker needs only the
  public keys, which the Data API serves as a JWKS
  (``/data/.well-known/jwks.json``).

``kid`` in each token's header names the key version that signed it, so a
rotated key's older tokens still verify while that version is enabled.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from src.common.platform import AdapterNotAvailable, adapter_name


@runtime_checkable
class TokenSigner(Protocol):
    name: str
    algorithm: str

    async def key_id(self) -> str:
        """The ``kid`` of the key that signs now."""

    async def sign(self, signing_input: bytes) -> Tuple[bytes, str]:
        """``(signature, kid)`` over a JWT's ``header.payload``."""

    async def verification_key(self, kid: Optional[str]) -> Any:
        """The key that checks a token signed by ``kid`` (python-jose's ``key``); ``None`` if unknown."""

    async def jwks(self) -> Dict[str, List[Dict[str, Any]]]:
        """The public keys a checker may use (``{"keys": []}`` for a shared secret)."""


class HmacSigner:
    name = "hmac"
    algorithm = "HS256"
    KID = "hs256"

    def _secret(self) -> bytes:
        from src.common.config import settings

        configured = getattr(settings, "DATA_API_SIGNING_KEY", "") or ""
        if configured:
            return configured.encode()
        return hmac.new(settings.SECRET_KEY.encode(), b"data-api", hashlib.sha256).hexdigest().encode()

    async def key_id(self) -> str:
        return self.KID

    async def sign(self, signing_input: bytes) -> Tuple[bytes, str]:
        return hmac.new(self._secret(), signing_input, hashlib.sha256).digest(), self.KID

    async def verification_key(self, kid: Optional[str]) -> Any:
        return self._secret().decode() if kid in (None, self.KID) else None

    async def jwks(self) -> Dict[str, List[Dict[str, Any]]]:
        return {"keys": []}


_signer: Optional[TokenSigner] = None


def get_signer() -> TokenSigner:
    global _signer
    if _signer is None:
        _signer = build_signer(adapter_name("token_signing"))
    return _signer


def set_signer(signer: Optional[TokenSigner]) -> None:
    """Replace the process's signer (tests); ``None`` re-selects from settings."""
    global _signer
    _signer = signer


def build_signer(name: str) -> TokenSigner:
    from src.common.config import settings

    if name == "hmac":
        return HmacSigner()
    if name == "azure_keyvault":
        from src.common.platform.signing.azure_keyvault import KeyVaultSigner

        return KeyVaultSigner(settings.AZURE_KEYVAULT_URL, settings.DATA_API_SIGNING_KEY_NAME)
    raise AdapterNotAvailable(f"TOKEN_SIGNER={name!r} has no adapter (hmac, azure_keyvault)")

"""``azure_keyvault`` token signing: RS256 with an RSA key in the platform vault.

Key Vault signs the SHA-256 digest of each token (``sign`` with RS256); the
private key never leaves it. The public keys of the key's enabled versions are
read once and kept for ``PUBLIC_KEYS_TTL`` (an unknown ``kid`` re-reads them,
at most every ``REFRESH_FLOOR``), so checking a token makes no call.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from typing import Any, Dict, List, Optional, Tuple

from src.common.platform import missing_sdk

try:
    from azure.keyvault.keys.aio import KeyClient
    from azure.keyvault.keys.crypto import SignatureAlgorithm
    from azure.keyvault.keys.crypto.aio import CryptographyClient
except ImportError:  # pragma: no cover - exercised only where the SDK is absent
    KeyClient = None  # type: ignore[assignment,misc]

PUBLIC_KEYS_TTL = 600.0
REFRESH_FLOOR = 30.0
MAX_VERSIONS = 5


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def public_jwk(kid: str, n: bytes, e: bytes) -> Dict[str, Any]:
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": _b64url(n), "e": _b64url(e)}


class KeyVaultSigner:
    name = "azure_keyvault"
    algorithm = "RS256"

    def __init__(self, vault_url: str, key_name: str):
        if KeyClient is None:
            raise missing_sdk("azure_keyvault", "azure-keyvault-keys", "TOKEN_SIGNER")
        if not vault_url:
            raise ValueError("azure_keyvault token signing needs AZURE_KEYVAULT_URL")
        self._vault_url = vault_url
        self._key_name = key_name or "data-api-signing"
        self._keys: Dict[str, Dict[str, Any]] = {}
        self._current: Optional[str] = None
        self._read_at = 0.0
        self._credentials: Dict[int, Any] = {}

    def _credential(self) -> Any:
        loop_id = id(asyncio.get_running_loop())
        credential = self._credentials.get(loop_id)
        if credential is None:
            from azure.identity.aio import DefaultAzureCredential

            credential = DefaultAzureCredential()
            self._credentials[loop_id] = credential
        return credential

    async def _read_public_keys(self) -> None:
        async with KeyClient(self._vault_url, credential=self._credential()) as client:
            current = await client.get_key(self._key_name)
            keys = {current.id: public_jwk(current.id, current.key.n, current.key.e)}
            versions = [v async for v in client.list_properties_of_key_versions(self._key_name)]
            versions = sorted((v for v in versions if v.enabled and v.id != current.id),
                              key=lambda v: v.created_on or 0, reverse=True)[:MAX_VERSIONS - 1]
            for props in versions:
                older = await client.get_key(self._key_name, version=props.version)
                keys[older.id] = public_jwk(older.id, older.key.n, older.key.e)
        self._keys, self._current, self._read_at = keys, current.id, time.monotonic()

    async def _fresh(self, *, unknown_kid: bool = False) -> None:
        age = time.monotonic() - self._read_at
        if not self._keys or age > PUBLIC_KEYS_TTL or (unknown_kid and age > REFRESH_FLOOR):
            await self._read_public_keys()

    async def key_id(self) -> str:
        await self._fresh()
        return self._current or ""

    async def sign(self, signing_input: bytes) -> Tuple[bytes, str]:
        await self._fresh()
        kid = self._current or ""
        async with CryptographyClient(kid, credential=self._credential()) as crypto:
            result = await crypto.sign(SignatureAlgorithm.rs256, hashlib.sha256(signing_input).digest())
        return result.signature, kid

    async def verification_key(self, kid: Optional[str]) -> Any:
        if not kid:
            return None
        await self._fresh()
        if kid not in self._keys:
            await self._fresh(unknown_kid=True)
        return self._keys.get(kid)

    async def jwks(self) -> Dict[str, List[Dict[str, Any]]]:
        await self._fresh()
        return {"keys": list(self._keys.values())}

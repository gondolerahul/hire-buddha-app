"""``azure_keyvault`` key-encryption keys: an RSA key per tenant in the tenant-keys vault.

The key never leaves Key Vault: ``wrapKey`` / ``unwrapKey`` with RSA-OAEP-256.
``destroy`` deletes it (soft delete; with purge protection it is purged after
the vault's retention period, after which what it wrapped is unrecoverable).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Tuple

from src.common.platform import missing_sdk
from src.common.platform.kek import KeyDestroyed, validate_key_name

try:
    from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
    from azure.keyvault.keys.aio import KeyClient
    from azure.keyvault.keys.crypto import KeyWrapAlgorithm
    from azure.keyvault.keys.crypto.aio import CryptographyClient
except ImportError:  # pragma: no cover - exercised only where the SDK is absent
    KeyClient = None  # type: ignore[assignment,misc]

RSA_KEY_SIZE = 3072


class KeyVaultKeyEncryption:
    name = "azure_keyvault"

    def __init__(self, vault_url: str, *, hardware_protected: bool = False):
        if KeyClient is None:
            raise missing_sdk("azure_keyvault", "azure-keyvault-keys", "KEK_BACKEND")
        if not vault_url:
            raise ValueError("azure_keyvault key encryption needs AZURE_TENANT_KEYS_VAULT_URL")
        self._vault_url = vault_url
        self._hsm = hardware_protected
        self._clients: Dict[int, Any] = {}

    def _credential(self) -> Any:
        from azure.identity.aio import DefaultAzureCredential

        return DefaultAzureCredential()

    def _client(self) -> Any:
        loop_id = id(asyncio.get_running_loop())
        client = self._clients.get(loop_id)
        if client is None:
            client = KeyClient(self._vault_url, credential=self._credential())
            self._clients[loop_id] = client
        return client

    async def ensure_key(self, key_name: str) -> str:
        client = self._client()
        try:
            key = await client.get_key(validate_key_name(key_name))
        except ResourceNotFoundError:
            key = await client.create_rsa_key(key_name, size=RSA_KEY_SIZE, hardware_protected=self._hsm,
                                              key_operations=["wrapKey", "unwrapKey"])
        return key.id

    async def wrap(self, key_name: str, plaintext_key: bytes) -> Tuple[bytes, str]:
        key_id = await self.ensure_key(key_name)
        async with CryptographyClient(key_id, credential=self._credential()) as crypto:
            result = await crypto.wrap_key(KeyWrapAlgorithm.rsa_oaep_256, plaintext_key)
        return result.encrypted_key, key_id

    async def unwrap(self, key_id: str, wrapped: bytes) -> bytes:
        try:
            async with CryptographyClient(key_id, credential=self._credential()) as crypto:
                result = await crypto.unwrap_key(KeyWrapAlgorithm.rsa_oaep_256, wrapped)
        except (ResourceNotFoundError, HttpResponseError) as error:
            if isinstance(error, ResourceNotFoundError) or getattr(error, "status_code", None) in (403, 404):
                raise KeyDestroyed(f"key {key_id} is gone or not usable: {error}") from error
            raise
        return result.key

    async def destroy(self, key_name: str) -> None:
        try:
            poller = await self._client().begin_delete_key(validate_key_name(key_name))
            await poller.wait()
        except ResourceNotFoundError:
            return

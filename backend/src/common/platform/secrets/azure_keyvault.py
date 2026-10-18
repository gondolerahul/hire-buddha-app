"""``azure_keyvault`` secrets: one Key Vault, reached with the workload identity."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from src.common.platform import missing_sdk
from src.common.platform.secrets import validate_secret_name

try:
    from azure.core.exceptions import ResourceNotFoundError
    from azure.keyvault.secrets.aio import SecretClient
except ImportError:  # pragma: no cover - exercised only where the SDK is absent
    SecretClient = None  # type: ignore[assignment,misc]


class KeyVaultSecrets:
    name = "azure_keyvault"

    def __init__(self, vault_url: str):
        if SecretClient is None:
            raise missing_sdk("azure_keyvault", "azure-keyvault-secrets", "SECRETS_BACKEND")
        if not vault_url:
            raise ValueError("azure_keyvault secrets need AZURE_KEYVAULT_URL")
        self._vault_url = vault_url
        self._clients: Dict[int, Any] = {}

    def _client(self) -> Any:
        loop_id = id(asyncio.get_running_loop())
        client = self._clients.get(loop_id)
        if client is None:
            from azure.identity.aio import DefaultAzureCredential

            client = SecretClient(self._vault_url, credential=DefaultAzureCredential())
            self._clients[loop_id] = client
        return client

    async def get(self, name: str) -> Optional[str]:
        try:
            secret = await self._client().get_secret(validate_secret_name(name))
        except ResourceNotFoundError:
            return None
        return secret.value or None

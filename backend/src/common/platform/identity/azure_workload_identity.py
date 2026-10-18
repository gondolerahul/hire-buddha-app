"""``azure_workload_identity``: Entra tokens from ``DefaultAzureCredential``.

In AKS the pod's service account is federated to a user-assigned managed
identity (``azure.workload.identity/use: "true"``); on a laptop the same
credential falls back to ``az login``. The async credential caches each token
and refreshes it before it expires; synchronous callers (a database driver's
connect hook) get a token cached here until five minutes before its expiry.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Dict, Tuple

from src.common.platform import missing_sdk

try:
    from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
    from azure.identity.aio import DefaultAzureCredential
except ImportError:  # pragma: no cover - exercised only where the SDK is absent
    DefaultAzureCredential = SyncDefaultAzureCredential = None  # type: ignore[assignment,misc]

REFRESH_BEFORE_EXPIRY_SECONDS = 300


class AzureWorkloadIdentity:
    name = "azure_workload_identity"

    def __init__(self) -> None:
        if DefaultAzureCredential is None:
            raise missing_sdk("azure_workload_identity", "azure-identity", "WORKLOAD_IDENTITY_BACKEND")
        # aio credentials hold an HTTP session bound to the loop they first ran on.
        self._credentials: Dict[int, Any] = {}
        self._sync_credential: Any = None
        self._sync_tokens: Dict[str, Tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _credential(self) -> Any:
        loop_id = id(asyncio.get_running_loop())
        credential = self._credentials.get(loop_id)
        if credential is None:
            credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            self._credentials[loop_id] = credential
        return credential

    async def token(self, scope: str) -> str:
        return (await self._credential().get_token(scope)).token

    def sync_token(self, scope: str) -> str:
        with self._lock:
            cached = self._sync_tokens.get(scope)
            if cached and cached[1] - REFRESH_BEFORE_EXPIRY_SECONDS > time.time():
                return cached[0]
            if self._sync_credential is None:
                self._sync_credential = SyncDefaultAzureCredential(exclude_interactive_browser_credential=True)
            access = self._sync_credential.get_token(scope)
            self._sync_tokens[scope] = (access.token, float(access.expires_on))
            return access.token

"""Workload identity to other services (Phase 14, tech spec §12.2, §19.3).

A bearer token for a service scope — Azure OpenAI, Claude on Microsoft
Foundry, Key Vault — obtained from the workload's own identity, so no API key
is stored anywhere (P-07). Callers get a token *provider*: an async callable
returning a current token, which SDKs call per request (the adapter caches
and refreshes the token).

Adapters (``WORKLOAD_IDENTITY_BACKEND``, default from ``PLATFORM_PROFILE``):

* ``azure_workload_identity`` — ``DefaultAzureCredential``: the pod's AKS
  workload identity, or ``az login`` on a developer laptop.
* ``none`` — no workload identity; a caller that needs one is told to store a
  key or choose an adapter.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Dict, Optional, Protocol, runtime_checkable

from src.common.platform import AdapterNotAvailable, adapter_name

# Microsoft Entra scope for Azure AI services (Azure OpenAI, Foundry models).
COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"

TokenProvider = Callable[[], Awaitable[str]]


@runtime_checkable
class WorkloadTokenSource(Protocol):
    name: str

    async def token(self, scope: str) -> str:
        """A current bearer token for ``scope``."""

    def sync_token(self, scope: str) -> str:
        """The same, for synchronous callers (a database driver's connect hook).
        Blocks only when the cached token is near expiry."""


class NoWorkloadIdentity:
    name = "none"

    async def token(self, scope: str) -> str:
        raise self._error(scope)

    def sync_token(self, scope: str) -> str:
        raise self._error(scope)

    @staticmethod
    def _error(scope: str) -> AdapterNotAvailable:
        return AdapterNotAvailable(
            f"no workload identity on this deployment to get a token for {scope}: store an API "
            "key or password, or set WORKLOAD_IDENTITY_BACKEND=azure_workload_identity")


_source: Optional[WorkloadTokenSource] = None


def get_token_source() -> WorkloadTokenSource:
    global _source
    if _source is None:
        _source = build_token_source(adapter_name("workload_identity"))
    return _source


def set_token_source(source: Optional[WorkloadTokenSource]) -> None:
    """Replace the process's token source (tests); ``None`` re-selects from settings."""
    global _source
    _source = source


def build_token_source(name: str) -> WorkloadTokenSource:
    if name == "none":
        return NoWorkloadIdentity()
    if name == "azure_workload_identity":
        from src.common.platform.identity.azure_workload_identity import AzureWorkloadIdentity

        return AzureWorkloadIdentity()
    raise AdapterNotAvailable(
        f"WORKLOAD_IDENTITY_BACKEND={name!r} has no adapter (azure_workload_identity, none)")


_providers: Dict[str, TokenProvider] = {}


def sync_token(scope: str) -> str:
    """A current token for ``scope``, synchronously."""
    return get_token_source().sync_token(scope)


def token_provider(scope: str = COGNITIVE_SERVICES_SCOPE) -> TokenProvider:
    """An async callable returning a current token for ``scope``."""
    provider = _providers.get(scope)
    if provider is None:
        async def provider() -> str:
            return await get_token_source().token(scope)

        _providers[scope] = provider
    return provider

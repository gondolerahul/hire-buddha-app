"""Provider adapters by the catalog's ``provider`` (Phase 14 WS5 5.4)."""
from __future__ import annotations

from typing import Dict

from src.connections.providers.base import Account, AccessToken, Provider, ProviderError
from src.connections.providers.forms import ApiKeyProvider, MailboxProvider, McpProvider
from src.connections.providers.github import GitHubAppProvider
from src.connections.providers.meta import MetaProvider
from src.connections.providers.oauth import GoogleProvider, LinkedInProvider, MicrosoftProvider, XProvider

__all__ = ["Account", "AccessToken", "Provider", "ProviderError", "provider_for"]

PROVIDERS: Dict[str, Provider] = {
    "meta": MetaProvider(),
    "linkedin": LinkedInProvider(),
    "google": GoogleProvider(),
    "microsoft": MicrosoftProvider(),
    "x": XProvider(),
    "github": GitHubAppProvider(),
    "mailbox": MailboxProvider(),
    "hubspot": ApiKeyProvider(),
    "generic": ApiKeyProvider(),
    "mcp": McpProvider(),
}


def provider_for(name: str) -> Provider:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ProviderError(f"no adapter for provider {name!r}") from None

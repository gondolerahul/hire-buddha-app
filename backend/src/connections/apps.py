"""HireBuddha's own apps with providers (Phase 14 WS5 5.1, 5.7; tech spec §10.2).

A business connects *through* HireBuddha's app: one registered with Meta,
LinkedIn, Google, Microsoft, X and GitHub (task 5.9, outside the code). Each
is a system-integration row of the platform company, category ``OAUTH_APP``,
``service_sku`` = the catalog's ``oauth_app_ref`` (``oauth-app-meta`` …):

* ``service_metadata``: non-secret settings — ``client_id`` (Meta: the app id),
  ``app_slug`` and ``app_id`` (GitHub), ``config_id`` (WhatsApp Embedded
  Signup), ``tenant`` (Microsoft), ``graph_version`` (Meta) — and the names of
  further secrets in the vault: ``webhook_secret_ref`` (GitHub),
  ``private_key_ref`` (GitHub App key), ``verify_token_ref`` (Meta's webhook
  verification);
* the client secret: ``secret_ref`` (the vault) or ``encrypted_api_key``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from sqlalchemy import select


class AppNotConfigured(LookupError):
    """HireBuddha has no app with this provider on this environment yet."""


@dataclass(frozen=True)
class ProviderApp:
    ref: str
    client_id: str
    client_secret: Optional[str]
    settings: Dict[str, Any] = field(default_factory=dict)
    secrets: Dict[str, Optional[str]] = field(default_factory=dict)

    def secret(self, name: str) -> Optional[str]:
        return self.secrets.get(name)


_overrides: Dict[str, ProviderApp] = {}


def set_app(app: Optional[ProviderApp], ref: Optional[str] = None) -> None:
    """Tests: use ``app`` for its ref (``None`` with ``ref`` removes it)."""
    if app is None:
        _overrides.pop(ref or "", None)
    else:
        _overrides[app.ref] = app


async def provider_app(db: Any, ref: str) -> ProviderApp:
    if ref in _overrides:
        return _overrides[ref]
    from src.auth.platform import platform_company_id
    from src.config.models import IntegrationRegistry, ServiceCategory
    from src.config.registry_secrets import registry_secret, secret_by_name

    platform = await platform_company_id(db)
    row = (await db.execute(select(IntegrationRegistry).where(
        IntegrationRegistry.company_id == platform, IntegrationRegistry.service_sku == ref,
        IntegrationRegistry.service_category == ServiceCategory.OAUTH_APP.value,
        IntegrationRegistry.status == "active",
    ))).scalar_one_or_none()
    if row is None:
        raise AppNotConfigured(f"HireBuddha's app {ref!r} is not registered on this environment")
    metadata = dict(row.service_metadata or {})
    secrets = {key[: -len("_ref")]: await secret_by_name(value)
               for key, value in metadata.items() if key.endswith("_ref") and value}
    settings = {key: value for key, value in metadata.items() if not key.endswith("_ref")}
    client_id = str(settings.get("client_id") or settings.get("app_id") or "")
    if not client_id:
        raise AppNotConfigured(f"app {ref!r} has no client_id in its service_metadata")
    return ProviderApp(ref=ref, client_id=client_id, client_secret=await registry_secret(row),
                       settings=settings, secrets=secrets)

"""A tenant's own Azure identity (Phase 14 M2, tech spec §5.2, §6.2 identity_ready).

``id-<prefix>-<env>-t-<key>`` (``TENANT_IDENTITY_NAME_PREFIX`` + key), a
user-assigned managed identity in ``TENANT_IDENTITY_RESOURCE_GROUP``, federated
to the service account ``t-<key>/data-api`` on the cluster's OIDC issuer: the
tenant's Data API signs in to its database (``hb_dataapi``) as it. Made by the
provisioner through Azure Resource Manager with its own workload identity,
which may manage identities in that resource group only (Bicep slice 2).
Both calls are PUTs: running the step again changes nothing.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

ARM = "https://management.azure.com"
ARM_SCOPE = f"{ARM}/.default"
API_VERSION = "2023-01-31"
TOKEN_AUDIENCE = "api://AzureADTokenExchange"


class TenantIdentityError(RuntimeError):
    """Azure refused to make or federate the tenant's identity."""


def identity_name(tenant_key: str) -> str:
    from src.common.config import settings

    prefix = settings.TENANT_IDENTITY_NAME_PREFIX
    if not prefix:
        raise TenantIdentityError("TENANT_IDENTITY_NAME_PREFIX is not set")
    return f"{prefix}{tenant_key}"


def _path(name: str) -> str:
    from src.common.config import settings

    missing = [k for k in ("AZURE_SUBSCRIPTION_ID", "TENANT_IDENTITY_RESOURCE_GROUP", "AZURE_LOCATION",
                           "AKS_OIDC_ISSUER") if not getattr(settings, k)]
    if missing:
        raise TenantIdentityError(f"identity_ready needs {', '.join(missing)}")
    return (f"/subscriptions/{settings.AZURE_SUBSCRIPTION_ID}/resourceGroups/"
            f"{settings.TENANT_IDENTITY_RESOURCE_GROUP}/providers/Microsoft.ManagedIdentity/"
            f"userAssignedIdentities/{name}")


async def _arm(client: httpx.AsyncClient, token: str, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    response = await client.put(path, params={"api-version": API_VERSION}, json=body,
                                headers={"Authorization": f"Bearer {token}"})
    if response.status_code >= 400:
        raise TenantIdentityError(f"PUT {path.rsplit('/', 2)[-2]}/{path.rsplit('/', 1)[-1]}: "
                                  f"{response.status_code} {response.text[:300]}")
    return response.json() if response.content else {}


async def ensure_tenant_identity(tenant_key: str, *,
                                 transport: Optional[httpx.AsyncBaseTransport] = None) -> Dict[str, Any]:
    """The identity and its federated credential; ``{name, principal_id, client_id, subject}``."""
    from src.common.config import settings
    from src.common.platform.identity import get_token_source

    name = identity_name(tenant_key)
    path = _path(name)
    subject = f"system:serviceaccount:t-{tenant_key}:data-api"
    token = await get_token_source().token(ARM_SCOPE)
    async with httpx.AsyncClient(base_url=ARM, transport=transport, timeout=60) as client:
        identity = await _arm(client, token, path, {
            "location": settings.AZURE_LOCATION,
            "tags": {"app": "hirebuddha", "tenant": tenant_key, "made-by": "provisioner"},
        })
        await _arm(client, token, f"{path}/federatedIdentityCredentials/data-api", {
            "properties": {"issuer": settings.AKS_OIDC_ISSUER, "subject": subject, "audiences": [TOKEN_AUDIENCE]},
        })
    properties = identity.get("properties") or {}
    if not properties.get("principalId"):
        raise TenantIdentityError(f"{name}: Azure returned no principalId")
    return {"name": name, "principal_id": properties["principalId"], "client_id": properties.get("clientId"),
            "subject": subject}


async def delete_tenant_identity(tenant_key: str, *,
                                 transport: Optional[httpx.AsyncBaseTransport] = None) -> bool:
    """Delete the tenant's identity (its federated credential goes with it) when the business is
    erased (docs/phase15/13 §6 step 10); ``False`` when it was already gone."""
    from src.common.platform.identity import get_token_source

    path = _path(identity_name(tenant_key))
    token = await get_token_source().token(ARM_SCOPE)
    async with httpx.AsyncClient(base_url=ARM, transport=transport, timeout=60) as client:
        response = await client.delete(path, params={"api-version": API_VERSION},
                                       headers={"Authorization": f"Bearer {token}"})
    if response.status_code == 204 or response.status_code == 404:
        return False if response.status_code == 404 else True
    if response.status_code >= 400:
        raise TenantIdentityError(f"DELETE {path.rsplit('/', 1)[-1]}: {response.status_code} {response.text[:300]}")
    return True


async def tenant_identity_exists(tenant_key: str, *, transport: Optional[httpx.AsyncBaseTransport] = None) -> bool:
    from src.common.platform.identity import get_token_source

    path = _path(identity_name(tenant_key))
    token = await get_token_source().token(ARM_SCOPE)
    async with httpx.AsyncClient(base_url=ARM, transport=transport, timeout=60) as client:
        response = await client.get(path, params={"api-version": API_VERSION},
                                    headers={"Authorization": f"Bearer {token}"})
    return response.status_code == 200

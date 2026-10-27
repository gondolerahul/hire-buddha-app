"""Removing a business's workspace — the provisioner's steps in reverse (docs/phase15/13 §6 steps 5–11).

Each function takes the business (``Workspace``) and returns what it found and
removed; running one again removes nothing new and succeeds. What a profile
does not have (no cluster, no Azure identity on this machine) is skipped with
the reason, as provisioning skips it.

| Step | Removes |
|---|---|
| ``apps_removed`` | the business's Git repositories and their owner (``t-<key>`` / ``c-<hex>``), its app images (Azure Container Registry repositories ``t-<key>/…``) |
| ``namespace_deleted`` | the cluster namespace ``t-<key>`` and everything in it (apps, previews, Data API, secrets) |
| ``storage_deleted`` | the storage namespaces ``t-<key>`` and ``c-<company hex>``, every object and version |
| ``database_dropped`` | the tenant database ``t_<key>`` and the tenant's own sign-in role |
| ``identity_deleted`` | the tenant's managed identity and its federated credential |
| ``key_deleted`` | the tenant KEK — last, so everything before it could still decrypt (crypto-shredding) |
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from sqlalchemy import text

logger = logging.getLogger(__name__)

NAMESPACE_GONE_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class Workspace:
    """What the workspace steps need to know about the business."""
    company_id: UUID
    tenant_key: Optional[str] = None          # None: the company never had a tenant of its own
    db_name: Optional[str] = None
    server_host: Optional[str] = None

    @property
    def legacy_namespace(self) -> str:
        return f"c-{uuid.UUID(str(self.company_id)).hex}"

    @property
    def git_owners(self) -> List[str]:
        owners = [f"c-{uuid.UUID(str(self.company_id)).hex[:12]}"]
        if self.tenant_key:
            owners.insert(0, f"t-{self.tenant_key}")
        return owners

    @property
    def storage_namespaces(self) -> List[str]:
        names = [self.legacy_namespace]
        if self.tenant_key:
            names.insert(0, f"t-{self.tenant_key}")
        return names


async def workspace_of(db: Any, company_id: UUID) -> Workspace:
    """The business's workspace, as its tenant directory row names it."""
    from src.common.tenancy.models import TenantDbServer, TenantDirectoryEntry

    entry = await db.get(TenantDirectoryEntry, company_id)
    if entry is None:
        return Workspace(company_id=company_id)
    server = await db.get(TenantDbServer, entry.server_id) if entry.server_id else None
    return Workspace(company_id=company_id, tenant_key=entry.tenant_key, db_name=entry.db_name,
                     server_host=server.host if server else None)


def _profile() -> str:
    from src.common.platform import platform_profile
    return platform_profile()


# ── apps: Git and images ────────────────────────────────────────────────────

async def apps_removed(ws: Workspace) -> Dict[str, Any]:
    from src.code_lanes.git import builtin_provider

    detail: Dict[str, Any] = {"repositories": 0, "owners": [], "images": 0}
    try:
        git = builtin_provider()
    except Exception as exc:  # noqa: BLE001 - no built-in Git configured here
        detail["git"] = f"skipped: {exc}"
        git = None
    if git is not None:
        try:
            for owner in ws.git_owners:
                count = await git.delete_owner(owner)
                if count:
                    detail["owners"].append(owner)
                detail["repositories"] += count
        except httpx.ConnectError as exc:
            # A deployment without its Gitea (Azure prod before the tenant runtime) has no repositories
            # to delete; one the business recorded means a Gitea that should be there is not answering.
            if await _has_repos(ws):
                raise
            detail["git"] = f"skipped: built-in Git unreachable, no repositories on record ({exc})"
    detail["images"] = await _delete_images(ws)
    return detail


async def _has_repos(ws: Workspace) -> bool:
    """Whether the business recorded a built-in Git repository (its database still exists at this step)."""
    from src.common.tenancy.session import tenant_session

    try:
        async with tenant_session(ws.company_id) as tdb:
            return bool((await tdb.execute(text(
                "SELECT count(*) FROM git_repos WHERE company_id = :c AND provider = 'builtin'"),
                {"c": ws.company_id})).scalar())
    except Exception:  # noqa: BLE001 - no database or no table: nothing was recorded here
        return False


async def _delete_images(ws: Workspace) -> Any:
    """The business's app images in the apps registry (``t-<key>/<app>``); a count, or why not."""
    from src.common.config import settings

    registry = getattr(settings, "ACR_LOGIN_SERVER", "") or (
        f"{settings.ACR_REGISTRY_NAME}.azurecr.io" if getattr(settings, "ACR_REGISTRY_NAME", "") else "")
    if not registry or not ws.tenant_key:
        return "skipped: no apps registry"
    if not await _has_builds(ws):
        return "none built"
    from src.common.platform.identity import get_token_source

    aad = await get_token_source().token("https://management.azure.com/.default")
    async with httpx.AsyncClient(base_url=f"https://{registry}", timeout=60) as client:
        exchanged = await client.post("/oauth2/exchange", data={
            "grant_type": "access_token", "service": registry, "access_token": aad})
        exchanged.raise_for_status()
        refresh = exchanged.json()["refresh_token"]
        token = await client.post("/oauth2/token", data={
            "grant_type": "refresh_token", "service": registry, "refresh_token": refresh,
            "scope": "registry:catalog:* repository:*:*"})
        token.raise_for_status()
        headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
        catalog = await client.get("/acr/v1/_catalog", params={"n": 1000}, headers=headers)
        catalog.raise_for_status()
        prefixes = (f"t-{ws.tenant_key}/", f"hb-apps/t-{ws.tenant_key}/")
        mine = [r for r in catalog.json().get("repositories", []) if r.startswith(prefixes)]
        for repository in mine:
            gone = await client.delete(f"/acr/v1/{repository}", headers=headers)
            if gone.status_code not in (202, 204, 404):
                raise RuntimeError(f"registry delete {repository}: {gone.status_code} {gone.text[:200]}")
    return len(mine)


async def _has_builds(ws: Workspace) -> bool:
    """Whether the business ever built an app image (its database still exists at this step)."""
    from src.common.tenancy.session import tenant_session

    try:
        async with tenant_session(ws.company_id) as tdb:
            return bool((await tdb.execute(text("SELECT count(*) FROM app_builds WHERE company_id = :c"),
                                           {"c": ws.company_id})).scalar())
    except Exception:  # noqa: BLE001 - no database or no table: nothing was built here
        return False


# ── the cluster namespace ───────────────────────────────────────────────────

def _has_cluster() -> bool:
    from src.common.config import settings
    return not (_profile() == "local" and not settings.KUBE_API_URL)


async def namespace_deleted(ws: Workspace) -> Dict[str, Any]:
    if not ws.tenant_key:
        return {"skipped": "no tenant"}
    if not _has_cluster():
        return {"skipped": "no Kubernetes on this machine"}
    from src.common.platform.kube import get_kube, path_for

    kube = get_kube()
    path = path_for("Namespace", name=f"t-{ws.tenant_key}")
    existed = await kube.find(path) is not None
    if existed:
        await kube.delete(path)
    deadline = time.monotonic() + NAMESPACE_GONE_TIMEOUT_SECONDS
    while await kube.find(path) is not None:
        if time.monotonic() > deadline:
            raise TimeoutError(f"namespace t-{ws.tenant_key} still terminating after "
                               f"{NAMESPACE_GONE_TIMEOUT_SECONDS} s")
        await asyncio.sleep(5)
    return {"namespace": f"t-{ws.tenant_key}", "deleted": existed}


async def namespace_exists(ws: Workspace) -> bool:
    if not ws.tenant_key or not _has_cluster():
        return False
    from src.common.platform.kube import get_kube, path_for
    return await get_kube().find(path_for("Namespace", name=f"t-{ws.tenant_key}")) is not None


# ── storage ─────────────────────────────────────────────────────────────────

async def storage_deleted(ws: Workspace) -> Dict[str, Any]:
    from src.common.platform.storage import get_storage

    storage = get_storage()
    return {namespace: await storage.delete_namespace(namespace) for namespace in ws.storage_namespaces}


async def storage_left(ws: Workspace) -> Dict[str, int]:
    from src.common.platform.storage import get_storage

    storage = get_storage()
    left = {}
    for namespace in ws.storage_namespaces:
        keys = await storage.list(f"{namespace}/")
        if keys:
            left[namespace] = len(keys)
    return left


# ── the tenant database ─────────────────────────────────────────────────────

def _admin_engine(ws: Workspace, database: str = "postgres") -> Any:
    from src.common.tenancy.provisioner import Tenant, _admin_url, _engine

    tenant = Tenant(company_id=ws.company_id, key=ws.tenant_key or "", db_name=ws.db_name or "",
                    server_host=ws.server_host or "")
    return _engine(_admin_url(tenant, database))


async def database_dropped(ws: Workspace) -> Dict[str, Any]:
    if not (ws.tenant_key and ws.db_name and ws.server_host):
        return {"skipped": "no tenant database"}
    from src.common.tenancy import db_roles

    engine = _admin_engine(ws)
    try:
        async with engine.connect() as conn:
            existed = (await conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"),
                                          {"d": ws.db_name})).first() is not None
            if existed:
                await conn.execute(text(f'DROP DATABASE "{ws.db_name}" WITH (FORCE)'))
            role = None
            if _profile() != "local":
                from src.common.tenancy.azure_identity import identity_name
                role = identity_name(ws.tenant_key)
                await db_roles.drop_tenant_principal(conn, role)
    finally:
        await engine.dispose()
    return {"database": ws.db_name, "dropped": existed, "role": role}


async def database_exists(ws: Workspace) -> bool:
    if not (ws.db_name and ws.server_host):
        return False
    engine = _admin_engine(ws)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"),
                                       {"d": ws.db_name})).first() is not None
    finally:
        await engine.dispose()


# ── identity and key ────────────────────────────────────────────────────────

async def identity_deleted(ws: Workspace) -> Dict[str, Any]:
    if not ws.tenant_key:
        return {"skipped": "no tenant"}
    if _profile() == "local":
        return {"skipped": "no tenant identity on this machine"}
    from src.common.tenancy.azure_identity import delete_tenant_identity, identity_name
    return {"identity": identity_name(ws.tenant_key), "deleted": await delete_tenant_identity(ws.tenant_key)}


async def identity_exists(ws: Workspace) -> bool:
    if not ws.tenant_key or _profile() == "local":
        return False
    from src.common.tenancy.azure_identity import tenant_identity_exists
    return await tenant_identity_exists(ws.tenant_key)


async def key_deleted(ws: Workspace) -> Dict[str, Any]:
    if not ws.tenant_key:
        return {"skipped": "no tenant"}
    from src.common.platform.kek import get_kek, tenant_kek_name

    name = tenant_kek_name(ws.tenant_key)
    await get_kek().destroy(name)
    return {"key": name, "deleted": True,
            "note": "a vault with purge protection keeps it soft-deleted and unusable until its retention ends"}

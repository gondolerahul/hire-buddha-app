"""Provisioning a tenant (Phase 14 WS2 2.8, tech spec §6.2).

    python -m src.common.tenancy.provisioner add-server NAME HOST [--kind pool] [--capacity 40] [--region R]
    python -m src.common.tenancy.provisioner provision COMPANY_ID [--server NAME]
    python -m src.common.tenancy.provisioner status COMPANY_ID

A company gets a database of its own in two moves:

* ``request_tenant`` — its ``tenant_directory`` row, ``requested``: a new
  tenant key, a slug, a server (an active pool server with room, the
  emptiest first, or one named) and the database name ``t_<key>``;
* ``provision`` — the state machine's steps, in order, from where the tenant
  is: ``db_created`` → ``migrated`` → ``identity_ready`` → ``keys_ready`` →
  ``namespace_ready`` → ``storage_ready`` → ``data_api_ready`` → ``active``.

Every step checks before it creates, so running a step again does nothing
new. Each attempt is written to ``tenant_provisioning_log`` (started, then
succeeded, skipped or failed); the directory row's ``status`` is the last
step that finished. A failed step leaves the tenant ``failed``; ``provision``
again resumes after the last step that succeeded. Two provisioners never
work on one tenant at once (a PostgreSQL advisory lock on the control
database).

What each step does depends on the platform profile (``PLATFORM_PROFILE``):

| Step | ``local`` | ``azure`` |
|------|-----------|-----------|
| db_created | ``CREATE DATABASE`` on the tenant's server, extensions, schema ``platform``, ``search_path`` | the same, as the provisioner identity, after the server's roles (once) and before who may use it: ``hb_runtime`` and the DDL role only, objects owned by the DDL role (``db_roles``) |
| migrated | the platform schema (``migrate.upgrade_tenant``), then base pack v1 (``schema_engine``) | the same |
| identity_ready | skipped: one database role | the tenant's managed identity, its federated credential (``t-<key>/data-api``) and its ``hb_dataapi`` sign-in to this database (``azure_identity``, ``db_roles``) |
| keys_ready | the tenant KEK (a local key file) and its first DEK | the KEK in the tenant-keys vault, and the DEK |
| namespace_ready | skipped: no Kubernetes (unless ``KUBE_API_URL``) | namespace ``t-<key>``: restricted pods, default-deny, quota, limits |
| storage_ready | the ``t-<key>`` namespace in storage | the ``t-<key>`` Blob container |
| data_api_ready | skipped: served in-process at ``/data`` | the same with ``DATA_API_MODE=in_process`` (Azure dev); otherwise not built yet: the tenant's Data API Deployment |

A step "not built yet" fails with that reason, so a tenant on Azure stops
short of ``active`` instead of being marked ready without its resources.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence
from uuid import UUID

from sqlalchemy import func, select, text

from src.common.tenancy.models import PROVISIONING_STEPS

logger = logging.getLogger(__name__)

__all__ = [
    "EXTENSIONS", "NoServerAvailable", "ProvisioningError", "StepNotBuilt", "StepResult",
    "add_server", "provision", "provisioning_status", "request_tenant", "STEPS",
]

# The steps provision() runs, in order (``requested`` is request_tenant's).
STEPS = PROVISIONING_STEPS[1:]
EXTENSIONS = ("vector", "pgcrypto", "pg_trgm", "uuid-ossp")
FINISHED = frozenset({"active", "suspended", "exporting", "retired"})
WORKSPACE_MARKER = "workspace.json"


class ProvisioningError(RuntimeError):
    """A tenant cannot be requested or provisioned; the message says why."""


class NoServerAvailable(ProvisioningError):
    """No active pool server has room for another tenant."""


class StepNotBuilt(ProvisioningError):
    """The step has no implementation for this platform profile yet."""


@dataclass
class StepResult:
    outcome: str                       # succeeded | skipped
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Tenant:
    """What a step needs to know about the tenant it works on."""
    company_id: UUID
    key: str
    db_name: str
    server_host: str


# ── Requesting ──────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:40].strip("-") or "workspace"


async def add_server(db: Any, *, name: str, host: str, kind: str = "pool", capacity: int = 40,
                     region: str = "local", status: str = "active") -> Any:
    """Register (or update) a PostgreSQL server tenant databases may live on."""
    from src.common.tenancy.models import TenantDbServer

    server = (await db.execute(select(TenantDbServer).where(TenantDbServer.name == name))).scalar_one_or_none()
    if server is None:
        server = TenantDbServer(name=name, host=host, kind=kind, region=region, capacity=capacity, status=status)
        db.add(server)
    else:
        server.host, server.kind, server.region, server.capacity, server.status = host, kind, region, capacity, status
    await db.flush()
    return server


async def _choose_server(db: Any, server_name: Optional[str]) -> Any:
    from src.common.tenancy.models import TenantDbServer, TenantDirectoryEntry

    if server_name:
        server = (await db.execute(select(TenantDbServer).where(TenantDbServer.name == server_name))
                  ).scalar_one_or_none()
        if server is None or server.status != "active":
            raise ProvisioningError(f"server {server_name!r} is not an active tenant database server")
        return server
    tenants = (select(TenantDirectoryEntry.server_id, func.count().label("n"))
               .where(TenantDirectoryEntry.status != "retired")
               .group_by(TenantDirectoryEntry.server_id).subquery())
    used = func.coalesce(tenants.c.n, 0)
    row = (await db.execute(
        select(TenantDbServer)
        .outerjoin(tenants, tenants.c.server_id == TenantDbServer.id)
        .where(TenantDbServer.status == "active", TenantDbServer.kind == "pool",
               used < TenantDbServer.capacity)
        .order_by(used, TenantDbServer.name).limit(1)
    )).scalar_one_or_none()
    if row is None:
        raise NoServerAvailable("no active pool server has room for another tenant; register one with "
                                "`python -m src.common.tenancy.provisioner add-server NAME HOST`")
    return row


async def _unique_slug(db: Any, base: str, key: str) -> str:
    from src.common.tenancy.models import TenantDirectoryEntry

    for candidate in (base, f"{base}-{key[:4]}", f"{base}-{key}"):
        taken = (await db.execute(select(TenantDirectoryEntry.company_id)
                                  .where(TenantDirectoryEntry.slug == candidate))).first()
        if taken is None:
            return candidate
    raise ProvisioningError(f"no free slug for {base!r}")


async def request_tenant(company_id: Any, *, server_name: Optional[str] = None,
                         key: Optional[str] = None) -> Any:
    """The company's directory row, made ``requested`` if it has none (idempotent)."""
    from src.auth.models import Company
    from src.common.tenancy.directory import is_valid_tenant_key, new_tenant_key, tenant_db_name
    from src.common.tenancy.models import TenantDirectoryEntry, TenantProvisioningLog
    from src.common.tenancy.session import control_session

    company_id = UUID(str(company_id))
    async with control_session() as db:
        entry = await db.get(TenantDirectoryEntry, company_id)
        if entry is not None:
            return entry
        company = await db.get(Company, company_id)
        if company is None:
            raise ProvisioningError(f"company {company_id} does not exist")
        if key is not None and not is_valid_tenant_key(key):
            raise ProvisioningError(f"not a tenant key: {key!r}")
        server = await _choose_server(db, server_name)
        key = key or new_tenant_key()
        entry = TenantDirectoryEntry(
            company_id=company_id, tenant_key=key, slug=await _unique_slug(db, slugify(company.name), key),
            server_id=server.id, db_name=tenant_db_name(key), status="requested",
            timezone=getattr(company, "timezone", None) or "Asia/Kolkata",
        )
        db.add(entry)
        db.add(TenantProvisioningLog(company_id=company_id, tenant_key=key, step="requested",
                                     outcome="succeeded", detail={"server": server.name}))
        await db.commit()
    await _publish(company_id)
    logger.info("tenant %s requested for company %s on server %s", key, company_id, server.name)
    return entry


# ── The steps ───────────────────────────────────────────────────────────────

def _profile() -> str:
    from src.common.platform import platform_profile

    return platform_profile()


def _admin_url(tenant: Tenant, database: str = "postgres") -> Any:
    from src.common.tenancy.directory import TenantLocation
    from src.common.tenancy.engines import tenant_url

    location = TenantLocation(company_id=tenant.company_id, key=tenant.key, server_host=tenant.server_host,
                              db_name=database, status="requested", schema_version=None,
                              automation_state="running", timezone="UTC")
    return tenant_url(location)


def _engine(url: Any) -> Any:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from src.common.platform.dbauth import install as install_db_auth

    engine = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    install_db_auth(engine)
    return engine


async def _db_created(tenant: Tenant) -> StepResult:
    """The server's roles (once), the database, its extensions, schema ``platform``,
    ``search_path`` and who may use it (``db_roles``; local: one user owns everything)."""
    from src.common.tenancy import db_roles

    admin = _engine(_admin_url(tenant))
    try:
        async with admin.connect() as conn:
            server_roles = await db_roles.ensure_server_roles(conn)
            exists = (await conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"),
                                         {"d": tenant.db_name})).first() is not None
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{tenant.db_name}"'))
    finally:
        await admin.dispose()
    database = _engine(_admin_url(tenant, tenant.db_name))
    try:
        async with database.connect() as conn:
            for extension in EXTENSIONS:
                await conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{extension}"'))
            access = await db_roles.secure_database(conn, tenant.db_name)
            if db_roles.ddl_role() is None:
                await conn.execute(text("CREATE SCHEMA IF NOT EXISTS platform"))
            await conn.execute(text(f'ALTER DATABASE "{tenant.db_name}" SET search_path TO platform, public'))
    finally:
        await database.dispose()
    return StepResult("succeeded", {"database": tenant.db_name, "created": not exists,
                                    "server": tenant.server_host, "server_roles": server_roles,
                                    "access": access})


async def _migrated(tenant: Tenant) -> StepResult:
    """The platform schema's tables, then base pack v1 (the business's records)."""
    from src.common.tenancy.engines import create_tenant_engine, tenant_url
    from src.common.tenancy.migrate import upgrade_tenant
    from src.schema_engine import engine as schema_engine

    from src.common.tenancy.db_roles import ddl_role

    location = await _location(tenant, status="db_created")
    version = await upgrade_tenant(location)
    # The base pack's tables belong to the DDL role, like the platform schema's.
    engine = create_tenant_engine(tenant_url(location), role=ddl_role())
    try:
        blueprint = await schema_engine.active_blueprint(engine, tenant.company_id)
    finally:
        await engine.dispose()
    return StepResult("succeeded", {"platform_schema_version": version,
                                    "base_pack": blueprint.get("base_pack"),
                                    "objects": sorted((blueprint.get("objects") or {}).keys())})


def _local_skip(reason: str, step: str, later: str) -> Callable[[Tenant], Awaitable[StepResult]]:
    async def run(tenant: Tenant) -> StepResult:
        if _profile() == "local":
            return StepResult("skipped", {"reason": reason})
        raise StepNotBuilt(f"{step} has no implementation for PLATFORM_PROFILE={_profile()} yet ({later})")
    run.__name__ = f"_{step}"
    return run


async def _storage_ready(tenant: Tenant) -> StepResult:
    """The tenant's storage namespace (``t-<key>``; a Blob container on Azure), marked as its workspace."""
    from src.common.platform.storage import get_storage

    storage = get_storage()
    marker = f"t-{tenant.key}/{WORKSPACE_MARKER}"
    if await storage.exists(marker):
        return StepResult("succeeded", {"namespace": f"t-{tenant.key}", "created": False})
    body = json.dumps({"tenant_key": tenant.key, "company_id": str(tenant.company_id),
                       "created_at": datetime.utcnow().isoformat() + "Z"}).encode()
    await storage.put(marker, body, content_type="application/json")
    return StepResult("succeeded", {"namespace": f"t-{tenant.key}", "created": True})


async def _keys_ready(tenant: Tenant) -> StepResult:
    """The tenant's KEK (a local key file, or an RSA key in the tenant-keys vault) and its first DEK (WS5)."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.common.platform.kek import get_kek, tenant_kek_name
    from src.common.tenancy.engines import create_tenant_engine, tenant_url
    from src.connections import crypto

    name = tenant_kek_name(tenant.key)
    key_id = await get_kek().ensure_key(name)
    engine = create_tenant_engine(tenant_url(await _location(tenant, status="identity_ready")))
    try:
        async with AsyncSession(engine) as db:
            version, _ = await crypto._current_dek(db, tenant.company_id)  # noqa: SLF001 - made on first use
            await db.commit()
    finally:
        await engine.dispose()
    return StepResult("succeeded", {"kek": name, "key_id": key_id, "dek_version": version})


def namespace_manifests(tenant_key: str, *, quota: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """The tenant's Kubernetes namespace ``t-<key>`` (tech spec §13.1): Pod Security
    ``restricted``, a default-deny network policy (the App Controller and the
    sandbox runtime open what each pod needs), a quota by tier and default limits."""
    namespace = f"t-{tenant_key}"
    labels = {"hirebuddha.com/tenant": tenant_key, "pod-security.kubernetes.io/enforce": "restricted",
              "pod-security.kubernetes.io/enforce-version": "latest"}
    quota = quota or {"requests.cpu": "8", "requests.memory": "16Gi", "limits.memory": "32Gi", "pods": "60",
                      "services.loadbalancers": "0", "services.nodeports": "0"}
    return [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace, "labels": labels}},
        {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
         "metadata": {"name": "default-deny", "namespace": namespace},
         "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}},
        {"apiVersion": "v1", "kind": "ResourceQuota", "metadata": {"name": "tenant-quota", "namespace": namespace},
         "spec": {"hard": quota}},
        {"apiVersion": "v1", "kind": "LimitRange", "metadata": {"name": "tenant-defaults", "namespace": namespace},
         "spec": {"limits": [{"type": "Container", "default": {"cpu": "500m", "memory": "512Mi"},
                              "defaultRequest": {"cpu": "100m", "memory": "128Mi"}}]}},
    ]


async def _namespace_ready(tenant: Tenant) -> StepResult:
    """The tenant's namespace on the cluster (WS6); skipped where there is no cluster."""
    from src.common.config import settings

    if _profile() == "local" and not settings.KUBE_API_URL:
        return StepResult("skipped", {"reason": "no Kubernetes on this machine"})
    from src.common.platform.kube import get_kube

    kube = get_kube()
    for manifest in namespace_manifests(tenant.key):
        await kube.apply(manifest)
    return StepResult("succeeded", {"namespace": f"t-{tenant.key}"})


async def _identity_ready(tenant: Tenant) -> StepResult:
    """The tenant's own identity for its Data API (Azure): the managed identity, its
    federated credential, and its sign-in to this database only (``hb_dataapi``)."""
    if _profile() == "local":
        return StepResult("skipped", {"reason": "one database role for every database on this machine"})
    from src.common.tenancy import azure_identity, db_roles

    identity = await azure_identity.ensure_tenant_identity(tenant.key)
    database = _engine(_admin_url(tenant, tenant.db_name))
    try:
        async with database.connect() as conn:
            grant = await db_roles.grant_tenant_principal(conn, tenant.db_name, identity["name"],
                                                          identity["principal_id"])
    finally:
        await database.dispose()
    return StepResult("succeeded", {**identity, "database_role": db_roles.DATA_API, "made": grant["made"]})


async def _data_api_ready(tenant: Tenant) -> StepResult:
    """The tenant's Data API: in-process at ``/data`` (local; Azure dev until the
    per-tenant Deployment, ``DATA_API_MODE=in_process``), else its own Deployment."""
    from src.common.config import settings

    mode = (settings.DATA_API_MODE or ("in_process" if _profile() == "local" else "deployment")).lower()
    if mode == "in_process":
        return StepResult("skipped", {"reason": "the Data API is served in-process at /data"})
    raise StepNotBuilt("data_api_ready: the per-tenant Data API Deployment is not built yet (WS4); "
                       "set DATA_API_MODE=in_process to serve it in-process")


async def _active(tenant: Tenant) -> StepResult:
    return StepResult("succeeded", {})


STEP_FUNCTIONS: Dict[str, Callable[[Tenant], Awaitable[StepResult]]] = {
    "db_created": _db_created,
    "migrated": _migrated,
    "identity_ready": _identity_ready,
    "keys_ready": _keys_ready,
    "namespace_ready": _namespace_ready,
    "storage_ready": _storage_ready,
    "data_api_ready": _data_api_ready,
    "active": _active,
}
assert tuple(STEP_FUNCTIONS) == STEPS


# ── Running them ────────────────────────────────────────────────────────────

async def _publish(company_id: UUID) -> None:
    from src.common.tenancy.directory import directory, publish_change

    directory.invalidate(company_id)
    try:
        from src.common.redis_client import shared_redis

        await publish_change(shared_redis(), company_id)
    except Exception as exc:  # noqa: BLE001 - other processes see it within the cache time
        logger.warning("tenant directory change for %s not published: %s", company_id, exc)


async def _location(tenant: Tenant, *, status: str) -> Any:
    from src.common.tenancy.directory import TenantLocation

    return TenantLocation(company_id=tenant.company_id, key=tenant.key, server_host=tenant.server_host,
                          db_name=tenant.db_name, status=status, schema_version=None,
                          automation_state="running", timezone="UTC")


def _lock_id(company_id: UUID) -> int:
    return int.from_bytes(hashlib.sha256(f"tenant-provisioning:{company_id}".encode()).digest()[:8],
                          "big", signed=True)


async def _resume_after(db: Any, entry: Any) -> str:
    """The step the tenant has finished: its status, or for a failed one the
    last step that succeeded (``requested`` if none did)."""
    from src.common.tenancy.models import TenantProvisioningLog

    if entry.status != "failed":
        return entry.status
    done = (await db.execute(
        select(TenantProvisioningLog.step)
        .where(TenantProvisioningLog.company_id == entry.company_id,
               TenantProvisioningLog.outcome.in_(("succeeded", "skipped")),
               TenantProvisioningLog.step.in_(PROVISIONING_STEPS))
    )).scalars().all()
    finished = [step for step in PROVISIONING_STEPS if step in set(done)]
    return finished[-1] if finished else "requested"


async def _attempt(db: Any, company_id: UUID, step: str) -> int:
    from src.common.tenancy.models import TenantProvisioningLog

    tries = (await db.execute(select(func.count()).where(
        TenantProvisioningLog.company_id == company_id, TenantProvisioningLog.step == step,
        TenantProvisioningLog.outcome == "started"))).scalar()
    return int(tries or 0) + 1


async def provision(company_id: Any) -> Dict[str, Any]:
    """Run the tenant's remaining steps; ``{"status", "steps": [...], "failed"?, "busy"?}``."""
    from src.common.tenancy.session import control_session

    company_id = UUID(str(company_id))
    # Held for the whole run by this session's open transaction; it goes with
    # the transaction, so a provisioner that dies does not keep it.
    async with control_session() as lock_db:
        locked = (await lock_db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"),
                                        {"k": _lock_id(company_id)})).scalar()
        if not locked:
            return {"company_id": str(company_id), "busy": True}
        try:
            return await _provision_locked(company_id)
        finally:
            await lock_db.rollback()


async def _provision_locked(company_id: UUID) -> Dict[str, Any]:
    from src.common.tenancy.models import TenantDbServer, TenantDirectoryEntry, TenantProvisioningLog
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        entry = await db.get(TenantDirectoryEntry, company_id)
        if entry is None:
            raise ProvisioningError(f"company {company_id} has no tenant requested (request_tenant first)")
        server = await db.get(TenantDbServer, entry.server_id)
        tenant = Tenant(company_id=company_id, key=entry.tenant_key, db_name=entry.db_name,
                        server_host=server.host)
        status = entry.status
        if status in FINISHED:
            return {"company_id": str(company_id), "tenant_key": tenant.key, "status": status, "steps": []}
        resume_after = await _resume_after(db, entry)
    remaining = STEPS[STEPS.index(resume_after) + 1:] if resume_after in STEPS else STEPS
    ran: List[Dict[str, Any]] = []
    for step in remaining:
        async with control_session() as db:
            attempt = await _attempt(db, company_id, step)
            db.add(TenantProvisioningLog(company_id=company_id, tenant_key=tenant.key, step=step,
                                         outcome="started", attempt=attempt))
            await db.commit()
        try:
            result = await STEP_FUNCTIONS[step](tenant)
        except Exception as exc:  # noqa: BLE001 - recorded, and the tenant is left failed
            error = f"{type(exc).__name__}: {exc}"[:2000]
            logger.error("tenant %s: step %s failed: %s", tenant.key, step, error)
            async with control_session() as db:
                db.add(TenantProvisioningLog(company_id=company_id, tenant_key=tenant.key, step=step,
                                             outcome="failed", attempt=attempt, error=error))
                entry = await db.get(TenantDirectoryEntry, company_id)
                entry.status = "failed"
                await db.commit()
            await _publish(company_id)
            ran.append({"step": step, "outcome": "failed", "error": error})
            return {"company_id": str(company_id), "tenant_key": tenant.key, "status": "failed",
                    "failed": step, "steps": ran}
        async with control_session() as db:
            db.add(TenantProvisioningLog(company_id=company_id, tenant_key=tenant.key, step=step,
                                         outcome=result.outcome, attempt=attempt, detail=result.detail))
            entry = await db.get(TenantDirectoryEntry, company_id)
            entry.status = step
            await db.commit()
        await _publish(company_id)
        ran.append({"step": step, "outcome": result.outcome, "detail": result.detail})
        logger.info("tenant %s: %s %s", tenant.key, step, result.outcome)
    return {"company_id": str(company_id), "tenant_key": tenant.key, "status": "active", "steps": ran}


async def provisioning_status(db: Any, company_id: Any) -> Dict[str, Any]:
    """The tenant's state for the "setting up your workspace" screen and for staff."""
    from src.common.tenancy.models import TenantDirectoryEntry, TenantProvisioningLog

    company_id = UUID(str(company_id))
    entry = await db.get(TenantDirectoryEntry, company_id)
    if entry is None:
        return {"company_id": str(company_id), "status": "not_requested", "ready": False, "steps": []}
    rows = (await db.execute(
        select(TenantProvisioningLog).where(TenantProvisioningLog.company_id == company_id)
        .order_by(TenantProvisioningLog.created_at, TenantProvisioningLog.id)
    )).scalars().all()
    latest: Dict[str, Any] = {}
    for row in rows:
        if row.outcome != "started" or row.step not in latest:
            latest[row.step] = row
    steps = []
    for step in PROVISIONING_STEPS:
        row = latest.get(step)
        steps.append({"step": step, "outcome": row.outcome if row else "pending",
                      "attempt": row.attempt if row else 0, "error": row.error if row else None,
                      "detail": row.detail if row else None,
                      "at": row.created_at.isoformat() if row and row.created_at else None})
    from src.common.tenancy.models import DATABASE_READY_STATUSES

    return {"company_id": str(company_id), "tenant_key": entry.tenant_key, "slug": entry.slug,
            "status": entry.status, "ready": entry.status == "active",
            "database_ready": entry.status in DATABASE_READY_STATUSES,
            "platform_schema_version": entry.platform_schema_version, "steps": steps}


# ── The arq job and the command line ────────────────────────────────────────

async def provision_tenant(ctx: Dict[str, Any], company_id: str) -> Dict[str, Any]:
    """arq job: provision ``company_id``'s tenant (``request_tenant`` made its row)."""
    return await provision(company_id)


async def enqueue_provisioning(company_id: Any, *, job_id: Optional[str] = None) -> Any:
    """Queue ``provision_tenant``: on ``PROVISIONING_QUEUE`` when set (its own worker,
    signed in as the provisioner identity on Azure), else the default queue."""
    from src.common.config import settings
    from src.common.job_queue import enqueue_job

    options: Dict[str, Any] = {"_queue_name": settings.PROVISIONING_QUEUE} if settings.PROVISIONING_QUEUE else {}
    if job_id:
        options["_job_id"] = job_id
    return await enqueue_job("provision_tenant", str(company_id), **options)


async def request_and_enqueue(company_id: Any, *, server_name: Optional[str] = None) -> Optional[Any]:
    """Sign-up's hook (WS2 2.9): with ``TENANCY_MODE=split`` a new company gets
    its tenant requested and a provisioning job; ``None`` with ``single``."""
    from src.common.tenancy.session import is_split

    if not is_split():
        return None
    entry = await request_tenant(company_id, server_name=server_name)
    await enqueue_provisioning(company_id, job_id=f"provision-tenant:{company_id}")
    return entry


async def _cli(args: argparse.Namespace) -> int:
    from src.common import database
    from src.common.tenancy.engines import engines
    from src.common.tenancy.session import control_session

    try:
        if args.command == "add-server":
            async with control_session() as db:
                server = await add_server(db, name=args.name, host=args.host, kind=args.kind,
                                          capacity=args.capacity, region=args.region)
                await db.commit()
            print(f"server {server.name}: {server.host}, {server.kind}, capacity {server.capacity}")
            return 0
        if args.command == "provision":
            await request_tenant(args.company_id, server_name=args.server)
            result = await provision(args.company_id)
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("status") == "active" else 1
        async with control_session() as db:
            print(json.dumps(await provisioning_status(db, args.company_id), indent=2, default=str))
        return 0
    finally:
        await engines.dispose_all()
        await database.engine.dispose()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.common.tenancy.provisioner",
                                     description="Tenant database servers and tenant provisioning.")
    sub = parser.add_subparsers(dest="command", required=True)
    server = sub.add_parser("add-server", help="register a server tenant databases may live on")
    server.add_argument("name")
    server.add_argument("host")
    server.add_argument("--kind", choices=("pool", "dedicated"), default="pool")
    server.add_argument("--capacity", type=int, default=40)
    server.add_argument("--region", default="local")
    prov = sub.add_parser("provision", help="request and provision a company's tenant")
    prov.add_argument("company_id")
    prov.add_argument("--server", help="the server's name (default: the emptiest pool server with room)")
    status = sub.add_parser("status", help="a tenant's provisioning steps")
    status.add_argument("company_id")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return asyncio.run(_cli(args))


if __name__ == "__main__":
    sys.exit(main())

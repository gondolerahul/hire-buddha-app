"""Tenant apps: create, build, preview, publish, roll back, operate (Phase 14 WS6 6.6–6.11; tech spec §11.4–§11.7).

The life of an app:

1. **Create** (``create_app``) from a template (D48) — and, for a CRM or a
   backend, the business's objects it works with: the first commit goes to a
   repository of its own (built-in Git, or GitHub), its default roles are made,
   and keys it needs are issued (an app key for a backend; a public key that
   may only create one kind of record, for a website's forms).
2. **Change** — every later change (an agent's, a person's) is a pull request
   (``code_lanes.open_change``) with checks; a merge builds.
3. **Build** (``start_build`` → job ``build_app``) — the commit's image
   (``build.py``), its SBOM and scan; ``app.build.succeeded|failed``. A build
   of an open pull request is deployed as that request's **preview**
   (``<app>-<slug>-pr<n>.<APPS_DOMAIN>``, ``APP_PREVIEW_DAYS``).
4. **Publish** (``publish``) — the build runs as ``<app>-<slug>.<APPS_DOMAIN>``
   and its verified custom domains; ``app.deployed``. **Rollback** runs the
   build published before it (the last five are kept).
5. **Operate** — stop, start, restart, mode (always on / sleep), limits,
   outbound allow-list, logs and metrics (``runtime.py``).
"""
from __future__ import annotations

import base64
import logging
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select

from src.apps import templates as tpl
from src.apps.db import app_session
from src.apps.models import (App, AppBuild, AppDeployment, AppRole, AppUser, AppUserRole, AppUserSession,
                             CustomDomain)

logger = logging.getLogger(__name__)

KEEP_PUBLISHED = 5
MAX_EGRESS_HOSTS = 50
_HOST = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_CPU = re.compile(r"^(?:[0-9]{1,4}m|[0-9](?:\.[0-9]{1,3})?)$")
_MEMORY = re.compile(r"^[0-9]{2,5}(?:Mi|Gi)$")
MAX_CPU_CORES = 2.0
MAX_MEMORY_GB = 4.0


class AppProblem(RuntimeError):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


# ── Views ───────────────────────────────────────────────────────────────────

def app_view(app: App) -> Dict[str, Any]:
    settings = app.settings or {}
    return {"id": str(app.id), "name": app.name, "display_name": app.display_name, "template": app.template,
            "template_version": app.template_version, "status": app.status, "mode": app.mode,
            "resources": app.resources or {}, "env": app.env or {}, "outbound_allowlist": list(app.outbound_allowlist or []),
            "repo_id": str(app.repo_id) if app.repo_id else None, "repo_path": app.repo_path,
            "objects": settings.get("objects") or [], "hostname": settings.get("published_hostname"),
            "url": settings.get("published_url"), "kind": settings.get("kind"),
            "published_deployment_id": str(app.published_deployment_id) if app.published_deployment_id else None,
            "created_at": _iso(app.created_at), "updated_at": _iso(app.updated_at)}


def build_view(build: AppBuild) -> Dict[str, Any]:
    return {"id": str(build.id), "app_id": str(build.app_id), "commit_sha": build.commit_sha, "status": build.status,
            "builder": build.builder, "image": build.image, "image_digest": build.image_digest,
            "scan": build.scan or {}, "sbom_key": build.sbom_key, "log_key": build.log_key,
            "duration_seconds": build.duration_seconds, "cost": float(build.cost) if build.cost is not None else None,
            "error": build.error, "review_id": str(build.review_id) if build.review_id else None,
            "created_at": _iso(build.created_at), "started_at": _iso(build.started_at),
            "finished_at": _iso(build.finished_at)}


def deployment_view(row: AppDeployment) -> Dict[str, Any]:
    return {"id": str(row.id), "app_id": str(row.app_id), "build_id": str(row.build_id), "kind": row.kind,
            "pr_number": row.pr_number, "hostnames": list(row.hostnames or []), "url": row.url,
            "image_digest": row.image_digest, "status": row.status, "runtime_status": row.runtime_status or {},
            "expires_at": _iso(row.expires_at), "created_at": _iso(row.created_at)}


# ── Names, keys, sealed secrets ─────────────────────────────────────────────

def business_slug(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return cleaned[:20].strip("-") or "app"


async def _hostname_slug(company_id: Any, tenant_key: str) -> str:
    """The business's part of its apps' names (``crm-<slug>``): the tenant directory's slug
    (unique, chosen at sign-up), else its name made unique with its tenant key."""
    from src.auth.models import Company
    from src.common.tenancy.models import TenantDirectoryEntry
    from src.common.tenancy.session import control_session

    async with control_session() as cdb:
        slug = (await cdb.execute(select(TenantDirectoryEntry.slug).where(
            TenantDirectoryEntry.company_id == _uuid(company_id)))).scalar()
        if slug:
            return business_slug(slug)
        company = await cdb.get(Company, _uuid(company_id))
    return f"{business_slug(company.name if company else '')}-{tenant_key[:4]}"


def hostname(app_name: str, slug: str, *, pr_number: Optional[int] = None, preview: bool = False) -> str:
    from src.common.config import settings

    suffix = f"-pr{pr_number}" if pr_number else ("-preview" if preview else "")
    return f"{app_name}-{slug}{suffix}.{settings.APPS_DOMAIN}"


def data_api_url(kind: str) -> str:
    """Where the app reaches the Data API: browsers (web apps) or its own pods (backends)."""
    from src.common.config import settings

    if kind == "api":
        return settings.APP_DATA_API_INTERNAL_URL or settings.APP_DATA_API_PUBLIC_URL or \
            "http://host.docker.internal:8000/data"
    return settings.APP_DATA_API_PUBLIC_URL or "http://localhost:8000/data"


async def _seal(db: Any, company_id: Any, app_id: Any, values: Dict[str, str]) -> Dict[str, Any]:
    from src.connections.crypto import seal_secret

    version, nonce, ciphertext = await seal_secret(db, company_id, f"app-secrets:{app_id}", values)
    return {"v": version, "n": base64.b64encode(nonce).decode(), "c": base64.b64encode(ciphertext).decode()}


async def _unseal(db: Any, app: App) -> Dict[str, str]:
    from src.connections.crypto import open_secret

    sealed = (app.settings or {}).get("sealed")
    if not sealed:
        return {}
    return await open_secret(db, app.company_id, f"app-secrets:{app.id}", sealed["v"], base64.b64decode(sealed["n"]),
                             base64.b64decode(sealed["c"]))


async def _issue_key(db: Any, company_id: Any, tenant_key: str, name: str, scopes: Dict[str, Any], *,
                     external: bool, public: bool = False) -> tuple[str, uuid.UUID]:
    """An app's Data API key; a ``public`` one (a website's form, in browsers) works only
    while the business's public API access is on."""
    from src.data_api import tokens
    from src.schema_engine.models import ApiKey

    key, prefix = tokens.new_key(tenant_key)
    checked = tokens.validate_scopes(scopes)
    if public:
        checked["public"] = True
    row = ApiKey(id=uuid.uuid4(), company_id=_uuid(company_id), name=name[:120], prefix=prefix,
                 key_hash=tokens.key_hash(key), scopes=checked, external=external,
                 created_by="platform:apps", created_at=datetime.utcnow())
    db.add(row)
    return key, row.id


# ── Create ──────────────────────────────────────────────────────────────────

async def _location(company_id: Any) -> Any:
    from src.common.tenancy.directory import directory

    location = await directory.find(company_id)
    if location is None or not location.database_ready:
        raise AppProblem("apps need the business on its own database; this one has none yet")
    return location


async def _blueprint_objects(company_id: Any) -> List[str]:
    from src.schema_engine import engine as schema

    engine, _ = await schema.business_engine(company_id)
    blueprint = await schema.active_blueprint(engine, company_id)
    return sorted(n for n, o in blueprint["objects"].items() if not o.get("archived"))


async def create_app(company_id: Any, user: Any, *, name: str, display_name: str, template: str,
                     objects: Optional[List[str]] = None, params: Optional[Dict[str, Any]] = None,
                     repo_id: Any = None, provider: str = "builtin", connection_id: Any = None) -> Dict[str, Any]:
    from src.code_lanes import service as code
    from src.code_lanes.git import GitError

    company_id = _uuid(company_id)
    try:
        spec = tpl.get(template)
        name = tpl.check_app_name(name)
    except tpl.TemplateError as error:
        raise AppProblem(str(error), 422) from None
    location = await _location(company_id)
    async with app_session(company_id) as db:
        if (await db.execute(select(App.id).where(App.company_id == company_id, App.name == name))).first():
            raise AppProblem(f"an app named {name} exists")
    known = await _blueprint_objects(company_id)
    objects = list(objects or [])
    unknown = [o for o in objects if o not in known]
    if unknown:
        raise AppProblem(f"no such object: {', '.join(unknown)}", 422)
    if spec.uses_blueprint and not objects:
        raise AppProblem(f"the {spec.name} template works with your records: name the objects", 422)
    if spec.public_key:
        form_object = (params or {}).get("form_object") or spec.params.get("form_object")
        if form_object not in known:
            raise AppProblem(f"the form creates {form_object!r} records, and there is no such object", 422)
    try:
        files = tpl.render(template, app_name=name, display_name=display_name, tenant_key=location.key,
                           data_api_url=data_api_url(spec.kind), params=params, objects=objects)
    except tpl.TemplateError as error:
        raise AppProblem(str(error), 422) from None

    user_id = getattr(user, "id", None)
    if repo_id:
        repo = await _repo_row(company_id, repo_id)
        repo_path = f"apps/{name}"
    else:
        repo = await code.create_repo(company_id, user_id, f"app-{name}", provider=provider,
                                      connection_id=connection_id, description=display_name)
        repo_path = ""
    tree = {f"{repo_path}/{p}" if repo_path else p: c for p, c in files.items()}
    try:
        provider_ = code.provider_for(await _repo_model(company_id, repo["id"]))
        commit = await provider_.commit_files(repo["full_name"], branch=repo["default_branch"],
                                              base=repo["default_branch"], files=tree,
                                              message=f"Start {display_name} from the {spec.name} template")
    except GitError as error:
        raise AppProblem(f"could not write the app's first commit: {error}", 502) from None

    slug = await _hostname_slug(company_id, location.key)
    app_id = uuid.uuid4()
    async with app_session(company_id) as db:
        secrets_: Dict[str, str] = {}
        app = App(id=app_id, company_id=company_id, name=name, display_name=tpl.safe_text(display_name) or name,
                  template=spec.id, template_version=spec.version, repo_id=_uuid(repo["id"]), repo_path=repo_path,
                  status="building" if spec.deployable else "ready", mode="always_on",
                  resources={"cpu": "250m", "memory": "256Mi", "replicas": 1, "maxReplicas": 2},
                  env={}, outbound_allowlist=[], created_by=_uuid(user_id) if user_id else None,
                  settings={"objects": objects, "kind": spec.kind, "port": spec.port, "health_path": spec.health_path,
                            "hostname_slug": slug, "hostnames": [], "params": dict(params or {})})
        db.add(app)
        roles = tpl.default_roles(spec.id, objects)
        for role in roles:
            db.add(AppRole(company_id=company_id, app_id=app_id, name=role["name"], description=role["description"],
                           permissions=role["permissions"]))
        if spec.kind == "api" and objects:
            union = {o: ["read", "create", "update"] for o in objects}
            secrets_["app_key"], app.app_key_id = await _issue_key(
                db, company_id, location.key, f"app {name}", {"objects": union}, external=False)
        if spec.public_key:
            form_object = (params or {}).get("form_object") or spec.params.get("form_object")
            secrets_["public_key"], _ = await _issue_key(
                db, company_id, location.key, f"app {name} form", {"objects": {form_object: ["create"]}},
                external=True, public=True)
        if secrets_:
            await db.flush()
            app.settings = {**app.settings, "sealed": await _seal(db, company_id, app_id, secrets_)}
        await db.commit()
        view = app_view(app)
    view["commit_sha"] = commit
    if spec.deployable:
        view["build"] = await start_build(company_id, app_id, commit_sha=commit, user_id=user_id)
    return view


async def _repo_model(company_id: Any, repo_id: Any) -> Any:
    from src.apps.db import code_session
    from src.code_lanes.models import GitRepo

    async with code_session(company_id) as db:
        repo = await db.get(GitRepo, _uuid(repo_id))
    if repo is None or repo.company_id != _uuid(company_id):
        raise AppProblem("no such repository", 404)
    return repo


async def _repo_row(company_id: Any, repo_id: Any) -> Dict[str, Any]:
    from src.code_lanes.service import repo_view

    return repo_view(await _repo_model(company_id, repo_id))


async def _app(db: Any, company_id: Any, app_id: Any) -> App:
    app = await db.get(App, _uuid(app_id))
    if app is None or app.company_id != _uuid(company_id) or app.status == "archived":
        raise AppProblem("no such app", 404)
    return app


async def list_apps(company_id: Any) -> List[Dict[str, Any]]:
    async with app_session(company_id) as db:
        rows = (await db.execute(select(App).where(App.company_id == _uuid(company_id), App.status != "archived")
                                 .order_by(App.created_at))).scalars().all()
    return [app_view(a) for a in rows]


async def get_app(company_id: Any, app_id: Any) -> Dict[str, Any]:
    from src.common.tenancy.session import control_session

    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        builds = (await db.execute(select(AppBuild).where(AppBuild.app_id == app.id)
                                   .order_by(AppBuild.created_at.desc()).limit(20))).scalars().all()
        deployments = (await db.execute(select(AppDeployment).where(AppDeployment.app_id == app.id)
                                        .order_by(AppDeployment.created_at.desc()).limit(20))).scalars().all()
        roles = (await db.execute(select(AppRole).where(AppRole.app_id == app.id).order_by(AppRole.name))
                 ).scalars().all()
        users = (await db.execute(select(AppUser.id).where(AppUser.app_id == app.id))).all()
    async with control_session() as cdb:
        domains = (await cdb.execute(select(CustomDomain).where(CustomDomain.app_id == app.id,
                                                                CustomDomain.status != "removed"))).scalars().all()
    from src.apps.domains import domain_view

    return {**app_view(app), "builds": [build_view(b) for b in builds],
            "deployments": [deployment_view(d) for d in deployments],
            "roles": [role_view(r) for r in roles], "user_count": len(users),
            "domains": [domain_view(d) for d in domains]}


def _check_resources(resources: Dict[str, Any]) -> Dict[str, Any]:
    from src.apps.runtime import cores, gb

    out = {}
    cpu = str(resources.get("cpu", "250m"))
    memory = str(resources.get("memory", "256Mi"))
    if not _CPU.match(cpu) or cores(cpu) <= 0 or cores(cpu) > MAX_CPU_CORES:
        raise AppProblem(f"cpu is like 250m or 1, at most {MAX_CPU_CORES}", 422)
    if not _MEMORY.match(memory) or gb(memory) > MAX_MEMORY_GB or gb(memory) < 0.0625:
        raise AppProblem(f"memory is like 256Mi or 1Gi, between 64Mi and {MAX_MEMORY_GB:g}Gi", 422)
    replicas = int(resources.get("replicas", 1))
    max_replicas = int(resources.get("maxReplicas", max(2, replicas)))
    if not 1 <= replicas <= 5 or not replicas <= max_replicas <= 10:
        raise AppProblem("replicas 1–5, maxReplicas up to 10 and at least replicas", 422)
    out.update(cpu=cpu, memory=memory, replicas=replicas, maxReplicas=max_replicas)
    return out


async def update_settings(company_id: Any, app_id: Any, *, display_name: Optional[str] = None,
                          mode: Optional[str] = None, resources: Optional[Dict[str, Any]] = None,
                          env: Optional[Dict[str, str]] = None, outbound_allowlist: Optional[List[str]] = None,
                          ) -> Dict[str, Any]:
    """Change how the app runs; a published app is re-applied at once."""
    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        if display_name is not None:
            app.display_name = tpl.safe_text(display_name) or app.display_name
        if mode is not None:
            if mode not in ("always_on", "sleep"):
                raise AppProblem("mode is always_on or sleep", 422)
            app.mode = mode
        if resources is not None:
            app.resources = _check_resources({**(app.resources or {}), **resources})
        if env is not None:
            bad = [k for k in env if not re.match(r"^[A-Z][A-Z0-9_]{0,63}$", k) or k.startswith("HB_")]
            if bad:
                raise AppProblem(f"environment names are UPPER_CASE and not HB_*: {', '.join(bad)}", 422)
            app.env = {k: str(v)[:4000] for k, v in env.items()}
        if outbound_allowlist is not None:
            hosts = sorted({h.strip().lower().lstrip("*.") for h in outbound_allowlist if h.strip()})
            if len(hosts) > MAX_EGRESS_HOSTS or any(not _HOST.match(h) for h in hosts):
                raise AppProblem(f"at most {MAX_EGRESS_HOSTS} host names like api.example.com", 422)
            app.outbound_allowlist = hosts
        app.updated_at = datetime.utcnow()
        await db.commit()
        published = app.published_deployment_id
    if published:
        await _reapply(company_id, app_id)
    return await get_app(company_id, app_id)


async def archive_app(company_id: Any, app_id: Any) -> Dict[str, Any]:
    """Stop everything it runs and take its names; its repository, builds and users stay."""
    from src.apps.runtime import get_runtime

    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        live = (await db.execute(select(AppDeployment).where(AppDeployment.app_id == app.id,
                                                             AppDeployment.status == "active"))).scalars().all()
    location = await _location(company_id)
    for row in live:
        try:
            await get_runtime().delete(f"t-{location.key}", _instance(app, row.kind, row.pr_number))
        except Exception:  # noqa: BLE001 - archiving goes on; the edge stops routing below
            logger.warning("instance of %s not deleted", app.name, exc_info=True)
    await _forget_hostnames(app.id, kinds=("platform", "preview", "custom"))
    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        for row in (await db.execute(select(AppDeployment).where(AppDeployment.app_id == app.id,
                                                                 AppDeployment.status == "active"))).scalars().all():
            row.status = "stopped"
        app.status, app.published_deployment_id, app.updated_at = "archived", None, datetime.utcnow()
        await db.commit()
        return app_view(app)


# ── Builds ──────────────────────────────────────────────────────────────────

async def start_build(company_id: Any, app_id: Any, *, commit_sha: Optional[str] = None, review_id: Any = None,
                      user_id: Any = None, inline: bool = False) -> Dict[str, Any]:
    from src.apps.build import get_builder
    from src.code_lanes import service as code

    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        repo_id = app.repo_id
    repo = await _repo_model(company_id, repo_id)
    if commit_sha is None:
        commit_sha = await code.provider_for(repo).head(repo.full_name, repo.default_branch)
        if not commit_sha:
            raise AppProblem("the app's repository has no commit to build")
    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        build = AppBuild(company_id=app.company_id, app_id=app.id, commit_sha=commit_sha,
                         template_version=app.template_version, builder=getattr(get_builder(), "name", "unknown"),
                         status="queued", review_id=_uuid(review_id) if review_id else None,
                         requested_by=_uuid(user_id) if user_id else None)
        db.add(build)
        app.status = "building" if app.status in ("draft", "failed", "building") else app.status
        await db.commit()
        view = build_view(build)
    if inline:
        return await run_build(company_id, build.id)
    from src.common.job_queue import enqueue_job, tenant_arg

    try:
        await enqueue_job("build_app", str(build.id), company_id=tenant_arg(company_id), _job_id=f"build:{build.id}")
    except Exception:  # noqa: BLE001 - no queue: build here
        logger.warning("build %s runs inline (no job queue)", build.id, exc_info=True)
        return await run_build(company_id, build.id)
    return view


async def run_build(company_id: Any, build_id: Any, *, builder: Any = None) -> Dict[str, Any]:
    """Build one queued build: context from the commit, image, SBOM, scan, log; then its preview."""
    import time

    from src.apps import events
    from src.apps.build import BuildError, build_context, get_builder
    from src.code_lanes import service as code
    from src.common.config import settings
    from src.common.platform.storage import company_namespace, get_storage

    builder = builder or get_builder()
    async with app_session(company_id) as db:
        build = await db.get(AppBuild, _uuid(build_id))
        if build is None or build.status not in ("queued", "running"):
            return build_view(build) if build else {"build": None}
        app = await db.get(App, build.app_id)
        build.status, build.started_at = "running", datetime.utcnow()
        await db.commit()
    location = await _location(company_id)
    repo = await _repo_model(company_id, app.repo_id)
    provider = code.provider_for(repo)
    started = time.monotonic()
    prefix = f"{company_namespace(company_id)}/apps/{app.name}/builds/{build.id}"
    storage = get_storage()
    result, error = None, None
    try:
        archive = await provider.archive(repo.full_name, build.commit_sha)
        context = build_context(archive, subdir=app.repo_path or "", strip_top=getattr(provider, "archive_prefixed", True))
        repository = f"t-{location.key}/{app.name}"
        if getattr(builder, "name", "") == "docker":
            repository = f"hb-apps/{repository}"
        result = await builder.build(context, repository=repository, tag=build.commit_sha[:12], labels={
            "hirebuddha.tenant": location.key, "hirebuddha.app": app.name, "hirebuddha.commit": build.commit_sha,
            "hirebuddha.template": f"{app.template}@{app.template_version}"})
    except BuildError as caught:
        error = str(caught)
    except Exception as caught:  # noqa: BLE001 - the build fails, it does not crash the worker
        logger.exception("build %s failed", build.id)
        error = f"{type(caught).__name__}: {caught}"
    duration = int(time.monotonic() - started)
    log = (result.log if result else "") or (error or "")
    try:
        await storage.put(f"{prefix}/build.log", log.encode(), content_type="text/plain")
        if result and result.sbom:
            await storage.put(f"{prefix}/sbom.spdx.json", result.sbom, content_type="application/json")
    except Exception:  # noqa: BLE001
        logger.warning("build %s log not stored", build.id, exc_info=True)
    async with app_session(company_id) as db:
        build = await db.get(AppBuild, build.id)
        app = await db.get(App, build.app_id)
        build.finished_at, build.duration_seconds = datetime.utcnow(), duration
        build.cost = Decimal(str(round(duration * settings.APP_BUILD_COST_PER_SECOND, 6)))
        build.log_key = f"{prefix}/build.log"
        if result is not None:
            build.status, build.image, build.image_digest = "succeeded", result.image, result.digest
            build.scan, build.external_id = result.scan or {}, result.external_id
            build.base_image_digest = result.base_image_digest
            build.sbom_key = f"{prefix}/sbom.spdx.json" if result.sbom else None
            if app.status in ("building", "failed", "draft"):
                app.status = "ready"
        else:
            build.status, build.error = "failed", (error or "")[-4000:]
            if app.status == "building":
                app.status = "failed"
        app.updated_at = datetime.utcnow()
        await db.commit()
        view = build_view(build)
    await events.emit(company_id, f"app.build.{'succeeded' if result else 'failed'}", f"app:{app.id}",
                      {"app_id": str(app.id), "app": app.name, "build_id": view["id"], "commit_sha": build.commit_sha,
                       "image_digest": view["image_digest"], "error": (error or "")[:500] or None})
    if result is not None and build.review_id:
        review = await code.get_review(company_id, build.review_id)
        if review["status"] == "open":
            try:
                await deploy(company_id, app.id, build.id, kind="preview", pr_number=review["number"])
            except Exception:  # noqa: BLE001 - the build stands; the preview can be asked for again
                logger.exception("preview of build %s failed", build.id)
    return view


async def list_builds(company_id: Any, app_id: Any) -> List[Dict[str, Any]]:
    async with app_session(company_id) as db:
        await _app(db, company_id, app_id)
        rows = (await db.execute(select(AppBuild).where(AppBuild.app_id == _uuid(app_id))
                                 .order_by(AppBuild.created_at.desc()).limit(50))).scalars().all()
    return [build_view(b) for b in rows]


async def build_log(company_id: Any, app_id: Any, build_id: Any) -> str:
    from src.common.platform.storage import get_storage

    async with app_session(company_id) as db:
        await _app(db, company_id, app_id)
        build = await db.get(AppBuild, _uuid(build_id))
        if build is None or build.app_id != _uuid(app_id):
            raise AppProblem("no such build", 404)
    if not build.log_key:
        return ""
    return (await get_storage().get(build.log_key)).decode(errors="replace")


# ── Deployments ─────────────────────────────────────────────────────────────

def _instance(app: App, kind: str, pr_number: Optional[int]) -> str:
    if kind == "published":
        return app.name
    return f"{app.name}-pr{pr_number}" if pr_number else f"{app.name}-preview"


async def _spec(db: Any, app: App, build: AppBuild, *, kind: str, pr_number: Optional[int], hostnames: List[str],
                previous: List[str], tenant_key: str) -> Any:
    from src.apps.runtime import AppSpec

    secrets_ = await _unseal(db, app)
    settings_ = app.settings or {}
    env = {**(app.env or {}), "HB_TENANT_KEY": tenant_key, "HB_APP": app.name,
           "HB_DATA_API_URL": data_api_url(settings_.get("kind", "web"))}
    if secrets_.get("public_key"):
        env["HB_PUBLIC_KEY"] = secrets_["public_key"]
    # A registry image runs by digest (what was scanned is what runs); a local one by its tag.
    image = build.image
    if build.builder != "docker" and (build.image_digest or "").startswith("sha256:"):
        image = f"{build.image.rsplit(':', 1)[0]}@{build.image_digest}"
    return AppSpec(tenant_key=tenant_key, app=app.name, instance=_instance(app, kind, pr_number), image=image,
                   port=int(settings_.get("port", 8080)), health_path=settings_.get("health_path", "/healthz"),
                   env=env, app_key=secrets_.get("app_key"), resources=app.resources or {},
                   mode=app.mode if kind == "published" else "sleep", hostnames=hostnames,
                   egress=list(app.outbound_allowlist or []), previous_images=previous)


async def _hostnames_for(app: App, kind: str, pr_number: Optional[int]) -> List[str]:
    from src.common.tenancy.session import control_session

    slug = (app.settings or {}).get("hostname_slug") or "app"
    names = [hostname(app.name, slug, pr_number=pr_number, preview=kind == "preview")]
    if kind == "published":
        async with control_session() as cdb:
            names += [d.hostname for d in (await cdb.execute(select(CustomDomain).where(
                CustomDomain.app_id == app.id, CustomDomain.kind == "custom", CustomDomain.status == "verified"))
            ).scalars().all()]
    return names


async def _claim_hostnames(app: App, tenant_key: str, names: List[str], *, kind: str, instance: str) -> None:
    """Record the platform's names in ``custom_domains`` (verified: they are ours) so the edge serves them."""
    from src.apps.controller import APP_PORT
    from src.common.tenancy.session import control_session

    async with control_session() as cdb:
        for name in names:
            row = await cdb.get(CustomDomain, name)
            if row is not None and row.kind == "custom":
                continue
            if row is not None and row.company_id != app.company_id:
                raise AppProblem(f"{name} belongs to another business")
            if row is None:
                row = CustomDomain(hostname=name, company_id=app.company_id, app_id=app.id, kind=kind)
                cdb.add(row)
            row.tenant_key, row.status, row.verified_at = tenant_key, "verified", row.verified_at or datetime.utcnow()
            row.upstream = f"{instance}.t-{tenant_key}.svc.cluster.local:{APP_PORT}"
        await cdb.commit()


async def _forget_hostnames(app_id: Any, *, kinds: tuple = ("preview",), names: Optional[List[str]] = None) -> None:
    from src.common.tenancy.session import control_session

    async with control_session() as cdb:
        query = delete(CustomDomain).where(CustomDomain.app_id == _uuid(app_id), CustomDomain.kind.in_(kinds))
        if names is not None:
            query = query.where(CustomDomain.hostname.in_(names))
        await cdb.execute(query)
        await cdb.commit()


async def deploy(company_id: Any, app_id: Any, build_id: Any, *, kind: str, pr_number: Optional[int] = None,
                 user_id: Any = None) -> Dict[str, Any]:
    """Run a succeeded build as the published app or as a preview."""
    from src.apps import events
    from src.apps.runtime import RuntimeProblem, get_runtime
    from src.common.config import settings

    if kind not in ("preview", "published"):
        raise AppProblem("kind is preview or published", 422)
    location = await _location(company_id)
    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        if not (app.settings or {}).get("kind") or (app.settings or {}).get("kind") == "mobile":
            raise AppProblem("a mobile app is built and published outside HireBuddha")
        build = await db.get(AppBuild, _uuid(build_id))
        if build is None or build.app_id != app.id or build.status != "succeeded":
            raise AppProblem("only a succeeded build of this app can run")
        previous = [d.image_digest for d in (await db.execute(
            select(AppDeployment).where(AppDeployment.app_id == app.id, AppDeployment.kind == "published")
            .order_by(AppDeployment.created_at.desc()).limit(KEEP_PUBLISHED))).scalars().all() if d.image_digest]
        names = await _hostnames_for(app, kind, pr_number)
        spec = await _spec(db, app, build, kind=kind, pr_number=pr_number, hostnames=names,
                           previous=list(reversed(previous)), tenant_key=location.key)
        row = AppDeployment(company_id=app.company_id, app_id=app.id, build_id=build.id, kind=kind,
                            pr_number=pr_number, hostnames=names, image_digest=build.image_digest, status="pending",
                            runtime_ref=f"t-{location.key}/{spec.instance}", deployed_by=_uuid(user_id) if user_id else None,
                            expires_at=datetime.utcnow() + timedelta(days=settings.APP_PREVIEW_DAYS)
                            if kind == "preview" else None)
        db.add(row)
        await db.commit()
    await _claim_hostnames(app, location.key, names, kind="platform" if kind == "published" else "preview",
                           instance=spec.instance)
    try:
        applied = await get_runtime().apply(spec)
        status, error = "active", None
    except (RuntimeProblem, Exception) as caught:  # noqa: BLE001 - recorded on the deployment
        logger.exception("deployment of %s failed", app.name)
        applied, status, error = {}, "failed", str(caught)
    async with app_session(company_id) as db:
        row = await db.get(AppDeployment, row.id)
        app = await db.get(App, app.id)
        row.status, row.url = status, applied.get("url") or (f"https://{names[0]}" if names else None)
        row.runtime_status = {"error": error[:2000]} if error else {}
        row.updated_at = datetime.utcnow()
        if status == "active":
            same = select(AppDeployment).where(AppDeployment.app_id == app.id, AppDeployment.kind == kind,
                                               AppDeployment.status == "active", AppDeployment.id != row.id)
            if kind == "preview":
                same = same.where(AppDeployment.pr_number.is_(None) if pr_number is None
                                  else AppDeployment.pr_number == pr_number)
            for older in (await db.execute(same)).scalars().all():
                older.status = "superseded"
            if kind == "published":
                app.published_deployment_id, app.status = row.id, "published"
                app.settings = {**(app.settings or {}), "published_hostname": names[0] if names else None,
                                "published_url": row.url, "hostnames": sorted(set(names))}
            else:
                app.settings = {**(app.settings or {}),
                                "hostnames": sorted(set((app.settings or {}).get("hostnames") or []) | set(names))}
        app.updated_at = datetime.utcnow()
        await db.commit()
        view = deployment_view(row)
    if status != "active":
        raise AppProblem(f"the app could not be started: {error}", 502)
    await events.emit(company_id, "app.deployed", f"app:{app.id}",
                      {"app_id": str(app.id), "app": app.name, "deployment_id": view["id"], "kind": kind,
                       "pr_number": pr_number, "url": view["url"], "build_id": str(build_id)})
    return view


async def publish(company_id: Any, app_id: Any, *, build_id: Any = None, user_id: Any = None) -> Dict[str, Any]:
    """Publish a build (default: the latest succeeded one)."""
    if build_id is None:
        async with app_session(company_id) as db:
            await _app(db, company_id, app_id)
            build_id = (await db.execute(select(AppBuild.id).where(
                AppBuild.app_id == _uuid(app_id), AppBuild.status == "succeeded")
                .order_by(AppBuild.created_at.desc()).limit(1))).scalar()
        if build_id is None:
            raise AppProblem("there is no succeeded build to publish yet")
    return await deploy(company_id, app_id, build_id, kind="published", user_id=user_id)


async def preview(company_id: Any, app_id: Any, *, build_id: Any = None, user_id: Any = None) -> Dict[str, Any]:
    if build_id is None:
        async with app_session(company_id) as db:
            build_id = (await db.execute(select(AppBuild.id).where(
                AppBuild.app_id == _uuid(app_id), AppBuild.status == "succeeded")
                .order_by(AppBuild.created_at.desc()).limit(1))).scalar()
        if build_id is None:
            raise AppProblem("there is no succeeded build to preview yet")
    return await deploy(company_id, app_id, build_id, kind="preview", user_id=user_id)


async def rollback(company_id: Any, app_id: Any, *, user_id: Any = None) -> Dict[str, Any]:
    """Publish the build that was published before the current one."""
    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        history = (await db.execute(select(AppDeployment).where(
            AppDeployment.app_id == app.id, AppDeployment.kind == "published",
            AppDeployment.status.in_(("active", "superseded", "stopped")))
            .order_by(AppDeployment.created_at.desc()).limit(KEEP_PUBLISHED + 1))).scalars().all()
    current = next((d for d in history if d.id == app.published_deployment_id), None)
    earlier = [d for d in history if current is None or (d.created_at < current.created_at
                                                         and d.build_id != current.build_id)]
    if not earlier:
        raise AppProblem("there is no earlier published version to go back to")
    return await deploy(company_id, app_id, earlier[0].build_id, kind="published", user_id=user_id)


async def _published(company_id: Any, app_id: Any) -> tuple[App, AppDeployment, str]:
    location = await _location(company_id)
    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        row = await db.get(AppDeployment, app.published_deployment_id) if app.published_deployment_id else None
    if row is None:
        raise AppProblem(f"{app.name} is not published")
    return app, row, location.key


async def _reapply(company_id: Any, app_id: Any) -> None:
    from src.apps.runtime import get_runtime

    app, row, tenant_key = await _published(company_id, app_id)
    async with app_session(company_id) as db:
        app = await db.get(App, app.id)
        build = await db.get(AppBuild, row.build_id)
        names = await _hostnames_for(app, "published", None)
        spec = await _spec(db, app, build, kind="published", pr_number=None, hostnames=names, previous=[],
                           tenant_key=tenant_key)
        spec.stopped = app.status == "stopped"
    await _claim_hostnames(app, tenant_key, names, kind="platform", instance=spec.instance)
    await get_runtime().apply(spec)


async def operate(company_id: Any, app_id: Any, action: str) -> Dict[str, Any]:
    """``stop`` | ``start`` | ``restart`` | ``unpublish`` the published app."""
    from src.apps.runtime import get_runtime

    if action not in ("stop", "start", "restart", "unpublish"):
        raise AppProblem("action is stop, start, restart or unpublish", 422)
    app, row, tenant_key = await _published(company_id, app_id)
    runtime = get_runtime()
    namespace = f"t-{tenant_key}"
    if action == "unpublish":
        await runtime.delete(namespace, app.name)
        await _forget_hostnames(app.id, kinds=("platform",))
    else:
        await getattr(runtime, action)(namespace, app.name)
    async with app_session(company_id) as db:
        app = await db.get(App, app.id)
        row = await db.get(AppDeployment, row.id)
        if action == "stop":
            app.status, row.status = "stopped", "stopped"
        elif action == "start":
            app.status, row.status = "published", "active"
        elif action == "unpublish":
            app.status, row.status, app.published_deployment_id = "ready", "stopped", None
        app.updated_at = row.updated_at = datetime.utcnow()
        await db.commit()
        return app_view(app)


async def status(company_id: Any, app_id: Any) -> Dict[str, Any]:
    from src.apps.runtime import get_runtime

    app, row, tenant_key = await _published(company_id, app_id)
    return await get_runtime().status(f"t-{tenant_key}", app.name)


async def logs(company_id: Any, app_id: Any, *, tail: int = 200, since_seconds: Optional[int] = None,
               instance: Optional[str] = None) -> str:
    from src.apps.runtime import get_runtime

    location = await _location(company_id)
    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
    name = instance or app.name
    if not (name == app.name or name.startswith(f"{app.name}-pr") or name == f"{app.name}-preview"):
        raise AppProblem("not an instance of this app", 422)
    return await get_runtime().logs(f"t-{location.key}", name, tail=min(max(tail, 1), 2000),
                                    since_seconds=min(since_seconds or 86400, 86400))


async def metrics(company_id: Any, app_id: Any) -> Dict[str, Any]:
    from src.apps.models import AppUsage
    from src.apps.runtime import get_runtime

    app, _, tenant_key = await _published(company_id, app_id)
    now = await get_runtime().metrics(f"t-{tenant_key}", app.name)
    async with app_session(company_id) as db:
        usage = (await db.execute(select(AppUsage).where(AppUsage.app_id == app.id)
                                  .order_by(AppUsage.window_start.desc()).limit(24))).scalars().all()
    return {"now": now, "hourly": [{"window_start": _iso(u.window_start), "vcpu_hours": float(u.vcpu_hours),
                                    "gb_hours": float(u.gb_hours), "egress_gb": float(u.egress_gb)} for u in usage]}


async def list_deployments(company_id: Any, app_id: Any) -> List[Dict[str, Any]]:
    async with app_session(company_id) as db:
        await _app(db, company_id, app_id)
        rows = (await db.execute(select(AppDeployment).where(AppDeployment.app_id == _uuid(app_id))
                                 .order_by(AppDeployment.created_at.desc()).limit(50))).scalars().all()
    return [deployment_view(d) for d in rows]


async def expire_previews(company_id: Any, app_id: Any = None, *, pr_number: Optional[int] = None,
                          now: Optional[datetime] = None) -> int:
    """Stop previews past their date, or of a pull request that closed."""
    from src.apps.runtime import get_runtime

    location = await _location(company_id)
    now = now or datetime.utcnow()
    query = select(AppDeployment).where(AppDeployment.company_id == _uuid(company_id), AppDeployment.kind == "preview",
                                        AppDeployment.status == "active")
    if app_id is not None:
        query = query.where(AppDeployment.app_id == _uuid(app_id))
    if pr_number is not None:
        query = query.where(AppDeployment.pr_number == pr_number)
    else:
        query = query.where(AppDeployment.expires_at < now)
    async with app_session(company_id) as db:
        rows = (await db.execute(query)).scalars().all()
        apps = {a.id: a for a in (await db.execute(select(App).where(App.id.in_({r.app_id for r in rows})))).scalars()} \
            if rows else {}
    count = 0
    for row in rows:
        app = apps.get(row.app_id)
        if app is None:
            continue
        try:
            await get_runtime().delete(f"t-{location.key}", _instance(app, "preview", row.pr_number))
        except Exception:  # noqa: BLE001 - marked expired anyway; the reaper retries on the cluster
            logger.warning("preview %s not deleted", row.id, exc_info=True)
        await _forget_hostnames(app.id, kinds=("preview",), names=list(row.hostnames or []))
        async with app_session(company_id) as db:
            row = await db.get(AppDeployment, row.id)
            row.status, row.updated_at = "expired", datetime.utcnow()
            await db.commit()
        count += 1
    return count


# ── App users and roles (managed by the business) ───────────────────────────

def role_view(role: AppRole) -> Dict[str, Any]:
    return {"id": str(role.id), "name": role.name, "description": role.description,
            "permissions": role.permissions or {}}


def user_view(user: AppUser, roles: List[str]) -> Dict[str, Any]:
    return {"id": str(user.id), "email": user.email, "name": user.name, "status": user.status, "roles": roles,
            "has_password": bool(user.password_hash), "last_login_at": _iso(user.last_login_at),
            "created_at": _iso(user.created_at)}


async def _roles_by_name(db: Any, app: App, names: List[str]) -> List[AppRole]:
    rows = (await db.execute(select(AppRole).where(AppRole.app_id == app.id, AppRole.name.in_(names)))).scalars().all()
    missing = set(names) - {r.name for r in rows}
    if missing:
        raise AppProblem(f"no such role: {', '.join(sorted(missing))}", 422)
    return list(rows)


async def list_users(company_id: Any, app_id: Any) -> List[Dict[str, Any]]:
    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        users = (await db.execute(select(AppUser).where(AppUser.app_id == app.id).order_by(AppUser.email))
                 ).scalars().all()
        links = (await db.execute(select(AppUserRole.app_user_id, AppRole.name).join(
            AppRole, AppRole.id == AppUserRole.role_id).where(AppRole.app_id == app.id))).all()
    roles: Dict[uuid.UUID, List[str]] = {}
    for user_id, role in links:
        roles.setdefault(user_id, []).append(role)
    return [user_view(u, sorted(roles.get(u.id, []))) for u in users]


async def save_user(company_id: Any, app_id: Any, *, email: str, name: Optional[str] = None,
                    roles: Optional[List[str]] = None, password: Optional[str] = None,
                    status: Optional[str] = None, user_id: Any = None) -> Dict[str, Any]:
    """Add an app user (``invited`` until they sign in) or change one; roles replace the user's roles."""
    from src.data_api.app_users import AuthProblem, hash_password

    email = (email or "").strip().lower()
    if user_id is None and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise AppProblem("a valid e-mail address", 422)
    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        if user_id is not None:
            user = await db.get(AppUser, _uuid(user_id))
            if user is None or user.app_id != app.id:
                raise AppProblem("no such app user", 404)
        else:
            if (await db.execute(select(AppUser.id).where(AppUser.app_id == app.id, AppUser.email == email))).first():
                raise AppProblem(f"{email} is already a user of this app")
            user = AppUser(company_id=app.company_id, app_id=app.id, email=email, status="invited")
            db.add(user)
        if name is not None:
            user.name = tpl.safe_text(name, length=120) or None
        if password:
            try:
                user.password_hash = hash_password(password)
            except AuthProblem as error:
                raise AppProblem(str(error), 422) from None
            if user.status == "invited":
                user.status = "active"
        if status is not None:
            if status not in ("active", "disabled"):
                raise AppProblem("status is active or disabled", 422)
            if status == "disabled" and user.status != "disabled":
                user.token_version += 1   # every token of theirs stops at once
                await db.execute(delete(AppUserSession).where(AppUserSession.app_user_id == user.id))
            user.status = status
        await db.flush()
        if roles is not None:
            rows = await _roles_by_name(db, app, roles)
            await db.execute(delete(AppUserRole).where(AppUserRole.app_user_id == user.id))
            for role in rows:
                db.add(AppUserRole(app_user_id=user.id, role_id=role.id, company_id=app.company_id))
            user.token_version += 1       # the new roles apply to the next token
        user.updated_at = datetime.utcnow()
        await db.commit()
        names = [r for (r,) in (await db.execute(select(AppRole.name).join(
            AppUserRole, AppUserRole.role_id == AppRole.id).where(AppUserRole.app_user_id == user.id))).all()]
        return user_view(user, sorted(names))


async def delete_user(company_id: Any, app_id: Any, user_id: Any) -> None:
    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        user = await db.get(AppUser, _uuid(user_id))
        if user is None or user.app_id != app.id:
            raise AppProblem("no such app user", 404)
        await db.execute(delete(AppUserRole).where(AppUserRole.app_user_id == user.id))
        await db.execute(delete(AppUserSession).where(AppUserSession.app_user_id == user.id))
        await db.delete(user)
        await db.commit()


async def save_role(company_id: Any, app_id: Any, *, name: str, permissions: Dict[str, Any],
                    description: Optional[str] = None) -> Dict[str, Any]:
    """Create or replace a role: ``{"objects": {"lead": ["read", "update"]}, "own_rows": true}``."""
    from src.data_api import tokens

    name = (name or "").strip().lower()
    if not re.match(r"^[a-z][a-z0-9_]{1,39}$", name):
        raise AppProblem("a role name is 2–40 lower-case letters, digits and _", 422)
    try:
        scopes = tokens.validate_scopes({"objects": permissions.get("objects") or {}})
    except ValueError as error:
        raise AppProblem(str(error), 422) from None
    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        unknown = set(scopes["objects"]) - set((app.settings or {}).get("objects") or []) - {"*"}
        if unknown:
            raise AppProblem(f"the app does not work with {', '.join(sorted(unknown))}", 422)
        role = (await db.execute(select(AppRole).where(AppRole.app_id == app.id, AppRole.name == name))
                ).scalar_one_or_none()
        if role is None:
            role = AppRole(company_id=app.company_id, app_id=app.id, name=name)
            db.add(role)
        role.description = tpl.safe_text(description or "", length=200) or None
        role.permissions = {"objects": scopes["objects"], "own_rows": bool(permissions.get("own_rows"))}
        await db.commit()
        return role_view(role)


async def delete_role(company_id: Any, app_id: Any, role_id: Any) -> None:
    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        role = await db.get(AppRole, _uuid(role_id))
        if role is None or role.app_id != app.id:
            raise AppProblem("no such role", 404)
        if (await db.execute(select(AppUserRole.app_user_id).where(AppUserRole.role_id == role.id).limit(1))).first():
            raise AppProblem("people still have this role; take it from them first")
        await db.delete(role)
        await db.commit()


async def invite(company_id: Any, app_id: Any, user_id: Any, return_url: str) -> None:
    """E-mail an invited app user a sign-in link to the app."""
    from src.common.tenancy.directory import directory
    from src.data_api import app_users

    async with app_session(company_id) as db:
        app = await _app(db, company_id, app_id)
        user = await db.get(AppUser, _uuid(user_id))
        if user is None or user.app_id != app.id:
            raise AppProblem("no such app user", 404)
    location = await directory.get(company_id)
    try:
        await app_users.request_magic_link(location.key, app.name, user.email, return_url)
    except app_users.AuthProblem as error:
        raise AppProblem(str(error), error.status) from None

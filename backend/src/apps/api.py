"""Code lanes, Git and tenant apps over HTTP (Phase 14 WS6; tech spec Appendix C).

Everyone in the business reads; owners and admins change (``code.approve``
merges and rejects reviews).

    GET    /api/v1/code-items                          scratch and asset code (?lane, ?status, ?kind)
    GET    /api/v1/code-items/{id}                     one, with its files while scratch
    POST   /api/v1/code-items/{id}/promote             branch + pull request + checks
    GET    /api/v1/code-reviews                        (?status, ?app_id)
    GET    /api/v1/code-reviews/{id}
    POST   /api/v1/code-reviews/{id}/approve           merge through the provider (code.approve)
    POST   /api/v1/code-reviews/{id}/reject            close it (code.approve)
    POST   /api/v1/code-reviews/{id}/checks            run the checks again
    GET    /api/v1/git/repos                           the business's repositories
    POST   /api/v1/git/repos                           create (built-in or GitHub) or import (GitHub)
    POST   /api/v1/git/repos/{id}/push-to-github       connect GitHub later
    GET    /api/v1/app-templates
    GET    /api/v1/apps · POST /api/v1/apps            list · create from a template
    GET    /api/v1/apps/{id} · PATCH · DELETE          detail · settings · archive
    GET    /api/v1/apps/{id}/builds · POST             list · build the default branch (or a commit)
    GET    /api/v1/apps/{id}/builds/{build}/log
    GET    /api/v1/apps/{id}/deployments
    POST   /api/v1/apps/{id}/preview | publish | rollback
    POST   /api/v1/apps/{id}/actions/{stop|start|restart|unpublish}
    GET    /api/v1/apps/{id}/status | logs | metrics
    GET    /api/v1/apps/{id}/domains · POST · POST {host}/verify · DELETE {host}
    GET    /api/v1/apps/{id}/users · POST · PATCH {user} · DELETE {user} · POST {user}/invite
    GET    /api/v1/apps/{id}/roles · PUT {name} · DELETE {role}
    GET    /internal/v1/edge/ask?domain=…&token=…       the tenant edge's on-demand TLS check
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.apps import domains, service as apps
from src.apps import templates as tpl
from src.apps.db import AppsUnavailable
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.auth.roles import ADMIN_ROLES
from src.automation.api import capability
from src.code_lanes import service as code
from src.code_lanes.git import GitError
from src.common.tenancy.session import acting_company_id, get_control_db
from src.billing.features import require_feature

router = APIRouter(tags=["Apps"])


async def _company(request: Request, user: User, db: AsyncSession) -> Any:
    return await acting_company_id(request, user, db)


def _manager(user: User) -> None:
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Owners and admins manage code and apps")


async def _call(awaitable: Any) -> Any:
    try:
        return await awaitable
    except (code.CodeProblem, apps.AppProblem) as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from None
    except AppsUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except (GitError, tpl.TemplateError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


# ── Code items and reviews ──────────────────────────────────────────────────

class PromoteBody(BaseModel):
    repo_id: UUID
    path: Optional[str] = Field(default=None, description="Folder in the repository (default <kind>s/<name>)")


@router.get("/api/v1/code-items", openapi_extra=capability("Scratch and asset code of the business", "read",
                                                           "code.read"))
async def list_code_items(request: Request, lane: Optional[str] = None, status: Optional[str] = None,
                          kind: Optional[str] = None, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_control_db)) -> List[Dict[str, Any]]:
    return await _call(code.list_items(await _company(request, user, db), lane=lane, status=status, kind=kind))


@router.get("/api/v1/code-items/{item_id}", openapi_extra=capability("One code item (with its files while scratch)",
                                                                     "read", "code.read"))
async def get_code_item(item_id: UUID, request: Request, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    return await _call(code.get_item(await _company(request, user, db), item_id, with_files=True))


@router.post("/api/v1/code-items/{item_id}/promote", dependencies=[Depends(require_feature("feature.code.lanes"))], status_code=201, openapi_extra=capability(
    "Open the pull request that makes scratch code an asset; checks run on it", "write_internal", "code.promote",
    idempotent=False))
async def promote(item_id: UUID, body: PromoteBody, request: Request, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(code.promote(await _company(request, user, db), item_id, repo_id=body.repo_id,
                                    user_id=user.id, path=body.path))


@router.get("/api/v1/code-reviews", openapi_extra=capability("Pull requests of code and apps", "read", "code.read"))
async def list_reviews(request: Request, status: Optional[str] = None, app_id: Optional[UUID] = None,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_control_db)
                       ) -> List[Dict[str, Any]]:
    return await _call(code.list_reviews(await _company(request, user, db), status=status, app_id=app_id))


@router.get("/api/v1/code-reviews/{review_id}", openapi_extra=capability("One pull request and its checks", "read",
                                                                         "code.read"))
async def get_review(review_id: UUID, request: Request, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    return await _call(code.get_review(await _company(request, user, db), review_id))


@router.post("/api/v1/code-reviews/{review_id}/approve", openapi_extra=capability(
    "Approve and merge a pull request whose checks passed", "write_external", "code.approve", approval="human",
    idempotent=False))
async def approve_review(review_id: UUID, request: Request, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    return await _call(code.approve(await _company(request, user, db), review_id, user=user))


@router.post("/api/v1/code-reviews/{review_id}/reject", openapi_extra=capability(
    "Close a pull request without merging", "write_external", "code.approve", approval="human"))
async def reject_review(review_id: UUID, request: Request, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    return await _call(code.reject(await _company(request, user, db), review_id, user=user))


@router.post("/api/v1/code-reviews/{review_id}/checks", status_code=202, openapi_extra=capability(
    "Run a pull request's checks again", "write_internal", "code.promote"))
async def rerun_checks(review_id: UUID, request: Request, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_control_db)) -> Dict[str, str]:
    _manager(user)
    company_id = await _company(request, user, db)
    await _call(code.get_review(company_id, review_id))
    await code.queue_checks(company_id, review_id)
    return {"status": "queued"}


# ── Repositories ────────────────────────────────────────────────────────────

class RepoBody(BaseModel):
    name: Optional[str] = Field(default=None, description="A new repository's name")
    provider: str = Field(default="builtin", description="builtin | github")
    connection_id: Optional[UUID] = Field(default=None, description="The GitHub connection (github)")
    import_full_name: Optional[str] = Field(default=None, description="owner/name of a GitHub repository to import")
    description: str = ""


class PushBody(BaseModel):
    connection_id: UUID
    name: Optional[str] = None


@router.get("/api/v1/git/repos", openapi_extra=capability("The business's repositories", "read", "code.read"))
async def list_repos(request: Request, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_control_db)) -> List[Dict[str, Any]]:
    return await _call(code.list_repos(await _company(request, user, db)))


@router.post("/api/v1/git/repos", dependencies=[Depends(require_feature("feature.code.lanes"))], status_code=201, openapi_extra=capability(
    "Create a repository (built-in or GitHub) or import one from GitHub", "write_external", "code.repos",
    idempotent=False))
async def create_repo(body: RepoBody, request: Request, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    company_id = await _company(request, user, db)
    if body.import_full_name:
        if not body.connection_id:
            raise HTTPException(status_code=422, detail="importing needs the GitHub connection_id")
        return await _call(code.import_repo(company_id, user.id, body.connection_id, body.import_full_name))
    if not body.name:
        raise HTTPException(status_code=422, detail="name the repository")
    return await _call(code.create_repo(company_id, user.id, body.name, provider=body.provider,
                                        connection_id=body.connection_id, description=body.description))


@router.post("/api/v1/git/repos/{repo_id}/push-to-github", dependencies=[Depends(require_feature("feature.code.lanes"))], status_code=201, openapi_extra=capability(
    "Push a built-in repository's whole history to a new GitHub repository", "write_external", "code.repos",
    approval="human", idempotent=False))
async def push_to_github(repo_id: UUID, body: PushBody, request: Request, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(code.push_to_github(await _company(request, user, db), repo_id, body.connection_id,
                                           name=body.name, user_id=user.id))


# ── Apps ────────────────────────────────────────────────────────────────────

class AppCreate(BaseModel):
    name: str = Field(..., description="Lower-case, part of its web address: crm")
    display_name: str
    template: str
    objects: List[str] = Field(default_factory=list, description="The business's objects it works with")
    params: Dict[str, Any] = Field(default_factory=dict)
    repo_id: Optional[UUID] = Field(default=None, description="An existing repository (the app goes in apps/<name>)")
    provider: str = "builtin"
    connection_id: Optional[UUID] = None


class AppPatch(BaseModel):
    display_name: Optional[str] = None
    mode: Optional[str] = Field(default=None, description="always_on | sleep")
    resources: Optional[Dict[str, Any]] = Field(default=None, description='{"cpu": "250m", "memory": "256Mi", '
                                                                          '"replicas": 1, "maxReplicas": 2}')
    env: Optional[Dict[str, str]] = None
    outbound_allowlist: Optional[List[str]] = None


class BuildBody(BaseModel):
    commit_sha: Optional[str] = None


class DeployBody(BaseModel):
    build_id: Optional[UUID] = None


@router.get("/api/v1/app-templates", openapi_extra=capability("The app templates (D48 stack)", "read", "apps.read"))
async def list_templates(user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    return tpl.catalog()


@router.get("/api/v1/apps", openapi_extra=capability("The business's apps", "read", "apps.read"))
async def list_apps(request: Request, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_control_db)) -> List[Dict[str, Any]]:
    return await _call(apps.list_apps(await _company(request, user, db)))


@router.post("/api/v1/apps", dependencies=[Depends(require_feature("feature.apps.hosting"))], status_code=201, openapi_extra=capability(
    "Create an app from a template: its repository, first commit, roles, keys and first build", "write_internal",
    "apps.manage", idempotent=False))
async def create_app(body: AppCreate, request: Request, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    company_id = await _company(request, user, db)
    # The plan's number of apps (feature.apps.hosting's limit, Phase 15 T6-2); archived apps do not count.
    from src.billing.features import check_limit, feature_locked
    in_use = len([a for a in await apps.list_apps(company_id) if a.get("status") != "archived"])
    refusal = await check_limit(db, company_id, "feature.apps.hosting", in_use)
    if refusal:
        raise feature_locked("feature.apps.hosting", refusal)
    return await _call(apps.create_app(company_id, user, name=body.name,
                                       display_name=body.display_name, template=body.template, objects=body.objects,
                                       params=body.params, repo_id=body.repo_id, provider=body.provider,
                                       connection_id=body.connection_id))


@router.get("/api/v1/apps/{app_id}", openapi_extra=capability("One app: builds, deployments, roles, domains",
                                                              "read", "apps.read"))
async def get_app(app_id: UUID, request: Request, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    return await _call(apps.get_app(await _company(request, user, db), app_id))


@router.patch("/api/v1/apps/{app_id}", openapi_extra=capability(
    "Change how an app runs: mode, limits, environment, outbound allow-list", "write_internal", "apps.manage"))
async def update_app(app_id: UUID, body: AppPatch, request: Request, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(apps.update_settings(await _company(request, user, db), app_id, **body.model_dump(
        exclude_unset=True)))


@router.delete("/api/v1/apps/{app_id}", openapi_extra=capability(
    "Archive an app: everything it runs stops; repository, builds and users stay", "destructive", "apps.manage",
    approval="human"))
async def archive_app(app_id: UUID, request: Request, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(apps.archive_app(await _company(request, user, db), app_id))


@router.get("/api/v1/apps/{app_id}/builds", openapi_extra=capability("An app's builds", "read", "apps.read"))
async def list_builds(app_id: UUID, request: Request, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_control_db)) -> List[Dict[str, Any]]:
    return await _call(apps.list_builds(await _company(request, user, db), app_id))


@router.post("/api/v1/apps/{app_id}/builds", dependencies=[Depends(require_feature("feature.apps.hosting"))], status_code=202, openapi_extra=capability(
    "Build an app's default branch (or a commit)", "write_internal", "apps.manage", idempotent=False))
async def start_build(app_id: UUID, body: BuildBody, request: Request, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(apps.start_build(await _company(request, user, db), app_id, commit_sha=body.commit_sha,
                                        user_id=user.id))


@router.get("/api/v1/apps/{app_id}/builds/{build_id}/log", response_class=PlainTextResponse,
            openapi_extra=capability("A build's log", "read", "apps.read"))
async def build_log(app_id: UUID, build_id: UUID, request: Request, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_control_db)) -> str:
    return await _call(apps.build_log(await _company(request, user, db), app_id, build_id))


@router.get("/api/v1/apps/{app_id}/deployments", openapi_extra=capability("Where an app runs and ran", "read",
                                                                          "apps.read"))
async def list_deployments(app_id: UUID, request: Request, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_control_db)) -> List[Dict[str, Any]]:
    return await _call(apps.list_deployments(await _company(request, user, db), app_id))


@router.post("/api/v1/apps/{app_id}/preview", dependencies=[Depends(require_feature("feature.apps.hosting"))], status_code=201, openapi_extra=capability(
    "Run a build as a preview (7 days)", "write_internal", "apps.manage", idempotent=False))
async def preview(app_id: UUID, body: DeployBody, request: Request, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(apps.preview(await _company(request, user, db), app_id, build_id=body.build_id,
                                    user_id=user.id))


@router.post("/api/v1/apps/{app_id}/publish", dependencies=[Depends(require_feature("feature.apps.hosting"))], status_code=201, openapi_extra=capability(
    "Publish a build at the app's address and custom domains", "write_external", "apps.publish", approval="human",
    idempotent=False))
async def publish(app_id: UUID, body: DeployBody, request: Request, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(apps.publish(await _company(request, user, db), app_id, build_id=body.build_id,
                                    user_id=user.id))


@router.post("/api/v1/apps/{app_id}/rollback", status_code=201, openapi_extra=capability(
    "Publish the version published before this one", "write_external", "apps.publish", approval="human",
    idempotent=False))
async def rollback(app_id: UUID, request: Request, user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(apps.rollback(await _company(request, user, db), app_id, user_id=user.id))


@router.post("/api/v1/apps/{app_id}/actions/{action}", openapi_extra=capability(
    "Stop, start, restart or unpublish the published app", "write_external", "apps.publish"))
async def operate(app_id: UUID, action: str, request: Request, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(apps.operate(await _company(request, user, db), app_id, action))


@router.get("/api/v1/apps/{app_id}/status", openapi_extra=capability("The published app's state now", "read",
                                                                     "apps.read"))
async def app_status(app_id: UUID, request: Request, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    return await _call(apps.status(await _company(request, user, db), app_id))


@router.get("/api/v1/apps/{app_id}/logs", response_class=PlainTextResponse,
            openapi_extra=capability("An app's recent log lines (24 hours at most)", "read", "apps.read"))
async def app_logs(app_id: UUID, request: Request, tail: int = Query(200, ge=1, le=2000),
                   since_seconds: Optional[int] = Query(None, ge=1, le=86400), instance: Optional[str] = None,
                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_control_db)) -> str:
    return await _call(apps.logs(await _company(request, user, db), app_id, tail=tail, since_seconds=since_seconds,
                                 instance=instance))


@router.get("/api/v1/apps/{app_id}/metrics", openapi_extra=capability("An app's CPU, memory and hourly use",
                                                                      "read", "apps.read"))
async def app_metrics(app_id: UUID, request: Request, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    return await _call(apps.metrics(await _company(request, user, db), app_id))


# ── Domains ─────────────────────────────────────────────────────────────────

class DomainBody(BaseModel):
    hostname: str


@router.get("/api/v1/apps/{app_id}/domains", openapi_extra=capability("An app's addresses and custom domains",
                                                                      "read", "apps.read"))
async def list_domains(app_id: UUID, request: Request, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_control_db)) -> List[Dict[str, Any]]:
    return await _call(domains.list_domains(await _company(request, user, db), app_id))


@router.post("/api/v1/apps/{app_id}/domains", dependencies=[Depends(require_feature("feature.apps.custom_domains"))], status_code=201, openapi_extra=capability(
    "Add a custom domain; the answer says which DNS records to create", "write_internal", "apps.domains"))
async def add_domain(app_id: UUID, body: DomainBody, request: Request, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(domains.add(await _company(request, user, db), app_id, body.hostname))


@router.post("/api/v1/apps/{app_id}/domains/{hostname}/verify", openapi_extra=capability(
    "Check a custom domain's DNS records; once right it is served with HTTPS", "write_internal", "apps.domains"))
async def verify_domain(app_id: UUID, hostname: str, request: Request, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(domains.verify(await _company(request, user, db), app_id, hostname))


@router.delete("/api/v1/apps/{app_id}/domains/{hostname}", status_code=204, response_class=Response,
               response_model=None, openapi_extra=capability("Stop serving a custom domain", "destructive",
                                                             "apps.domains", approval="human"))
async def remove_domain(app_id: UUID, hostname: str, request: Request, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_control_db)) -> Response:
    _manager(user)
    await _call(domains.remove(await _company(request, user, db), app_id, hostname))
    return Response(status_code=204)


# ── App users and roles ─────────────────────────────────────────────────────

class AppUserBody(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    roles: Optional[List[str]] = None
    password: Optional[str] = Field(default=None, description="Optional: else they sign in with an e-mailed link")
    status: Optional[str] = Field(default=None, description="active | disabled")


class InviteBody(BaseModel):
    return_url: str = Field(..., description="The app's address the link opens")


class RoleBody(BaseModel):
    description: Optional[str] = None
    objects: Dict[str, List[str]]
    own_rows: bool = False


@router.get("/api/v1/apps/{app_id}/users", openapi_extra=capability("The people who sign in to an app", "read",
                                                                    "apps.users"))
async def list_app_users(app_id: UUID, request: Request, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_control_db)) -> List[Dict[str, Any]]:
    _manager(user)
    return await _call(apps.list_users(await _company(request, user, db), app_id))


@router.post("/api/v1/apps/{app_id}/users", status_code=201, openapi_extra=capability(
    "Add an app user with roles", "write_internal", "apps.users", idempotent=False))
async def add_app_user(app_id: UUID, body: AppUserBody, request: Request, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(apps.save_user(await _company(request, user, db), app_id, email=body.email or "",
                                      name=body.name, roles=body.roles or [], password=body.password))


@router.patch("/api/v1/apps/{app_id}/users/{app_user_id}", openapi_extra=capability(
    "Change an app user: name, roles, password, active or disabled", "write_internal", "apps.users"))
async def update_app_user(app_id: UUID, app_user_id: UUID, body: AppUserBody, request: Request,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_control_db)
                          ) -> Dict[str, Any]:
    _manager(user)
    return await _call(apps.save_user(await _company(request, user, db), app_id, email=body.email or "",
                                      name=body.name, roles=body.roles, password=body.password, status=body.status,
                                      user_id=app_user_id))


@router.delete("/api/v1/apps/{app_id}/users/{app_user_id}", status_code=204, response_class=Response,
               response_model=None, openapi_extra=capability("Remove an app user", "destructive", "apps.users",
                                                             approval="human"))
async def delete_app_user(app_id: UUID, app_user_id: UUID, request: Request, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_control_db)) -> Response:
    _manager(user)
    await _call(apps.delete_user(await _company(request, user, db), app_id, app_user_id))
    return Response(status_code=204)


@router.post("/api/v1/apps/{app_id}/users/{app_user_id}/invite", status_code=202, openapi_extra=capability(
    "E-mail an app user a sign-in link", "write_external", "apps.users"))
async def invite_app_user(app_id: UUID, app_user_id: UUID, body: InviteBody, request: Request,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_control_db)
                          ) -> Dict[str, str]:
    _manager(user)
    await _call(apps.invite(await _company(request, user, db), app_id, app_user_id, body.return_url))
    return {"status": "sent"}


@router.get("/api/v1/apps/{app_id}/roles", openapi_extra=capability("An app's roles", "read", "apps.users"))
async def list_roles(app_id: UUID, request: Request, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_control_db)) -> List[Dict[str, Any]]:
    company_id = await _company(request, user, db)
    return (await _call(apps.get_app(company_id, app_id)))["roles"]


@router.put("/api/v1/apps/{app_id}/roles/{name}", openapi_extra=capability(
    "Create or replace a role: objects, operations, own rows only", "write_internal", "apps.users"))
async def save_role(app_id: UUID, name: str, body: RoleBody, request: Request, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    _manager(user)
    return await _call(apps.save_role(await _company(request, user, db), app_id, name=name, description=body.description,
                                      permissions={"objects": body.objects, "own_rows": body.own_rows}))


@router.delete("/api/v1/apps/{app_id}/roles/{role_id}", status_code=204, response_class=Response,
               response_model=None, openapi_extra=capability("Delete a role no one has", "destructive", "apps.users",
                                                             approval="human"))
async def delete_role(app_id: UUID, role_id: UUID, request: Request, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_control_db)) -> Response:
    _manager(user)
    await _call(apps.delete_role(await _company(request, user, db), app_id, role_id))
    return Response(status_code=204)


# ── The tenant edge ─────────────────────────────────────────────────────────

def edge_token() -> str:
    """What the edge sends with ``ask`` (in its URL: Caddy adds only ``domain``)."""
    from src.common.config import settings

    return hmac.new(settings.SECRET_KEY.encode(), b"tenant-edge-ask", hashlib.sha256).hexdigest()[:32]


@router.get("/internal/v1/edge/ask", include_in_schema=False)
async def edge_ask(domain: str = Query(...), token: str = Query("")) -> Response:
    """200 when the tenant edge may obtain a certificate for, and serve, ``domain``; else 404."""
    if not hmac.compare_digest(token.encode(), edge_token().encode()):
        return Response(status_code=403)
    return Response(status_code=200 if await domains.may_serve(domain) else 404)

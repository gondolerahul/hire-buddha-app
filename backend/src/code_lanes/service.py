"""Scratch and asset code, and promotion between them (Phase 14 WS6 6.3–6.5; tech spec §11.2, §11.3; D35, D36).

* **Scratch** — what an agent writes while it works (a script, a synthesized
  tool, a skill script, an app's first draft): its files in Blob under
  ``<namespace>/scratch/code/<item>/``, a ``code_items`` row, and a
  ``time_index`` entry (``scratch_cleanup``) that deletes it after
  ``CODE_SCRATCH_RETENTION_DAYS`` unless it is promoted. Nothing at runtime
  loads code from scratch.
* **Promotion** (``POST /api/v1/code-items/{id}/promote``): a branch
  ``hb/<run-or-item>-<slug>`` with the files and a test scaffold in a
  repository of the business (GitHub or built-in), a pull request, then the
  checks (``checks.py``), posted to the pull request and stored on the
  review. A person with ``code.approve`` (owners and admins) merges — in
  GitHub, or by approving here, which merges through the App and records who
  approved. The item becomes an **asset**: repository, path, commit.
* An app's code goes through the same reviews (``app_id`` on the review); a
  merge starts its build.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, select

from src.code_lanes.git import GitError, GitProvider, builtin_provider, check_path, org_for
from src.code_lanes.models import CODE_KINDS, CodeItem, CodeReview, GitRepo

logger = logging.getLogger(__name__)

APPROVER_ROLES = ("tenant_admin", "partner_admin", "app_admin")
MAX_SCRATCH_BYTES = 5 * 1024 * 1024
MAX_FILES = 200


class CodeProblem(RuntimeError):
    """A code-lane request that cannot be done; ``status`` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def can_approve(user: Any) -> bool:
    """The ``code.approve`` permission: the business's owners and admins."""
    return getattr(user, "role", None) in APPROVER_ROLES


def slug(text: Any, *, length: int = 40) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (cleaned[:length].strip("-")) or "change"


def _uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


# ── Repositories ────────────────────────────────────────────────────────────

def provider_for(repo: GitRepo) -> GitProvider:
    if repo.provider == "github":
        from src.code_lanes.github import GitHubProvider

        if repo.connection_id is None:
            raise CodeProblem(f"{repo.full_name} has no GitHub connection")
        return GitHubProvider(repo.company_id, repo.connection_id)
    return builtin_provider()


def repo_view(repo: GitRepo) -> Dict[str, Any]:
    return {"id": str(repo.id), "provider": repo.provider, "full_name": repo.full_name,
            "default_branch": repo.default_branch, "url": repo.url,
            "connection_id": str(repo.connection_id) if repo.connection_id else None,
            "moved_to_repo_id": str(repo.moved_to_repo_id) if repo.moved_to_repo_id else None,
            "created_at": repo.created_at.isoformat() + "Z" if repo.created_at else None}


async def _github_connection(company_id: Any, connection_id: Any) -> Any:
    """The business's GitHub connection (connections live where ``tenant_session`` opens)."""
    from src.common.tenancy.session import tenant_session
    from src.connections.models import Connection

    async with tenant_session(company_id) as db:
        connection = await db.get(Connection, _uuid(connection_id))
    if connection is None or connection.company_id != _uuid(company_id) or connection.connector_id != "github":
        raise CodeProblem("no such GitHub connection", 404)
    if connection.status not in ("active", "expiring"):
        raise CodeProblem("the GitHub connection needs to be reconnected")
    return connection


async def create_repo(company_id: Any, user_id: Any, name: str, *, provider: str = "builtin",
                      connection_id: Any = None, description: str = "") -> Dict[str, Any]:
    """A new repository: in the built-in Git (``t-<key>/<name>``) or the GitHub organisation the App is on."""
    from src.apps.db import code_session

    company_id = _uuid(company_id)
    if provider == "github":
        from src.code_lanes.github import GitHubProvider

        await _github_connection(company_id, connection_id)
        github = GitHubProvider(company_id, _uuid(connection_id))
        info = await github.create_repo(await github.account(), name, description=description)
    elif provider == "builtin":
        info = await builtin_provider().create_repo(await org_for(company_id), name, description=description)
    else:
        raise CodeProblem("provider is github or builtin", 422)
    async with code_session(company_id) as db:
        repo = GitRepo(company_id=company_id, provider=provider, external_repo_id=info.external_id,
                       full_name=info.full_name, default_branch=info.default_branch,
                       connection_id=_uuid(connection_id) if connection_id else None, url=info.url,
                       created_by=_uuid(user_id) if user_id else None)
        db.add(repo)
        await db.commit()
        return repo_view(repo)


async def import_repo(company_id: Any, user_id: Any, connection_id: Any, full_name: str) -> Dict[str, Any]:
    """Record a GitHub repository the App can already reach."""
    from src.code_lanes.github import GitHubProvider
    from src.apps.db import code_session

    company_id = _uuid(company_id)
    await _github_connection(company_id, connection_id)
    async with code_session(company_id) as db:
        existing = (await db.execute(select(GitRepo).where(
            GitRepo.company_id == company_id, GitRepo.provider == "github", GitRepo.full_name == full_name))
        ).scalar_one_or_none()
        if existing is not None:
            return repo_view(existing)
    try:
        info = await GitHubProvider(company_id, _uuid(connection_id)).repo(full_name)
    except GitError as error:
        raise CodeProblem(f"the App cannot reach {full_name}: {error}", 404) from None
    async with code_session(company_id) as db:
        repo = GitRepo(company_id=company_id, provider="github", external_repo_id=info.external_id,
                       full_name=info.full_name, default_branch=info.default_branch,
                       connection_id=_uuid(connection_id), url=info.url, created_by=_uuid(user_id) if user_id else None)
        db.add(repo)
        await db.commit()
        return repo_view(repo)


async def list_repos(company_id: Any) -> List[Dict[str, Any]]:
    from src.apps.db import code_session

    async with code_session(company_id) as db:
        rows = (await db.execute(select(GitRepo).where(GitRepo.company_id == _uuid(company_id))
                                 .order_by(GitRepo.created_at))).scalars().all()
    return [repo_view(r) for r in rows]


async def _repo(db: Any, company_id: Any, repo_id: Any) -> GitRepo:
    repo = await db.get(GitRepo, _uuid(repo_id))
    if repo is None or repo.company_id != _uuid(company_id):
        raise CodeProblem("no such repository", 404)
    if repo.moved_to_repo_id is not None:
        moved = await db.get(GitRepo, repo.moved_to_repo_id)
        if moved is not None:
            return moved
    return repo


async def push_to_github(company_id: Any, repo_id: Any, connection_id: Any, *, name: Optional[str] = None,
                         user_id: Any = None) -> Dict[str, Any]:
    """"Connect GitHub later": a built-in repository's whole history pushed to a new
    repository in the business's GitHub organisation; apps that used it follow."""
    from src.apps.models import App
    from src.code_lanes.github import GitHubProvider
    from src.apps.db import code_session

    company_id = _uuid(company_id)
    async with code_session(company_id) as db:
        source = await db.get(GitRepo, _uuid(repo_id))
        if source is None or source.company_id != company_id:
            raise CodeProblem("no such repository", 404)
        if source.provider != "builtin" or source.moved_to_repo_id is not None:
            raise CodeProblem("only a built-in repository that has not moved can be pushed to GitHub")
    await _github_connection(company_id, connection_id)
    github = GitHubProvider(company_id, _uuid(connection_id))
    target_name = name or source.full_name.split("/", 1)[1]
    owner = await github.account()
    info = await github._call("POST", f"/orgs/{owner}/repos", body={  # noqa: SLF001 - empty, so history pushes cleanly
        "name": target_name, "private": True, "auto_init": False}, ok=(201,))
    await builtin_provider().push_history(source.full_name, await github.push_url(info["full_name"]))
    async with code_session(company_id) as db:
        target = GitRepo(company_id=company_id, provider="github", external_repo_id=str(info["id"]),
                         full_name=info["full_name"], default_branch=source.default_branch,
                         connection_id=_uuid(connection_id), url=info.get("html_url"),
                         created_by=_uuid(user_id) if user_id else None)
        db.add(target)
        await db.flush()
        source = await db.get(GitRepo, source.id)
        source.moved_to_repo_id = target.id
        for app in (await db.execute(select(App).where(App.company_id == company_id, App.repo_id == source.id))
                    ).scalars().all():
            app.repo_id = target.id
        await db.commit()
        return repo_view(target)


# ── Scratch ─────────────────────────────────────────────────────────────────

def item_view(item: CodeItem, review: Optional[CodeReview] = None) -> Dict[str, Any]:
    out = {"id": str(item.id), "lane": item.lane, "kind": item.kind, "name": item.name,
           "description": item.description, "status": item.status, "files": item.files or [],
           "repo_id": str(item.repo_id) if item.repo_id else None, "path": item.path, "commit_sha": item.commit_sha,
           "review_id": str(item.review_id) if item.review_id else None,
           "app_id": str(item.app_id) if item.app_id else None,
           "created_by_run_id": str(item.created_by_run_id) if item.created_by_run_id else None,
           "retention_until": item.retention_until.isoformat() + "Z" if item.retention_until else None,
           "created_at": item.created_at.isoformat() + "Z" if item.created_at else None}
    if review is not None:
        out["review"] = review_view(review)
    return out


def review_view(review: CodeReview) -> Dict[str, Any]:
    return {"id": str(review.id), "repo_id": str(review.repo_id), "number": review.number, "title": review.title,
            "branch": review.branch, "base_branch": review.base_branch, "url": review.url, "status": review.status,
            "head_sha": review.head_sha, "merge_sha": review.merge_sha, "checks_status": review.checks_status,
            "checks": review.checks or [],
            "code_item_id": str(review.code_item_id) if review.code_item_id else None,
            "app_id": str(review.app_id) if review.app_id else None,
            "merged_by_user_id": str(review.merged_by_user_id) if review.merged_by_user_id else None,
            "merged_by_login": review.merged_by_login,
            "merged_at": review.merged_at.isoformat() + "Z" if review.merged_at else None,
            "created_at": review.created_at.isoformat() + "Z" if review.created_at else None}


def _scratch_prefix(company_id: Any, item_id: Any) -> str:
    from src.common.platform.storage import company_namespace

    return f"{company_namespace(company_id)}/scratch/code/{item_id}"


async def _index(company_id: Any, item_id: Any, due: Optional[datetime]) -> None:
    from src.automation.models import TimeIndexEntry
    from src.common.tenancy.session import control_session

    async with control_session() as cdb:
        await cdb.execute(delete(TimeIndexEntry).where(
            TimeIndexEntry.company_id == _uuid(company_id), TimeIndexEntry.ref_kind == "scratch_cleanup",
            TimeIndexEntry.ref_id == _uuid(item_id)))
        if due is not None:
            cdb.add(TimeIndexEntry(company_id=_uuid(company_id), ref_kind="scratch_cleanup", ref_id=_uuid(item_id),
                                   due_at=due))
        await cdb.commit()


async def register_scratch(company_id: Any, *, kind: str, name: str, files: Dict[str, Any],
                           description: Optional[str] = None, run_id: Any = None, user_id: Any = None,
                           app_id: Any = None, tool_registry_id: Any = None) -> Dict[str, Any]:
    """Keep what an agent wrote as scratch code (files in Blob, a row, a clean-up date)."""
    from src.common.config import settings
    from src.common.platform.storage import get_storage
    from src.apps.db import code_session

    if kind not in CODE_KINDS:
        raise CodeProblem(f"kind is one of {', '.join(CODE_KINDS)}", 422)
    if not files or len(files) > MAX_FILES:
        raise CodeProblem(f"between 1 and {MAX_FILES} files", 422)
    encoded = {check_path(p): (c if isinstance(c, bytes) else str(c).encode()) for p, c in files.items()}
    if sum(len(c) for c in encoded.values()) > MAX_SCRATCH_BYTES:
        raise CodeProblem("scratch code is at most 5 MB", 413)
    company_id = _uuid(company_id)
    item_id = uuid.uuid4()
    prefix = _scratch_prefix(company_id, item_id)
    storage = get_storage()
    for path, content in encoded.items():
        await storage.put(f"{prefix}/{path}", content, content_type="text/plain")
    async with code_session(company_id) as db:
        from src.schema_engine.models import RecordsSettings

        policy = await db.get(RecordsSettings, company_id)
    # The business's own retention (tenant settings, 1–30 days), else the platform's.
    days = (policy.scratch_retention_days if policy else None) or settings.CODE_SCRATCH_RETENTION_DAYS
    retention = datetime.utcnow() + timedelta(days=days)
    async with code_session(company_id) as db:
        item = CodeItem(id=item_id, company_id=company_id, lane="scratch", kind=kind, name=name[:200],
                        description=description, scratch_ref=prefix, files=sorted(encoded),
                        created_by_run_id=_uuid(run_id) if run_id else None,
                        created_by_user_id=_uuid(user_id) if user_id else None,
                        app_id=_uuid(app_id) if app_id else None,
                        tool_registry_id=_uuid(tool_registry_id) if tool_registry_id else None,
                        retention_until=retention, status="active")
        db.add(item)
        await db.commit()
        view = item_view(item)
    await _index(company_id, item_id, retention)
    return view


async def scratch_files(item: CodeItem) -> Dict[str, bytes]:
    from src.common.platform.storage import get_storage

    storage = get_storage()
    return {path: await storage.get(f"{item.scratch_ref}/{path}") for path in (item.files or [])}


async def _delete_scratch(item: CodeItem) -> None:
    from src.common.platform.storage import get_storage

    storage = get_storage()
    for path in item.files or []:
        try:
            await storage.delete(f"{item.scratch_ref}/{path}")
        except Exception:  # noqa: BLE001 - a file already gone
            pass


async def list_items(company_id: Any, *, lane: Optional[str] = None, status: Optional[str] = None,
                     kind: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    from src.apps.db import code_session

    query = select(CodeItem).where(CodeItem.company_id == _uuid(company_id))
    if lane:
        query = query.where(CodeItem.lane == lane)
    if status:
        query = query.where(CodeItem.status == status)
    if kind:
        query = query.where(CodeItem.kind == kind)
    async with code_session(company_id) as db:
        rows = (await db.execute(query.order_by(CodeItem.created_at.desc()).limit(limit))).scalars().all()
    return [item_view(r) for r in rows]


async def get_item(company_id: Any, item_id: Any, *, with_files: bool = False) -> Dict[str, Any]:
    from src.apps.db import code_session

    async with code_session(company_id) as db:
        item = await db.get(CodeItem, _uuid(item_id))
        if item is None or item.company_id != _uuid(company_id):
            raise CodeProblem("no such code item", 404)
        review = await db.get(CodeReview, item.review_id) if item.review_id else None
    view = item_view(item, review)
    if with_files and item.lane == "scratch" and item.status != "expired":
        view["contents"] = {p: c.decode("utf-8", errors="replace") for p, c in (await scratch_files(item)).items()}
    return view


async def expire_scratch(company_id: Any, item_id: Any) -> Dict[str, Any]:
    """The clean-up date passed (``time_index`` ``scratch_cleanup``): delete what was never promoted."""
    from src.apps.db import code_session

    async with code_session(company_id) as db:
        item = await db.get(CodeItem, _uuid(item_id))
        if item is None or item.lane != "scratch" or item.status in ("promoting", "promoted", "expired"):
            return {"item": str(item_id), "expired": False}
        await _delete_scratch(item)
        item.status = "expired"
        item.updated_at = datetime.utcnow()
        await db.commit()
    return {"item": str(item_id), "expired": True}


# ── Promotion ───────────────────────────────────────────────────────────────

def test_scaffold(kind: str, files: Dict[str, bytes], base: str) -> Dict[str, bytes]:
    """A smoke test when the code brings none: every Python file must compile."""
    if any(p.rsplit("/", 1)[-1].startswith("test_") for p in files) or not any(p.endswith(".py") for p in files):
        return {}
    body = (
        '"""Added by HireBuddha on promotion: every Python file here compiles. Replace with real tests."""\n'
        "import pathlib\nimport py_compile\n\n\n"
        "def test_python_files_compile():\n"
        "    here = pathlib.Path(__file__).parent\n"
        "    for path in here.rglob('*.py'):\n"
        "        py_compile.compile(str(path), doraise=True)\n")
    return {f"{base}test_smoke.py": body.encode()}


async def promote(company_id: Any, item_id: Any, *, repo_id: Any, user_id: Any = None, run_id: Any = None,
                  path: Optional[str] = None, run_checks: bool = True) -> Dict[str, Any]:
    """Open the pull request that would make a scratch item an asset, and start its checks."""
    from src.apps import events
    from src.apps.db import code_session

    company_id = _uuid(company_id)
    async with code_session(company_id) as db:
        item = await db.get(CodeItem, _uuid(item_id))
        if item is None or item.company_id != company_id:
            raise CodeProblem("no such code item", 404)
        if item.lane != "scratch" or item.status not in ("active", "rejected"):
            raise CodeProblem(f"{item.name} is {item.lane}/{item.status}: only active scratch code is promoted")
        repo = await _repo(db, company_id, repo_id)
    files = await scratch_files(item)
    base = (path.strip("/") + "/") if path else f"{item.kind}s/{slug(item.name)}/"
    tree = {f"{base}{p}": c for p, c in files.items()}
    tree.update(test_scaffold(item.kind, tree, base))
    provider = provider_for(repo)
    branch = f"hb/{(_uuid(run_id) if run_id else item.id).hex[:8]}-{slug(item.name, length=30)}"
    title = f"Promote {item.kind.replace('_', ' ')} {item.name}"
    body = "\n".join([item.description or "", "", f"Code item `{item.id}` from HireBuddha"
                      + (f", written by run `{run_id or item.created_by_run_id}`" if run_id or item.created_by_run_id else "")
                      + ".", "", "Files:", *[f"- `{p}`" for p in sorted(tree)]]).strip()
    try:
        head = await provider.commit_files(repo.full_name, branch=branch, base=repo.default_branch, files=tree,
                                           message=title)
        opened = await provider.open_review(repo.full_name, branch=branch, base=repo.default_branch, title=title,
                                            body=body)
    except GitError as error:
        raise CodeProblem(f"could not open the pull request: {error}", 502) from None
    async with code_session(company_id) as db:
        review = CodeReview(company_id=company_id, repo_id=repo.id, number=opened.number, code_item_id=item.id,
                            title=title, body=body, branch=branch, base_branch=repo.default_branch, url=opened.url,
                            status="open", head_sha=opened.head_sha or head, checks_status="pending",
                            opened_by_run_id=_uuid(run_id) if run_id else None,
                            opened_by_user_id=_uuid(user_id) if user_id else None)
        db.add(review)
        await db.flush()
        item = await db.get(CodeItem, item.id)
        item.status, item.review_id, item.repo_id, item.path = "promoting", review.id, repo.id, base.rstrip("/")
        item.updated_at = datetime.utcnow()
        await db.commit()
        view = review_view(review)
    await events.emit(company_id, "code.review.opened", f"code_review:{review.id}",
                      {"review_id": view["id"], "code_item_id": str(item.id), "repo": repo.full_name,
                       "number": opened.number, "url": opened.url}, source="code_lanes")
    if run_checks:
        await queue_checks(company_id, review.id)
    return view


async def open_change(company_id: Any, *, repo_id: Any, branch: str, files: Dict[str, bytes], title: str,
                      body: str = "", app_id: Any = None, run_id: Any = None, user_id: Any = None,
                      delete_paths: Optional[List[str]] = None, run_checks: bool = True) -> Dict[str, Any]:
    """An agent's (or a template's) change to a repository: a branch and a pull request
    (``hb/<run-id>-<slug>``), reviewed like a promotion. Used for apps."""
    from src.apps import events
    from src.apps.db import code_session

    company_id = _uuid(company_id)
    async with code_session(company_id) as db:
        repo = await _repo(db, company_id, repo_id)
    provider = provider_for(repo)
    try:
        head = await provider.commit_files(repo.full_name, branch=branch, base=repo.default_branch, files=files,
                                           message=title, delete=delete_paths or ())
        opened = await provider.open_review(repo.full_name, branch=branch, base=repo.default_branch, title=title,
                                            body=body)
    except GitError as error:
        raise CodeProblem(f"could not open the pull request: {error}", 502) from None
    async with code_session(company_id) as db:
        review = (await db.execute(select(CodeReview).where(CodeReview.repo_id == repo.id,
                                                            CodeReview.number == opened.number))).scalar_one_or_none()
        if review is None:
            review = CodeReview(company_id=company_id, repo_id=repo.id, number=opened.number, title=title,
                                body=body, branch=branch, base_branch=repo.default_branch, url=opened.url,
                                app_id=_uuid(app_id) if app_id else None, opened_by_run_id=_uuid(run_id) if run_id else None,
                                opened_by_user_id=_uuid(user_id) if user_id else None)
            db.add(review)
        review.status, review.head_sha, review.checks_status = "open", opened.head_sha or head, "pending"
        review.updated_at = datetime.utcnow()
        await db.commit()
        view = review_view(review)
    await events.emit(company_id, "code.review.opened", f"code_review:{review.id}",
                      {"review_id": view["id"], "app_id": str(app_id) if app_id else None, "repo": repo.full_name,
                       "number": opened.number, "url": opened.url}, source="code_lanes")
    if run_checks:
        await queue_checks(company_id, review.id)
    return view


async def queue_checks(company_id: Any, review_id: Any) -> None:
    """Run the checks in a worker (``run_review_checks``); inline when there is no queue."""
    from src.common.job_queue import enqueue_job, tenant_arg

    try:
        await enqueue_job("run_review_checks", str(review_id), company_id=tenant_arg(company_id),
                          _job_id=f"checks:{review_id}")
    except Exception:  # noqa: BLE001 - no Redis: run them here
        logger.warning("checks for review %s run inline (no job queue)", review_id, exc_info=True)
        await run_review_checks(company_id, review_id)


async def _files_at(provider: GitProvider, repo: GitRepo, review: CodeReview) -> Dict[str, bytes]:
    import io
    import tarfile

    data = await provider.archive(repo.full_name, review.head_sha or review.branch)
    files: Dict[str, bytes] = {}
    strip = getattr(provider, "archive_prefixed", True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile() or (strip and "/" not in member.name):
                continue
            name = member.name.split("/", 1)[1] if strip else member.name
            handle = archive.extractfile(member)
            if handle is not None and member.size <= MAX_SCRATCH_BYTES:
                files[name] = handle.read()
    return files


async def run_review_checks(company_id: Any, review_id: Any, *, runner: Any = None) -> Dict[str, Any]:
    """Run a review's checks on its head, post them to the pull request, keep them on the review."""
    from src.apps import events
    from src.code_lanes.checks import checks_runner, overall
    from src.apps.db import code_session

    company_id = _uuid(company_id)
    async with code_session(company_id) as db:
        review = await db.get(CodeReview, _uuid(review_id))
        if review is None or review.status != "open":
            return {"review": str(review_id), "skipped": True}
        repo = await db.get(GitRepo, review.repo_id)
        review.checks_status = "running"
        await db.commit()
    provider = provider_for(repo)
    try:
        files = await _files_at(provider, repo, review)
        results = await (runner or checks_runner()).run(company_id, files)
    except Exception as error:  # noqa: BLE001 - a check that could not run fails the review
        logger.exception("checks of review %s failed to run", review_id)
        results = [{"name": "checks", "conclusion": "failure", "summary": f"could not run: {error}"[:2000],
                    "tool": "platform"}]
    for result in results:
        try:
            await provider.post_check(repo.full_name, review.head_sha or "", name=result["name"],
                                      conclusion=result["conclusion"], summary=result.get("summary") or "",
                                      number=review.number)
        except Exception:  # noqa: BLE001 - the results stay on the review even if the provider refused them
            logger.warning("check %s not posted to %s#%s", result["name"], repo.full_name, review.number,
                           exc_info=True)
    status = overall(results)
    async with code_session(company_id) as db:
        review = await db.get(CodeReview, review.id)
        review.checks, review.checks_status, review.updated_at = results, status, datetime.utcnow()
        await db.commit()
        view = review_view(review)
    await events.emit(company_id, "code.checks.completed", f"code_review:{review.id}",
                      {"review_id": view["id"], "status": status, "repo": repo.full_name, "number": review.number,
                       "checks": [{"name": r["name"], "conclusion": r["conclusion"]} for r in results]},
                      source="code_lanes")
    return view


async def _merged(db: Any, company_id: Any, review: CodeReview, *, merge_sha: Optional[str],
                  user_id: Any = None, login: Optional[str] = None) -> Optional[CodeItem]:
    review.status, review.merge_sha, review.merged_at = "merged", merge_sha, datetime.utcnow()
    review.merged_by_user_id = _uuid(user_id) if user_id else None
    review.merged_by_login = login
    review.updated_at = datetime.utcnow()
    item = await db.get(CodeItem, review.code_item_id) if review.code_item_id else None
    if item is not None:
        item.lane, item.status, item.commit_sha = "asset", "promoted", merge_sha
        item.retention_until, item.updated_at = None, datetime.utcnow()
    return item


async def _after_merge(company_id: Any, review: Dict[str, Any], item: Optional[CodeItem]) -> None:
    from src.apps import events

    if item is not None:
        await _index(company_id, item.id, None)
        await _delete_scratch(item)
        if item.tool_registry_id:
            await _record_tool_asset(item, review)
        await events.emit(company_id, "code.promoted", f"code_item:{item.id}",
                          {"code_item_id": str(item.id), "kind": item.kind, "name": item.name,
                           "commit_sha": item.commit_sha, "path": item.path, "review_id": review["id"]},
                          source="code_lanes")
    if review.get("app_id") and review.get("merge_sha"):
        from src.apps import service as apps

        try:
            await apps.start_build(company_id, review["app_id"], commit_sha=review["merge_sha"],
                                   review_id=review["id"])
        except Exception:  # noqa: BLE001 - the merge stands; the build can be started again
            logger.exception("build after merge of review %s not started", review["id"])


async def _record_tool_asset(item: CodeItem, review: Dict[str, Any]) -> None:
    """A synthesized tool's code is now reviewed: its registry row records where it lives.
    Enabling the tool stays the tool admin's switch."""
    from src.ai.orm.tools import ToolRegistryEntry
    from src.common.tenancy.session import control_session

    async with control_session() as cdb:
        entry = await cdb.get(ToolRegistryEntry, item.tool_registry_id)
        if entry is None:
            return
        entry.configuration = {**(entry.configuration or {}), "code_item_id": str(item.id), "asset": {
            "repo_id": str(item.repo_id), "path": item.path, "commit_sha": item.commit_sha,
            "review_id": review["id"]}}
        await cdb.commit()


async def approve(company_id: Any, review_id: Any, *, user: Any) -> Dict[str, Any]:
    """Merge a review whose checks passed, through the provider, as an approval of ``user``."""
    from src.apps.db import code_session

    if not can_approve(user):
        raise CodeProblem("approving code needs the code.approve permission (owners and admins)", 403)
    company_id = _uuid(company_id)
    async with code_session(company_id) as db:
        review = await db.get(CodeReview, _uuid(review_id))
        if review is None or review.company_id != company_id:
            raise CodeProblem("no such review", 404)
        if review.status != "open":
            raise CodeProblem(f"the pull request is {review.status}")
        if review.checks_status != "passed":
            raise CodeProblem(f"its checks have not passed ({review.checks_status}); fix them, or merge in GitHub")
        repo = await db.get(GitRepo, review.repo_id)
    provider = provider_for(repo)
    who = getattr(user, "email", None) or str(getattr(user, "id", ""))
    try:
        current = await provider.review(repo.full_name, review.number)
        if current.status != "open":
            return await review_closed_outside(company_id, repo.provider, repo.full_name, review.number,
                                               merged=current.status == "merged", merge_sha=current.merge_sha,
                                               merged_by=current.merged_by)
        if review.head_sha and current.head_sha and current.head_sha != review.head_sha:
            raise CodeProblem("the pull request changed since its checks ran; they run again", 409)
        merge_sha = await provider.merge(repo.full_name, review.number, message=review.title, merged_by=who)
    except GitError as error:
        raise CodeProblem(f"could not merge: {error}", 502) from None
    async with code_session(company_id) as db:
        review = await db.get(CodeReview, review.id)
        item = await _merged(db, company_id, review, merge_sha=merge_sha, user_id=getattr(user, "id", None),
                             login=who)
        await db.commit()
        view = review_view(review)
    await _after_merge(company_id, view, item)
    return view


async def reject(company_id: Any, review_id: Any, *, user: Any) -> Dict[str, Any]:
    """Close the pull request; the scratch item stays until its clean-up date."""
    from src.apps import events
    from src.apps.db import code_session

    if not can_approve(user):
        raise CodeProblem("rejecting code needs the code.approve permission (owners and admins)", 403)
    company_id = _uuid(company_id)
    async with code_session(company_id) as db:
        review = await db.get(CodeReview, _uuid(review_id))
        if review is None or review.company_id != company_id:
            raise CodeProblem("no such review", 404)
        if review.status != "open":
            raise CodeProblem(f"the pull request is {review.status}")
        repo = await db.get(GitRepo, review.repo_id)
    try:
        await provider_for(repo).close_review(repo.full_name, review.number)
    except GitError as error:
        raise CodeProblem(f"could not close the pull request: {error}", 502) from None
    async with code_session(company_id) as db:
        review = await db.get(CodeReview, review.id)
        review.status, review.updated_at = "closed", datetime.utcnow()
        item = await db.get(CodeItem, review.code_item_id) if review.code_item_id else None
        if item is not None:
            item.status, item.updated_at = "rejected", datetime.utcnow()
        await db.commit()
        view = review_view(review)
    await events.emit(company_id, "code.rejected", f"code_review:{review.id}",
                      {"review_id": view["id"], "code_item_id": view["code_item_id"]}, source="code_lanes")
    return view


async def review_closed_outside(company_id: Any, provider: str, full_name: str, number: int, *, merged: bool,
                                merge_sha: Optional[str] = None, merged_by: Optional[str] = None) -> Dict[str, Any]:
    """A pull request merged or closed in GitHub (webhook) or found so on approval."""
    from src.apps.db import code_session

    company_id = _uuid(company_id)
    async with code_session(company_id) as db:
        repo = (await db.execute(select(GitRepo).where(GitRepo.company_id == company_id, GitRepo.provider == provider,
                                                       func.lower(GitRepo.full_name) == full_name.lower()))
                ).scalar_one_or_none()
        review = (await db.execute(select(CodeReview).where(CodeReview.repo_id == repo.id,
                                                            CodeReview.number == number))
                  ).scalar_one_or_none() if repo is not None else None
        if review is None or review.status != "open":
            return review_view(review) if review is not None else {"review": None}
        item = None
        if merged:
            item = await _merged(db, company_id, review, merge_sha=merge_sha, login=merged_by)
        else:
            review.status, review.updated_at = "closed", datetime.utcnow()
            item_row = await db.get(CodeItem, review.code_item_id) if review.code_item_id else None
            if item_row is not None:
                item_row.status = "rejected"
        await db.commit()
        view = review_view(review)
    if merged:
        await _after_merge(company_id, view, item)
    if view.get("app_id") and not merged:
        from src.apps import service as apps

        await apps.expire_previews(company_id, view["app_id"], pr_number=number)
    return view


async def list_reviews(company_id: Any, *, status: Optional[str] = None, app_id: Any = None) -> List[Dict[str, Any]]:
    from src.apps.db import code_session

    query = select(CodeReview).where(CodeReview.company_id == _uuid(company_id))
    if status:
        query = query.where(CodeReview.status == status)
    if app_id:
        query = query.where(CodeReview.app_id == _uuid(app_id))
    async with code_session(company_id) as db:
        rows = (await db.execute(query.order_by(CodeReview.created_at.desc()).limit(200))).scalars().all()
    return [review_view(r) for r in rows]


async def get_review(company_id: Any, review_id: Any) -> Dict[str, Any]:
    from src.apps.db import code_session

    async with code_session(company_id) as db:
        review = await db.get(CodeReview, _uuid(review_id))
        if review is None or review.company_id != _uuid(company_id):
            raise CodeProblem("no such review", 404)
        return review_view(review)

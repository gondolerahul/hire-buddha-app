"""Where a business's code is kept (Phase 14 WS6 6.4, tech spec §11.3; decision D36).

One interface, :class:`GitProvider`, over three places:

* **GitHub** (primary) — the business's own organisation, through its GitHub
  App connection (``code_lanes/github.py``);
* **built-in Git**, chosen by ``GIT_BACKEND`` (default from ``PLATFORM_PROFILE``):
  ``gitea`` — the platform's Gitea (one organisation per tenant, ``t-<key>``,
  no public UI: browsed through HireBuddha) — or ``local_git`` — bare
  repositories on this machine (``LOCAL_GIT_DIR``), with pull requests kept
  beside each repository, for development and tests.

What promotion needs from any of them: create a repository, commit files on a
branch, open a pull request, post a check, read its state, merge it, and read
a commit as a tarball (the build context). "Connect GitHub later" pushes a
built-in repository's whole history to a new GitHub repository.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence

import httpx

__all__ = ["CHECK_CONCLUSIONS", "GitError", "GitProvider", "GiteaProvider", "LocalGitProvider", "RepoInfo",
           "ReviewInfo", "builtin_provider", "check_repo_name", "org_for", "set_builtin_provider"]

CHECK_CONCLUSIONS = ("success", "failure", "neutral", "skipped")
_REPO_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
AUTHOR = ("HireBuddha", "code@hirebuddha.com")


class GitError(RuntimeError):
    """A repository operation that failed (the message says which and why)."""


@dataclass
class RepoInfo:
    full_name: str
    default_branch: str = "main"
    external_id: Optional[str] = None
    url: Optional[str] = None


@dataclass
class ReviewInfo:
    number: int
    status: str = "open"                 # open | merged | closed
    url: Optional[str] = None
    head_sha: Optional[str] = None
    merge_sha: Optional[str] = None
    mergeable: Optional[bool] = None
    merged_by: Optional[str] = None
    checks: List[Dict[str, Any]] = field(default_factory=list)


def check_repo_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not _REPO_NAME.match(name) or name.endswith(".git"):
        raise GitError(f"{name!r} is not a repository name (letters, digits, '.', '_', '-')")
    return name


def check_branch(name: str) -> str:
    if not _BRANCH.match(name or "") or ".." in name or name.startswith("/") or name.endswith((".lock", "/")):
        raise GitError(f"{name!r} is not a branch name")
    return name


def check_path(path: str) -> str:
    parts = (path or "").replace("\\", "/").split("/")
    if not path or path.startswith("/") or any(p in ("", ".", "..", ".git") for p in parts):
        raise GitError(f"{path!r} is not a file path in a repository")
    return "/".join(parts)


async def org_for(company_id: Any) -> str:
    """The built-in organisation of a business: ``t-<tenant key>``, or ``c-<company hex>`` without one."""
    from src.common.tenancy.directory import directory

    location = await directory.find(company_id)
    return f"t-{location.key}" if location is not None else f"c-{uuid.UUID(str(company_id)).hex[:12]}"


class GitProvider(Protocol):
    name: str

    async def create_repo(self, owner: str, name: str, *, description: str = "",
                          default_branch: str = "main") -> RepoInfo: ...

    async def head(self, full_name: str, ref: str) -> Optional[str]:
        """The commit a branch (or tag, or sha) names, or ``None`` when there is none."""

    async def commit_files(self, full_name: str, *, branch: str, base: str, files: Dict[str, bytes],
                           message: str, delete: Sequence[str] = ()) -> str:
        """Commit ``files`` on ``branch`` (made from ``base`` when new); the new commit's sha."""

    async def read_file(self, full_name: str, ref: str, path: str) -> Optional[bytes]: ...

    async def open_review(self, full_name: str, *, branch: str, base: str, title: str, body: str) -> ReviewInfo: ...

    async def review(self, full_name: str, number: int) -> ReviewInfo: ...

    async def post_check(self, full_name: str, sha: str, *, name: str, conclusion: str, summary: str,
                         number: Optional[int] = None) -> None: ...

    async def merge(self, full_name: str, number: int, *, message: str, merged_by: Optional[str] = None) -> str:
        """Squash-merge the pull request; the merge commit's sha."""

    async def close_review(self, full_name: str, number: int) -> None: ...

    async def archive(self, full_name: str, ref: str) -> bytes:
        """The tree at ``ref`` as a gzipped tarball (paths may sit under one top directory)."""

    async def push_history(self, full_name: str, remote_url: str) -> None:
        """Push every branch and tag to ``remote_url`` (connect GitHub later)."""

    async def delete_owner(self, owner: str) -> int:
        """Delete every repository of ``owner`` and the owner itself (offboarding); the number deleted."""


# ── Local bare repositories ─────────────────────────────────────────────────

def _local_root() -> Path:
    from src.common.config import settings

    if settings.LOCAL_GIT_DIR:
        return Path(settings.LOCAL_GIT_DIR)
    return Path(__file__).resolve().parents[2] / ".local-git"   # backend/.local-git


class LocalGitProvider:
    """Bare repositories under one directory; pull requests in ``hb-reviews.json`` beside each."""

    name = "local_git"
    archive_prefixed = False   # git archive puts files at the top
    _locks: Dict[str, asyncio.Lock] = {}

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else _local_root()

    def _repo(self, full_name: str) -> Path:
        owner, _, name = full_name.partition("/")
        if not owner or not name or "/" in name or ".." in full_name:
            raise GitError(f"{full_name!r} is not owner/name")
        return self.root / owner / f"{name}.git"

    def _lock(self, full_name: str) -> asyncio.Lock:
        return self._locks.setdefault(full_name, asyncio.Lock())

    async def _git(self, *args: str, cwd: Optional[Path] = None, check: bool = True,
                   stdin: Optional[bytes] = None) -> bytes:
        env = {**os.environ, "GIT_AUTHOR_NAME": AUTHOR[0], "GIT_AUTHOR_EMAIL": AUTHOR[1],
               "GIT_COMMITTER_NAME": AUTHOR[0], "GIT_COMMITTER_EMAIL": AUTHOR[1], "GIT_TERMINAL_PROMPT": "0"}
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-c", "core.autocrlf=false", "-c", "init.defaultBranch=main", *args,
                cwd=str(cwd) if cwd else None, env=env, stdin=asyncio.subprocess.PIPE if stdin else None,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError:
            raise GitError("git is not installed on this machine") from None
        out, err = await proc.communicate(stdin)
        if check and proc.returncode != 0:
            raise GitError(f"git {args[0]}: {err.decode(errors='replace').strip()[:500]}")
        return out

    def _reviews_file(self, full_name: str) -> Path:
        return self._repo(full_name) / "hb-reviews.json"

    def _load(self, full_name: str) -> Dict[str, Any]:
        path = self._reviews_file(full_name)
        if not path.exists():
            return {"next": 1, "reviews": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, full_name: str, data: Dict[str, Any]) -> None:
        self._reviews_file(full_name).write_text(json.dumps(data, indent=1), encoding="utf-8")

    async def create_repo(self, owner: str, name: str, *, description: str = "",
                          default_branch: str = "main") -> RepoInfo:
        full_name = f"{owner}/{check_repo_name(name)}"
        path = self._repo(full_name)
        if path.exists():
            raise GitError(f"{full_name} already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._git("init", "--bare", "-b", check_branch(default_branch), str(path))
        if description:
            (path / "description").write_text(description + "\n", encoding="utf-8")
        return RepoInfo(full_name=full_name, default_branch=default_branch, external_id=full_name,
                        url=path.as_uri())

    async def head(self, full_name: str, ref: str) -> Optional[str]:
        path = self._repo(full_name)
        if not path.exists():
            raise GitError(f"no repository {full_name}")
        out = await self._git("--git-dir", str(path), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}",
                              check=False)
        sha = out.decode().strip()
        return sha or None

    async def commit_files(self, full_name: str, *, branch: str, base: str, files: Dict[str, bytes],
                           message: str, delete: Sequence[str] = ()) -> str:
        check_branch(branch)
        bare = self._repo(full_name)
        async with self._lock(full_name):
            work = Path(tempfile.mkdtemp(prefix="hb-git-"))
            try:
                await self._git("clone", "--quiet", str(bare), str(work))
                if await self.head(full_name, branch):
                    await self._git("checkout", "--quiet", branch, cwd=work)
                elif await self.head(full_name, base):
                    await self._git("checkout", "--quiet", "-b", branch, f"origin/{base}", cwd=work)
                else:  # an empty repository: the first commit makes the branch
                    await self._git("checkout", "--quiet", "--orphan", branch, cwd=work)
                for path, content in files.items():
                    target = work / check_path(path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content if isinstance(content, bytes) else str(content).encode())
                for path in delete:
                    target = work / check_path(path)
                    if target.exists():
                        target.unlink()
                await self._git("add", "-A", cwd=work)
                status = await self._git("status", "--porcelain", cwd=work)
                if not status.strip():
                    sha = await self.head(full_name, branch)
                    if sha:
                        return sha
                    raise GitError("nothing to commit")
                await self._git("commit", "--quiet", "-m", message, cwd=work)
                await self._git("push", "--quiet", "origin", f"HEAD:refs/heads/{branch}", cwd=work)
                return (await self._git("rev-parse", "HEAD", cwd=work)).decode().strip()
            finally:
                shutil.rmtree(work, ignore_errors=True)

    async def read_file(self, full_name: str, ref: str, path: str) -> Optional[bytes]:
        out = await self._git("--git-dir", str(self._repo(full_name)), "show", f"{ref}:{check_path(path)}",
                              check=False)
        return out or None

    async def open_review(self, full_name: str, *, branch: str, base: str, title: str, body: str) -> ReviewInfo:
        async with self._lock(full_name):
            data = self._load(full_name)
            for number, item in data["reviews"].items():
                if item["branch"] == branch and item["status"] == "open":
                    return await self.review(full_name, int(number))
            number = data["next"]
            data["next"] = number + 1
            data["reviews"][str(number)] = {"branch": branch, "base": base, "title": title, "body": body,
                                            "status": "open", "checks": {}, "merge_sha": None, "merged_by": None,
                                            "created_at": datetime.utcnow().isoformat()}
            self._save(full_name, data)
        return await self.review(full_name, number)

    async def review(self, full_name: str, number: int) -> ReviewInfo:
        item = self._load(full_name)["reviews"].get(str(number))
        if item is None:
            raise GitError(f"{full_name} has no pull request {number}")
        head = await self.head(full_name, item["branch"]) if item["status"] == "open" else item.get("head_sha")
        return ReviewInfo(number=number, status=item["status"], url=f"{self._repo(full_name).as_uri()}#pr-{number}",
                          head_sha=head, merge_sha=item.get("merge_sha"), mergeable=item["status"] == "open",
                          merged_by=item.get("merged_by"), checks=list(item.get("checks", {}).values()))

    async def post_check(self, full_name: str, sha: str, *, name: str, conclusion: str, summary: str,
                         number: Optional[int] = None) -> None:
        async with self._lock(full_name):
            data = self._load(full_name)
            for key, item in data["reviews"].items():
                if number is not None and key != str(number):
                    continue
                item.setdefault("checks", {})[name] = {"name": name, "conclusion": conclusion,
                                                       "summary": summary[:2000], "sha": sha}
            self._save(full_name, data)

    async def merge(self, full_name: str, number: int, *, message: str, merged_by: Optional[str] = None) -> str:
        bare = self._repo(full_name)
        async with self._lock(full_name):
            data = self._load(full_name)
            item = data["reviews"].get(str(number))
            if item is None or item["status"] != "open":
                raise GitError(f"pull request {number} is not open")
            work = Path(tempfile.mkdtemp(prefix="hb-git-"))
            try:
                await self._git("clone", "--quiet", str(bare), str(work))
                head = (await self._git("rev-parse", f"origin/{item['branch']}", cwd=work)).decode().strip()
                if await self.head(full_name, item["base"]):
                    await self._git("checkout", "--quiet", item["base"], cwd=work)
                    await self._git("merge", "--squash", f"origin/{item['branch']}", cwd=work)
                    await self._git("commit", "--quiet", "--allow-empty", "-m", message, cwd=work)
                else:  # the base does not exist yet: the branch becomes it
                    await self._git("checkout", "--quiet", "-b", item["base"], f"origin/{item['branch']}", cwd=work)
                await self._git("push", "--quiet", "origin", f"HEAD:refs/heads/{item['base']}", cwd=work)
                sha = (await self._git("rev-parse", "HEAD", cwd=work)).decode().strip()
            finally:
                shutil.rmtree(work, ignore_errors=True)
            item.update(status="merged", merge_sha=sha, merged_by=merged_by, head_sha=head,
                        merged_at=datetime.utcnow().isoformat())
            self._save(full_name, data)
        return sha

    async def close_review(self, full_name: str, number: int) -> None:
        async with self._lock(full_name):
            data = self._load(full_name)
            item = data["reviews"].get(str(number))
            if item is not None and item["status"] == "open":
                item["status"] = "closed"
                self._save(full_name, data)

    async def archive(self, full_name: str, ref: str) -> bytes:
        return await self._git("--git-dir", str(self._repo(full_name)), "archive", "--format=tar.gz", ref)

    async def push_history(self, full_name: str, remote_url: str) -> None:
        await self._git("--git-dir", str(self._repo(full_name)), "push", "--quiet", "--mirror", remote_url)

    async def delete_owner(self, owner: str) -> int:
        if not owner or "/" in owner or ".." in owner:
            raise GitError(f"{owner!r} is not an owner")
        folder = self.root / owner
        if not folder.exists():
            return 0
        count = len(list(folder.glob("*.git")))
        await asyncio.to_thread(shutil.rmtree, folder)
        return count


# ── Gitea (the built-in Git on Azure) ───────────────────────────────────────

_GITEA_STATE = {"success": "success", "failure": "failure", "neutral": "warning", "skipped": "success"}


class GiteaProvider:
    """The platform's Gitea through its API, as the platform's admin user."""

    name = "gitea"
    archive_prefixed = True    # <repo>/...

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None,
                 transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        from src.common.config import settings

        self.base_url = (base_url or settings.GITEA_URL or "").rstrip("/")
        self.token = token or settings.GITEA_ADMIN_TOKEN
        self._transport = transport
        if not self.base_url:
            raise GitError("GIT_BACKEND=gitea needs GITEA_URL (and GITEA_ADMIN_TOKEN)")

    async def _call(self, method: str, path: str, *, body: Any = None, ok: Sequence[int] = (200, 201, 204),
                    raw: bool = False, params: Optional[Dict[str, Any]] = None) -> Any:
        async with httpx.AsyncClient(base_url=f"{self.base_url}/api/v1", transport=self._transport, timeout=60,
                                     follow_redirects=True) as client:
            response = await client.request(method, path, json=body, params=params,
                                            headers={"Authorization": f"token {self.token}"})
        if response.status_code not in ok:
            raise GitError(f"gitea {method} {path}: {response.status_code} {response.text[:300]}")
        if raw:
            return response.content
        return response.json() if response.content else None

    async def _ensure_org(self, owner: str) -> None:
        async with httpx.AsyncClient(base_url=f"{self.base_url}/api/v1", transport=self._transport, timeout=30) as c:
            found = await c.get(f"/orgs/{owner}", headers={"Authorization": f"token {self.token}"})
        if found.status_code == 404:
            await self._call("POST", "/orgs", body={"username": owner, "visibility": "private",
                                                     "repo_admin_change_team_access": False})

    async def create_repo(self, owner: str, name: str, *, description: str = "",
                          default_branch: str = "main") -> RepoInfo:
        await self._ensure_org(owner)
        body = await self._call("POST", f"/orgs/{owner}/repos", body={
            "name": check_repo_name(name), "description": description, "private": True,
            "default_branch": default_branch, "auto_init": False})
        return RepoInfo(full_name=body["full_name"], default_branch=body.get("default_branch") or default_branch,
                        external_id=str(body["id"]), url=body.get("html_url"))

    async def head(self, full_name: str, ref: str) -> Optional[str]:
        async with httpx.AsyncClient(base_url=f"{self.base_url}/api/v1", transport=self._transport, timeout=30) as c:
            # Gitea has no GitHub-style /commits/{ref}: the newest commit of a branch, tag or sha is listed.
            response = await c.get(f"/repos/{full_name}/commits", headers={"Authorization": f"token {self.token}"},
                                   params={"sha": ref, "limit": 1, "stat": "false", "verification": "false",
                                           "files": "false"})
        if response.status_code in (404, 409, 422):   # no such ref; 409: an empty repository
            return None
        if response.status_code == 500 and "does not exist" in response.text:   # Gitea 1.22: a branch not made yet
            return None
        if response.status_code != 200:
            raise GitError(f"gitea commit {ref}: {response.status_code}")
        found = response.json()
        return (found[0] if isinstance(found, list) and found else {}).get("sha")

    async def commit_files(self, full_name: str, *, branch: str, base: str, files: Dict[str, bytes],
                           message: str, delete: Sequence[str] = ()) -> str:
        exists = await self.head(full_name, branch)
        source = branch if exists else base
        source_exists = bool(exists) or bool(await self.head(full_name, base))
        operations = []
        for path, content in files.items():
            current = await self._call("GET", f"/repos/{full_name}/contents/{check_path(path)}",
                                       params={"ref": source}, ok=(200, 404)) if source_exists else None
            entry = {"path": path, "content": base64.b64encode(content).decode()}
            if isinstance(current, dict) and current.get("sha"):
                entry.update(operation="update", sha=current["sha"])
            else:
                entry["operation"] = "create"
            operations.append(entry)
        for path in delete:
            current = await self._call("GET", f"/repos/{full_name}/contents/{check_path(path)}",
                                       params={"ref": source}, ok=(200, 404))
            if isinstance(current, dict) and current.get("sha"):
                operations.append({"path": path, "operation": "delete", "sha": current["sha"]})
        body: Dict[str, Any] = {"files": operations, "message": message,
                                "author": {"name": AUTHOR[0], "email": AUTHOR[1]}}
        if exists:
            body["branch"] = branch
        elif source_exists:
            body.update(branch=base, new_branch=branch)
        else:
            body["new_branch"] = branch
        result = await self._call("POST", f"/repos/{full_name}/contents", body=body)
        return ((result or {}).get("commit") or {}).get("sha") or await self.head(full_name, branch) or ""

    async def read_file(self, full_name: str, ref: str, path: str) -> Optional[bytes]:
        found = await self._call("GET", f"/repos/{full_name}/raw/{check_path(path)}", params={"ref": ref},
                                 ok=(200, 404), raw=True)
        return found or None

    def _review(self, body: Dict[str, Any]) -> ReviewInfo:
        status = "merged" if body.get("merged") else ("closed" if body.get("state") == "closed" else "open")
        return ReviewInfo(number=int(body["number"]), status=status, url=body.get("html_url"),
                          head_sha=(body.get("head") or {}).get("sha"), merge_sha=body.get("merge_commit_sha"),
                          mergeable=body.get("mergeable"),
                          merged_by=(body.get("merged_by") or {}).get("login"))

    async def open_review(self, full_name: str, *, branch: str, base: str, title: str, body: str) -> ReviewInfo:
        return self._review(await self._call("POST", f"/repos/{full_name}/pulls",
                                             body={"head": branch, "base": base, "title": title, "body": body}))

    async def review(self, full_name: str, number: int) -> ReviewInfo:
        return self._review(await self._call("GET", f"/repos/{full_name}/pulls/{number}"))

    async def post_check(self, full_name: str, sha: str, *, name: str, conclusion: str, summary: str,
                         number: Optional[int] = None) -> None:
        await self._call("POST", f"/repos/{full_name}/statuses/{sha}", body={
            "state": _GITEA_STATE.get(conclusion, "warning"), "context": f"hirebuddha/{name}",
            "description": summary[:140]})

    async def merge(self, full_name: str, number: int, *, message: str, merged_by: Optional[str] = None) -> str:
        await self._call("POST", f"/repos/{full_name}/pulls/{number}/merge",
                         body={"Do": "squash", "MergeTitleField": message.splitlines()[0][:200],
                               "MergeMessageField": f"Approved in HireBuddha by {merged_by or 'an approver'}"})
        merged = await self.review(full_name, number)
        return merged.merge_sha or ""

    async def close_review(self, full_name: str, number: int) -> None:
        await self._call("PATCH", f"/repos/{full_name}/pulls/{number}", body={"state": "closed"})

    async def archive(self, full_name: str, ref: str) -> bytes:
        return await self._call("GET", f"/repos/{full_name}/archive/{ref}.tar.gz", raw=True)

    async def push_history(self, full_name: str, remote_url: str) -> None:
        """A push mirror from Gitea to the remote, synced once now (Gitea pushes, not this process)."""
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(remote_url)
        clean = urlunsplit((parts.scheme, parts.hostname + (f":{parts.port}" if parts.port else ""), parts.path, "", ""))
        await self._call("POST", f"/repos/{full_name}/push_mirrors", body={
            "remote_address": clean, "remote_username": parts.username or "x-access-token",
            "remote_password": parts.password or "", "sync_on_commit": False, "interval": "0"})
        await self._call("POST", f"/repos/{full_name}/push_mirrors-sync")

    async def delete_owner(self, owner: str) -> int:
        async with httpx.AsyncClient(base_url=f"{self.base_url}/api/v1", transport=self._transport, timeout=30) as c:
            found = await c.get(f"/orgs/{owner}", headers={"Authorization": f"token {self.token}"})
        if found.status_code == 404:
            return 0
        deleted, page = 0, 1
        while True:
            repos = await self._call("GET", f"/orgs/{owner}/repos", params={"page": page, "limit": 50}) or []
            for repo in repos:
                await self._call("DELETE", f"/repos/{repo['full_name']}", ok=(204, 404))
                deleted += 1
            if len(repos) < 50:
                break
        await self._call("DELETE", f"/orgs/{owner}", ok=(204, 404))
        return deleted


# ── Selection ───────────────────────────────────────────────────────────────

_builtin: Optional[GitProvider] = None


def builtin_provider() -> GitProvider:
    global _builtin
    if _builtin is None:
        from src.common.platform import AdapterNotAvailable, adapter_name

        name = adapter_name("git")
        if name == "local_git":
            _builtin = LocalGitProvider()
        elif name == "gitea":
            _builtin = GiteaProvider()
        else:
            raise AdapterNotAvailable(f"GIT_BACKEND={name!r} has no adapter (local_git, gitea)")
    return _builtin


def set_builtin_provider(provider: Optional[GitProvider]) -> None:
    global _builtin
    _builtin = provider

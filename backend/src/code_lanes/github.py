"""GitHub flows on the business's GitHub App connection (Phase 14 WS6 6.5, tech spec §11.3).

Every agent change is a branch ``hb/<run-or-item>-<slug>`` and a pull request
in the business's own organisation; checks are posted with the Checks API;
a person merges — in GitHub, or by approving in HireBuddha, which merges
through the App (the approving person is recorded). Webhooks
(``github.pull_request.*``, ``github.check.*``, WS5) keep ``code_reviews`` in
step with what happened in GitHub (:func:`sync_from_webhook`).

Tokens are the connection's installation tokens, minted per use by
``connections.service.system_credential`` (purpose ``code_lanes``), so each
use is audited on the connection.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional, Sequence

from src.code_lanes.git import GitError, RepoInfo, ReviewInfo, check_branch, check_path, check_repo_name

logger = logging.getLogger(__name__)

API = "https://api.github.com"
_CONCLUSION = {"success": "success", "failure": "failure", "neutral": "neutral", "skipped": "skipped"}


class GitHubProvider:
    name = "github"
    archive_prefixed = True    # <owner>-<repo>-<sha>/...

    def __init__(self, company_id: Any, connection_id: Any) -> None:
        self.company_id = company_id
        self.connection_id = connection_id

    async def _token(self) -> str:
        from src.connections.service import system_credential

        token = await system_credential(self.company_id, self.connection_id, purpose="code_lanes")
        if not token.access_token:
            raise GitError("the GitHub connection gave no token")
        return token.access_token

    async def _call(self, method: str, path: str, *, body: Any = None, ok: Sequence[int] = (200, 201, 204),
                    raw: bool = False, params: Optional[Dict[str, Any]] = None) -> Any:
        from src.connections.providers.base import http

        token = await self._token()
        async with http() as client:
            response = await client.request(method, f"{API}{path}", json=body, params=params, headers={
                "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}, follow_redirects=True)
        if response.status_code not in ok:
            detail = response.text[:300]
            try:
                detail = response.json().get("message", detail)
            except ValueError:
                pass
            raise GitError(f"GitHub {method} {path}: {response.status_code} {detail}")
        if raw:
            return response.content
        return response.json() if response.content else None

    async def account(self) -> str:
        """The organisation (or user) the App is installed on."""
        from sqlalchemy import select

        from src.common.tenancy.session import tenant_session
        from src.connections.models import Connection

        async with tenant_session(self.company_id) as db:
            connection = (await db.execute(select(Connection).where(Connection.id == self.connection_id))).scalar_one()
        login = (connection.settings or {}).get("account_login") or connection.external_account_name
        if not login:
            raise GitError("the GitHub connection does not say which account it is installed on")
        return str(login)

    async def repositories(self) -> List[Dict[str, Any]]:
        """The repositories the installation can reach (for import)."""
        body = await self._call("GET", "/installation/repositories", params={"per_page": 100})
        return [{"full_name": r["full_name"], "id": str(r["id"]), "default_branch": r.get("default_branch") or "main",
                 "url": r.get("html_url"), "private": r.get("private")} for r in (body or {}).get("repositories", [])]

    async def create_repo(self, owner: str, name: str, *, description: str = "",
                          default_branch: str = "main") -> RepoInfo:
        body = await self._call("POST", f"/orgs/{owner}/repos", body={
            "name": check_repo_name(name), "description": description, "private": True, "auto_init": True},
            ok=(201,))
        return RepoInfo(full_name=body["full_name"], default_branch=body.get("default_branch") or default_branch,
                        external_id=str(body["id"]), url=body.get("html_url"))

    async def repo(self, full_name: str) -> RepoInfo:
        body = await self._call("GET", f"/repos/{full_name}")
        return RepoInfo(full_name=body["full_name"], default_branch=body.get("default_branch") or "main",
                        external_id=str(body["id"]), url=body.get("html_url"))

    async def head(self, full_name: str, ref: str) -> Optional[str]:
        found = await self._call("GET", f"/repos/{full_name}/commits/{ref}", ok=(200, 404, 409, 422))
        return (found or {}).get("sha") if isinstance(found, dict) else None

    async def commit_files(self, full_name: str, *, branch: str, base: str, files: Dict[str, bytes],
                           message: str, delete: Sequence[str] = ()) -> str:
        check_branch(branch)
        current = await self.head(full_name, branch)
        parent = current or await self.head(full_name, base)
        if parent is None:
            raise GitError(f"{full_name} has no branch {base}")
        commit = await self._call("GET", f"/repos/{full_name}/git/commits/{parent}")
        tree: List[Dict[str, Any]] = []
        for path, content in files.items():
            blob = await self._call("POST", f"/repos/{full_name}/git/blobs", body={
                "content": base64.b64encode(content).decode(), "encoding": "base64"}, ok=(201,))
            tree.append({"path": check_path(path), "mode": "100644", "type": "blob", "sha": blob["sha"]})
        for path in delete:
            tree.append({"path": check_path(path), "mode": "100644", "type": "blob", "sha": None})
        new_tree = await self._call("POST", f"/repos/{full_name}/git/trees",
                                    body={"base_tree": commit["tree"]["sha"], "tree": tree}, ok=(201,))
        new_commit = await self._call("POST", f"/repos/{full_name}/git/commits", body={
            "message": message, "tree": new_tree["sha"], "parents": [parent]}, ok=(201,))
        if current:
            await self._call("PATCH", f"/repos/{full_name}/git/refs/heads/{branch}",
                             body={"sha": new_commit["sha"], "force": False})
        else:
            await self._call("POST", f"/repos/{full_name}/git/refs",
                             body={"ref": f"refs/heads/{branch}", "sha": new_commit["sha"]}, ok=(201,))
        return new_commit["sha"]

    async def read_file(self, full_name: str, ref: str, path: str) -> Optional[bytes]:
        found = await self._call("GET", f"/repos/{full_name}/contents/{check_path(path)}", params={"ref": ref},
                                 ok=(200, 404))
        if not isinstance(found, dict) or "content" not in found:
            return None
        return base64.b64decode(found["content"])

    @staticmethod
    def _review(body: Dict[str, Any]) -> ReviewInfo:
        status = "merged" if body.get("merged") or body.get("merged_at") else (
            "closed" if body.get("state") == "closed" else "open")
        return ReviewInfo(number=int(body["number"]), status=status, url=body.get("html_url"),
                          head_sha=(body.get("head") or {}).get("sha"), merge_sha=body.get("merge_commit_sha"),
                          mergeable=body.get("mergeable"), merged_by=(body.get("merged_by") or {}).get("login"))

    async def open_review(self, full_name: str, *, branch: str, base: str, title: str, body: str) -> ReviewInfo:
        existing = await self._call("GET", f"/repos/{full_name}/pulls", params={
            "head": f"{full_name.split('/')[0]}:{branch}", "state": "open"})
        if existing:
            return self._review(existing[0])
        return self._review(await self._call("POST", f"/repos/{full_name}/pulls", body={
            "title": title, "head": branch, "base": base, "body": body}, ok=(201,)))

    async def review(self, full_name: str, number: int) -> ReviewInfo:
        return self._review(await self._call("GET", f"/repos/{full_name}/pulls/{number}"))

    async def post_check(self, full_name: str, sha: str, *, name: str, conclusion: str, summary: str,
                         number: Optional[int] = None) -> None:
        await self._call("POST", f"/repos/{full_name}/check-runs", body={
            "name": f"HireBuddha / {name}", "head_sha": sha, "status": "completed",
            "conclusion": _CONCLUSION.get(conclusion, "neutral"),
            "output": {"title": f"{name}: {conclusion}", "summary": summary[:60000] or conclusion}}, ok=(201,))

    async def merge(self, full_name: str, number: int, *, message: str, merged_by: Optional[str] = None) -> str:
        body = await self._call("PUT", f"/repos/{full_name}/pulls/{number}/merge", body={
            "merge_method": "squash", "commit_title": message.splitlines()[0][:200],
            "commit_message": f"Approved in HireBuddha by {merged_by or 'an approver'}"})
        if not (body or {}).get("merged"):
            raise GitError(f"GitHub did not merge pull request {number}: {(body or {}).get('message')}")
        return body["sha"]

    async def close_review(self, full_name: str, number: int) -> None:
        await self._call("PATCH", f"/repos/{full_name}/pulls/{number}", body={"state": "closed"})

    async def archive(self, full_name: str, ref: str) -> bytes:
        return await self._call("GET", f"/repos/{full_name}/tarball/{ref}", raw=True)

    async def push_history(self, full_name: str, remote_url: str) -> None:
        raise GitError("history is pushed to GitHub, not from it")

    async def push_url(self, full_name: str) -> str:
        """An HTTPS URL a built-in repository's history can be pushed to (one-hour token)."""
        return f"https://x-access-token:{await self._token()}@github.com/{full_name}.git"


async def sync_from_webhook(company_id: Any, event: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Keep a review (and its code item, and an app's preview) in step with GitHub:
    a pull request merged or closed there, or a check finished. Best-effort."""
    from src.code_lanes import service

    repo = (payload.get("repository") or {}).get("full_name")
    if not repo:
        return None
    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        number = pr.get("number")
        if payload.get("action") == "closed" and number:
            merged = bool(pr.get("merged"))
            return await service.review_closed_outside(
                company_id, "github", repo, int(number), merged=merged, merge_sha=pr.get("merge_commit_sha"),
                merged_by=(pr.get("merged_by") or {}).get("login"))
    return None

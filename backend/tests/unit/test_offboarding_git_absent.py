"""Removing a business's apps where the deployment has no Gitea (Azure prod before the tenant runtime).

The first deletes on prod failed at ``apps_removed``: the Gitea host does not exist there. With no
built-in repository on record there is nothing to delete; with one, an unreachable Gitea still fails.
"""
from __future__ import annotations

import uuid

import httpx
import pytest


class _NoGitea:
    async def delete_owner(self, owner):
        raise httpx.ConnectError("[Errno -2] Name or service not known")


@pytest.fixture
def ws(monkeypatch):
    from src.code_lanes import git
    from src.offboarding import workspace

    git.set_builtin_provider(_NoGitea())
    monkeypatch.setattr(workspace, "_delete_images", _none)
    yield workspace.Workspace(company_id=uuid.uuid4(), tenant_key="abc123")
    git.set_builtin_provider(None)


async def _none(ws):
    return "none built"


@pytest.mark.asyncio
async def test_no_gitea_and_no_repositories_is_skipped(ws, monkeypatch):
    from src.offboarding import workspace

    monkeypatch.setattr(workspace, "_has_repos", _false)
    detail = await workspace.apps_removed(ws)
    assert detail["repositories"] == 0 and detail["git"].startswith("skipped: built-in Git unreachable")


@pytest.mark.asyncio
async def test_no_gitea_with_a_repository_on_record_fails(ws, monkeypatch):
    from src.offboarding import workspace

    monkeypatch.setattr(workspace, "_has_repos", _true)
    with pytest.raises(httpx.ConnectError):
        await workspace.apps_removed(ws)


async def _false(ws):
    return False


async def _true(ws):
    return True

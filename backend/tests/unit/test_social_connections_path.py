"""API-15: social connections are under /api/v1, the old path an alias for one release.

``/api/social-connections`` was the one business route without the version
segment. Every route now answers at ``/api/v1/social-connections``; the old
path still answers, marked deprecated, logging each call and pointing at the
new one in ``Deprecation`` / ``Link`` headers, and is hidden from OpenAPI.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.ai import social_router
from src.auth.dependencies import get_current_user_and_company


def _paths(prefix: str) -> set[tuple[str, str]]:
    from src.main import app

    return {(method, r.path[len(prefix):])
            for r in app.routes
            if getattr(r, "path", "") == prefix or getattr(r, "path", "").startswith(prefix + "/")
            for method in (r.methods or [])}


def test_every_route_is_versioned_and_the_old_path_mirrors_it():
    new, old = _paths("/api/v1/social-connections"), _paths("/api/social-connections")
    assert new and new == old
    assert {("GET", ""), ("POST", ""), ("DELETE", "/{connection_id}"), ("POST", "/{connection_id}/refresh")} <= new


def test_only_the_versioned_path_is_documented():
    from src.main import app

    documented = [p for p in app.openapi()["paths"] if "social-connections" in p]
    assert documented and all(p.startswith("/api/v1/social-connections") for p in documented)


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *_a, **_k):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))


@pytest.mark.asyncio
@pytest.mark.parametrize("path, deprecated", [("/api/v1/social-connections", False),
                                              ("/api/social-connections", True)])
async def test_both_paths_answer_and_the_old_one_says_it_is_deprecated(monkeypatch, caplog, path, deprecated):
    monkeypatch.setattr(social_router, "AsyncSessionLocal", _Session)
    app = FastAPI()
    app.include_router(social_router.router)
    app.dependency_overrides[get_current_user_and_company] = lambda: (
        SimpleNamespace(id=None), SimpleNamespace(id="c1"))
    with caplog.at_level(logging.WARNING, logger="src.ai.social_router"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.get(path)
    assert resp.status_code == 200, resp.text
    assert (resp.headers.get("Deprecation") == "true") is deprecated
    if deprecated:
        assert resp.headers["Link"] == '</api/v1/social-connections>; rel="successor-version"'
        assert "Deprecated path GET /api/social-connections" in caplog.text

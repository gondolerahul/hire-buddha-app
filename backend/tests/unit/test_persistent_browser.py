"""Persistent browser profile (S5) — real Chromium, no network.

Gated on the Playwright Chromium binary being installed (skips otherwise, like
the rest of the browser e2e surface). Verifies:
  * resolve_persistent_browser_dir flag layering (pure, always runs),
  * a cookie written in one persistent session is visible in the next session
    sharing the same user_data_dir, and an ephemeral session does NOT persist it.
"""
from __future__ import annotations

import os

import pytest

from src.ai.tools.sandbox import runtime as runtime_mod
from src.ai.tools.sandbox.runtime import (
    SubprocessRuntime,
    resolve_persistent_browser_dir,
)


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return os.path.exists(p.chromium.executable_path)
    except Exception:
        return False


# --------------------------------------------------------------------------
# flag resolution (pure)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_dir_none_without_company() -> None:
    assert await resolve_persistent_browser_dir({"persona": "x"}) is None


@pytest.mark.asyncio
async def test_resolve_dir_explicit_context(monkeypatch) -> None:
    d = await resolve_persistent_browser_dir(
        {"company_id": "c1", "persona": "sales", "persistent_browser": True}
    )
    assert d is not None and d.endswith(os.path.join("c1", ".browser", "sales"))


@pytest.mark.asyncio
async def test_resolve_dir_off_by_default(monkeypatch) -> None:
    from src.common import config

    monkeypatch.setattr(config.settings, "SANDBOX_PERSISTENT_BROWSER_ENABLED", False)

    async def _none(_k, _c):
        return None

    monkeypatch.setattr(runtime_mod, "_resolve_company_flag", _none)
    assert await resolve_persistent_browser_dir({"company_id": "c1"}) is None


@pytest.mark.asyncio
async def test_resolve_dir_settings_master_on(monkeypatch) -> None:
    from src.common import config

    monkeypatch.setattr(config.settings, "SANDBOX_PERSISTENT_BROWSER_ENABLED", True)

    async def _none(_k, _c):
        return None

    monkeypatch.setattr(runtime_mod, "_resolve_company_flag", _none)
    d = await resolve_persistent_browser_dir({"company_id": "c1"})
    assert d is not None and d.endswith(os.path.join("c1", ".browser", "default"))


# --------------------------------------------------------------------------
# real persistence (Chromium)
# --------------------------------------------------------------------------

@pytest.mark.skipif(not _chromium_available(), reason="Playwright Chromium not installed")
@pytest.mark.asyncio
async def test_cookie_persists_across_sessions(tmp_path) -> None:
    rt = SubprocessRuntime()
    profile = str(tmp_path / "profile")
    future = 4102444800  # 2100-01-01

    async with rt.open_browser_session(user_data_dir=profile) as s:
        await s.page.context.add_cookies([
            {"name": "sid", "value": "abc123", "url": "https://example.test",
             "expires": future},
        ])

    async with rt.open_browser_session(user_data_dir=profile) as s:
        cookies = await s.page.context.cookies("https://example.test")
    assert any(c["name"] == "sid" and c["value"] == "abc123" for c in cookies)


@pytest.mark.skipif(not _chromium_available(), reason="Playwright Chromium not installed")
@pytest.mark.asyncio
async def test_ephemeral_session_does_not_persist(tmp_path) -> None:
    rt = SubprocessRuntime()
    # Ephemeral (no user_data_dir): cookie set, new ephemeral session is clean.
    async with rt.open_browser_session() as s:
        await s.page.context.add_cookies([
            {"name": "sid", "value": "abc123", "url": "https://example.test",
             "expires": 4102444800},
        ])
    async with rt.open_browser_session() as s:
        cookies = await s.page.context.cookies("https://example.test")
    assert not any(c["name"] == "sid" for c in cookies)

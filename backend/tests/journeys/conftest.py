"""Browser journeys per role (Phase 15 T10-2; 07 §10, 08 §5 "E2E (Playwright)").

They drive the real frontend in Chromium (Playwright for Python, a backend
dependency; ``playwright install chromium`` once per machine) against a running
stack — the Vite dev server and the API it calls — and its database:

    JOURNEY_BASE_URL   the frontend, e.g. http://localhost:3000

Without it every journey is skipped; ``REQUIRE_JOURNEYS=1`` makes that a
failure (the release lane). Each journey builds its own people and companies
(``world.build``), all named with a fresh tag, and deletes them afterwards.
What a journey cannot do here is said where it stops: a Razorpay checkout is
credited as the gateway's confirmation would credit it, and nothing calls a
model provider.
"""
from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterator

import httpx
import pytest

BASE_URL = os.environ.get("JOURNEY_BASE_URL", "").rstrip("/")
REQUIRED = os.environ.get("REQUIRE_JOURNEYS") == "1"


def _unavailable() -> str:
    if not BASE_URL:
        return "JOURNEY_BASE_URL is not set (the frontend of a running stack)"
    try:
        httpx.get(BASE_URL, timeout=5)
    except httpx.HTTPError as error:
        return f"{BASE_URL} does not answer: {error}"
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return "Playwright is not installed"
    return ""


@pytest.fixture(scope="session", autouse=True)
def _stack() -> None:
    reason = _unavailable()
    if reason:
        if REQUIRED:
            pytest.fail(reason)
        pytest.skip(reason)


_DB = ThreadPoolExecutor(max_workers=1)


def db_call(fn: Callable[..., Any], *args: Any) -> Any:
    """Run a ``world`` helper (it uses ``asyncio.run``) off the Playwright thread."""
    return _DB.submit(fn, *args).result()


@pytest.fixture(scope="session")
def browser() -> Iterator[Any]:
    from playwright.sync_api import expect, sync_playwright

    expect.set_options(timeout=20_000)        # a dev server's first page and the sign-in take a while
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture
def world() -> Iterator[Any]:
    from tests.journeys import world as w

    built = db_call(w.build, uuid.uuid4().hex[:8])
    built.extra_companies = []
    yield built
    db_call(w.teardown, built, built.extra_companies)


@pytest.fixture
def signed_in(browser: Any) -> Iterator[Callable[[str], Any]]:
    """``signed_in(email)`` → a page signed in as that person (a token, as the sign-in form would store)."""
    from tests.journeys import world as w

    contexts = []

    def open_as(address: str) -> Any:
        token = db_call(w.token, address)
        context = browser.new_context(viewport={"width": 1400, "height": 900}, base_url=BASE_URL)
        context.add_init_script(f"window.localStorage.setItem('access_token', {token!r})")
        contexts.append(context)
        return context.new_page()

    yield open_as
    for context in contexts:
        context.close()


@pytest.fixture
def anonymous(browser: Any) -> Iterator[Any]:
    context = browser.new_context(viewport={"width": 1400, "height": 900}, base_url=BASE_URL)
    yield context.new_page()
    context.close()


def go(page: Any, path: str) -> Any:
    """Open ``path``. Its data arrives later: assert with ``expect``, which waits for it
    (``networkidle`` is no signal — some pages keep a request open)."""
    page.goto(path)
    return page


def main_text(page: Any) -> str:
    return page.locator("main").inner_text()


def path_of(page: Any) -> str:
    return page.url[len(BASE_URL):].split("?")[0]

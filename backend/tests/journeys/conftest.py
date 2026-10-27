"""Browser journeys per role (Phase 15 T10-2; 07 §10, 08 §5 "E2E (Playwright)").

They drive the real frontend in Chromium (Playwright for Python, a backend
dependency; ``playwright install chromium`` once per machine) against a running
stack — the Vite dev server and the API it calls — and its database:

    JOURNEY_BASE_URL   the frontend, e.g. http://localhost:3000
    JOURNEY_KUBE       optional: [<kube context>:]<namespace>/<pod or deploy/name>
                       — run the data setup in that pod (an Azure environment,
                       whose database and signing key only its pods reach), e.g.
                       aks-hb-prod:hb-platform/deploy/hb-api
    JOURNEY_TAG        optional: the world's tag (default: a fresh one)

Without the first, every journey is skipped; ``REQUIRE_JOURNEYS=1`` makes that a
failure (the release lane). The journeys build their people and companies as
test businesses (``world.build``) and delete them afterwards with the product's
immediate delete — one world per journey locally, one per run on an Azure
environment (its workspaces take minutes to make and remove). Immediate delete
must be on where they run (``offboarding.immediate_delete_enabled``); locally
the run turns it on and back off.
What a journey cannot do here is said where it stops: a Razorpay checkout is
credited as the gateway's confirmation would credit it, and nothing calls a
model provider.
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import tarfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx
import pytest

BASE_URL = os.environ.get("JOURNEY_BASE_URL", "").rstrip("/")
REQUIRED = os.environ.get("REQUIRE_JOURNEYS") == "1"
KUBE = os.environ.get("JOURNEY_KUBE", "")
TAG = os.environ.get("JOURNEY_TAG", "")
TESTS = Path(__file__).resolve().parents[1]
# What the pod needs of the tests tree (its image has no pytest): copied to /tmp/hbj first.
REMOTE_FILES = ("__init__.py", "journeys/__init__.py", "journeys/world.py", "journeys/remote.py",
                "harness/wallet.py", "harness/purge.py")


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


def _kubectl(*args: str, stdin: bytes = b"", timeout: int = 1800) -> str:
    context, _, place = KUBE.rpartition(":")
    namespace, target = place.split("/", 1)
    where = ["--context", context] if context else []
    done = subprocess.run(["kubectl", *where, "-n", namespace, "exec", "-i", target, "--", *args], input=stdin,
                          capture_output=True, timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(f"kubectl exec failed ({done.returncode}): {done.stderr.decode(errors='replace')[-2000:]}")
    return done.stdout.decode(errors="replace")


@pytest.fixture(scope="session", autouse=True)
def _remote_code(_stack: None) -> None:
    """With ``JOURNEY_KUBE``: this checkout's world helpers on the pod, under /tmp/hbj."""
    if not KUBE:
        return
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name in REMOTE_FILES:
            tar.add(TESTS / name, arcname=f"tests/{name}")
        empty = tarfile.TarInfo("tests/harness/__init__.py")
        tar.addfile(empty, io.BytesIO(b""))
    _kubectl("python", "-c", "import sys, tarfile; tarfile.open(fileobj=sys.stdin.buffer, mode='r|')"
             ".extractall('/tmp/hbj')", stdin=buffer.getvalue())


def _remote(fn: Callable[..., Any], *args: Any) -> Any:
    from tests.journeys import remote

    payload = base64.b64encode(json.dumps(remote.encode(list(args))).encode()).decode()
    # By path, not ``-m``: ``-m`` puts the working directory (/app, the image's own tests/) first.
    out = _kubectl("env", "PYTHONPATH=/tmp/hbj:/app", "python", "/tmp/hbj/tests/journeys/remote.py", fn.__name__,
                   payload)
    lines = [line for line in out.splitlines() if line.startswith(remote.MARK)]
    if not lines:
        raise RuntimeError(f"{fn.__name__} on {KUBE} printed no result: {out[-2000:]}")
    result = remote.decode(json.loads(lines[-1][len(remote.MARK):]))
    if fn.__name__ == "partner_state":
        result["customers"] = {uuid.UUID(k): v for k, v in result["customers"].items()}
    if fn.__name__ == "company_of" and result:
        result["id"] = uuid.UUID(result["id"])
    return result


def db_call(fn: Callable[..., Any], *args: Any) -> Any:
    """Run a ``world`` helper off the Playwright thread (it uses ``asyncio.run``): here, or in
    the ``JOURNEY_KUBE`` pod."""
    if KUBE:
        return _remote(fn, *args)
    return _DB.submit(fn, *args).result()


@pytest.fixture(scope="session")
def browser() -> Iterator[Any]:
    from playwright.sync_api import expect, sync_playwright

    expect.set_options(timeout=30_000)        # a dev server's first page and the sign-in (a reload) take a while
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        yield chromium
        chromium.close()


def _world_scope(fixture_name: str, config: Any) -> str:
    return "session" if KUBE else "function"


@pytest.fixture(scope="session")
def _switch() -> Iterator[None]:
    """Locally: immediate delete on for the run (teardown uses it), back off afterwards."""
    from tests.journeys import world as w

    if KUBE:
        yield
        return
    db_call(w.set_immediate_delete, True)
    yield
    db_call(w.set_immediate_delete, False)


@pytest.fixture(scope=_world_scope)
def world(_switch: None) -> Iterator[Any]:
    from tests.journeys import world as w

    built = db_call(w.build, TAG or f"j{uuid.uuid4().hex[:7]}")
    yield built
    states = db_call(w.teardown, built, built.extra_companies)
    assert set(states.values()) <= {"erased"}, f"journey businesses not deleted: {states}"


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

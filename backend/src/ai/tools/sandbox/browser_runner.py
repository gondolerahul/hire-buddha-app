"""The browser runner: one ``headless_browser`` session, wherever it runs (TL-18).

``headless_browser`` used to drive a Playwright page in the backend process,
so with the container runtime on, Chromium — and the ``evaluate`` step, which
runs arbitrary JavaScript by design — still ran on the host as the backend's
OS user. Now the session's steps are a JSON request and this module runs them:

* in the tenant's ``web`` container, as a script (``python3 browser_runner.py
  request.json``). The platform writes it under the read-only ``.skills/``
  root, so tenant code can read it but not change it. Its only way out is the
  egress proxy that refuses private addresses (``HTTPS_PROXY``); screenshots
  go to ``$ARTIFACTS_DIR``; the result is one JSON line on stdout;
* on the host runtime, in-process (:func:`run_session`), with the host's
  SSRF guard passed in as hooks.

It imports nothing from the platform — only the standard library and
Playwright — because inside the container the platform is not there.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlsplit

MARKER = "___BROWSER___"
MAX_OUTPUT_CHARS = 16384
VALID_WAIT_UNTIL = {"load", "domcontentloaded", "networkidle", "commit"}
DEFAULT_VIEWPORT = {"width": 1280, "height": 720}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
    "HireBuddha-AI-Agent/1.0"
)
PROFILE_ENV = "BROWSER_PROFILE_DIR"
# Set by the container's web proxy on a refusal (docker/egress-proxy/web_proxy.py).
REFUSED_HEADER = "x-hb-egress-refused"

CheckUrl = Callable[[str], Awaitable[None]]
Guard = Callable[[Any], Awaitable[List[str]]]


@contextlib.asynccontextmanager
async def open_page(
    *,
    timeout_ms: int = 30000,
    user_data_dir: Optional[str] = None,
    proxy: Optional[str] = None,
) -> AsyncIterator[Any]:
    """A page in a fresh Chromium; with ``user_data_dir`` a persistent profile
    (cookies and logins survive, S5). Everything is closed on exit."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = None
    options: Dict[str, Any] = {"viewport": dict(DEFAULT_VIEWPORT), "user_agent": DEFAULT_USER_AGENT}
    launch: Dict[str, Any] = {"headless": True}
    if proxy:
        launch["proxy"] = {"server": proxy}
    try:
        if user_data_dir:
            os.makedirs(user_data_dir, exist_ok=True)
            ctx = await pw.chromium.launch_persistent_context(user_data_dir, **launch, **options)
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        else:
            browser = await pw.chromium.launch(**launch)
            ctx = await browser.new_context(**options)
            page = await ctx.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            yield page
        finally:
            with contextlib.suppress(Exception):
                await ctx.close()
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        with contextlib.suppress(Exception):
            await pw.stop()


def _cut(text: str) -> str:
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + f"\n... [truncated, {len(text)} total chars]"
    return text


class _Refused(Exception):
    """A URL the session may not open."""


async def _open(page: Any, step: Dict[str, Any], timeout_ms: int, check_url: Optional[CheckUrl]) -> None:
    """Every navigation a step asks for goes through here: only ``http(s)``,
    and the host's guard when there is one (in the container, the proxy)."""
    url = (step.get("url") or "").strip()
    if not url:
        return
    if urlsplit(url).scheme.lower() not in ("http", "https"):
        raise _Refused(f"only http and https URLs may be opened, not {url!r}")
    if check_url is not None:
        try:
            await check_url(url)
        except Exception as exc:  # noqa: BLE001 - the guard's refusal, whatever its type
            raise _Refused(str(exc)) from exc
    wait_until = step.get("wait_for") or "load"
    response = await page.goto(url, wait_until=wait_until if wait_until in VALID_WAIT_UNTIL else "load",
                               timeout=timeout_ms)
    refused = (getattr(response, "headers", None) or {}).get(REFUSED_HEADER)
    if refused:
        raise _Refused(refused)


async def _navigate(page: Any, step: Dict[str, Any], timeout_ms: int, _out: Optional[str]) -> Dict[str, Any]:
    return {"url": page.url, "title": await page.title(), "content": _cut(await page.inner_text("body"))}


async def _click(page: Any, step: Dict[str, Any], timeout_ms: int, _out: Optional[str]) -> Dict[str, Any]:
    await page.click(step["selector"], timeout=timeout_ms)
    await page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 10000))
    return {"url": page.url, "title": await page.title(), "selector": step["selector"],
            "message": f"Clicked element matching '{step['selector']}'"}


async def _type(page: Any, step: Dict[str, Any], timeout_ms: int, _out: Optional[str]) -> Dict[str, Any]:
    await page.fill(step["selector"], str(step.get("text") or ""), timeout=timeout_ms)
    return {"url": page.url, "title": await page.title(), "selector": step["selector"],
            "message": f"Typed into element matching '{step['selector']}'"}


async def _screenshot(page: Any, step: Dict[str, Any], timeout_ms: int, out_dir: Optional[str]) -> Dict[str, Any]:
    if not out_dir:
        raise RuntimeError("this call has no place to keep a screenshot")
    selector = (step.get("selector") or "").strip()
    if selector:
        element = await page.query_selector(selector)
        if element is None:
            raise LookupError(f"Element '{selector}' not found.")
        image = await element.screenshot(timeout=timeout_ms)
    else:
        image = await page.screenshot(full_page=True, timeout=timeout_ms)
    name = f"screenshot_{uuid.uuid4().hex[:8]}.png"
    with open(os.path.join(out_dir, name), "wb") as fh:
        fh.write(image)
    return {"url": page.url, "title": await page.title(), "file": name}


async def _get_text(page: Any, step: Dict[str, Any], timeout_ms: int, _out: Optional[str]) -> Dict[str, Any]:
    selector = (step.get("selector") or "").strip()
    if selector:
        element = await page.query_selector(selector)
        if element is None:
            raise LookupError(f"Element '{selector}' not found.")
        text = await element.inner_text()
    else:
        text = await page.inner_text("body")
    return {"url": page.url, "title": await page.title(), "content": _cut(text)}


async def _evaluate(page: Any, step: Dict[str, Any], timeout_ms: int, _out: Optional[str]) -> Dict[str, Any]:
    result = await page.evaluate(step["javascript"])
    return {"url": page.url, "title": await page.title(), "result": _cut(str(result))}


ACTIONS = {"navigate": _navigate, "click": _click, "type": _type, "screenshot": _screenshot,
           "get_text": _get_text, "evaluate": _evaluate}
_REQUIRED = {"navigate": "url", "click": "selector", "type": "selector", "evaluate": "javascript"}


async def run_step(page: Any, step: Dict[str, Any], timeout_ms: int, out_dir: Optional[str],
                   check_url: Optional[CheckUrl] = None) -> Dict[str, Any]:
    """One step on the page: its result, or ``status: error`` with the reason.
    A step's ``url`` is opened first (for ``navigate`` it is the step)."""
    action = step.get("action")
    if action not in ACTIONS:
        return {"status": "error", "action": action, "error": f"unknown action {action!r}"}
    needed = _REQUIRED.get(action)
    if needed and not (step.get(needed) or "").strip():
        return {"status": "error", "action": action, "error": f"'{needed}' is required for {action}."}
    try:
        await _open(page, step, timeout_ms, check_url)
        outcome = await ACTIONS[action](page, step, timeout_ms, out_dir)
    except _Refused as exc:
        return {"status": "error", "action": action, "error": f"URL refused: {exc}"}
    except Exception as exc:  # noqa: BLE001 - a failed step is reported, not raised
        return {"status": "error", "action": action, "error": f"{type(exc).__name__}: {exc}"}
    return {"status": "success", "action": action, **outcome}


async def run_session(
    request: Dict[str, Any],
    *,
    check_url: Optional[CheckUrl] = None,
    guard: Optional[Guard] = None,
) -> Dict[str, Any]:
    """Run ``request["steps"]`` in order on one page, stopping at the first
    that fails. ``request``: ``steps``, ``timeout_ms``, and optionally
    ``user_data_dir``, ``out_dir`` (screenshots) and ``proxy``."""
    timeout_ms = int(request.get("timeout_ms") or 30000)
    done: List[Dict[str, Any]] = []
    refused: List[str] = []
    async with open_page(timeout_ms=timeout_ms, user_data_dir=request.get("user_data_dir"),
                         proxy=request.get("proxy")) as page:
        if guard is not None:
            refused = await guard(page)
        for step in request.get("steps") or []:
            outcome = await run_step(page, step, timeout_ms, request.get("out_dir"), check_url)
            done.append(outcome)
            if outcome["status"] == "error":
                break
    return {"steps": done, "blocked_requests": refused}


def main(argv: List[str]) -> int:
    """The container entry point: the request file is ``argv[1]``; where to
    keep screenshots, the profile and the proxy come from the environment the
    platform sets on the exec."""
    with open(argv[1], encoding="utf-8") as fh:
        request = json.load(fh)
    request["out_dir"] = os.environ.get("ARTIFACTS_DIR") or None
    request["user_data_dir"] = os.environ.get(PROFILE_ENV) or None
    request["proxy"] = os.environ.get("HTTPS_PROXY") or None
    result = asyncio.run(run_session(request))
    sys.stdout.write(MARKER + json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

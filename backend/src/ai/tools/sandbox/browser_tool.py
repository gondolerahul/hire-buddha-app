"""
HeadlessBrowserTool — Headless browser interaction for AI agents.

Uses Playwright (Chromium) to provide full browser capabilities including
JavaScript rendering, clicking, typing, screenshots, and text extraction.

Safety features:
  - Hard timeout per action (default 30s, max 120s)
  - Output capped at 16384 characters for text responses
  - Browser context is ephemeral (no persistent cookies/state)
  - URL validation (blocks file://, javascript:, data: protocols)

Input schema (JSON string):
    {
        "action":     "navigate|click|type|screenshot|get_text|evaluate",
        "url":        "https://example.com",    # required for navigate
        "selector":   "#login-button",           # required for click/type/get_text on element
        "text":       "hello",                   # required for type
        "javascript": "document.title",          # required for evaluate
        "timeout_ms": 30000,                     # optional, max 120000
        "wait_for":   "networkidle"              # optional: load|domcontentloaded|networkidle
    }

Output (JSON string):
    {
        "status":  "success",
        "action":  "navigate",
        "url":     "https://example.com",
        "title":   "Example Domain",
        "content": "... page text ...",
        "screenshot_path": "/path/to/screenshot.png"  # only for screenshot action
    }
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional
from pathlib import Path

from pydantic import Field, model_validator

from src.ai.tools.base import Tool, ToolOutput, ToolParams

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------
_MAX_OUTPUT_CHARS = 16384
_DEFAULT_TIMEOUT_MS = 30000
_MAX_TIMEOUT_MS = 120000
_SCREENSHOT_DIR = Path("/tmp/browser_screenshots")


_VALID_WAIT_UNTIL = {"load", "domcontentloaded", "networkidle", "commit"}


async def guard_requests(page: Any) -> list[str]:
    """Check every request the page makes against the SSRF guard (TL-08).

    Navigation, redirects, frames, subresources and script-driven requests all
    pass through Playwright's router, so ``evaluate`` cannot reach an internal
    host either. Returns the list the refused URLs are appended to.
    """
    from src.common.net_guard import BlockedURL, check_url

    refused: list[str] = []
    verdicts: dict[str, bool] = {}  # per host, for the life of the session

    async def _route(route: Any) -> None:
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:")):  # in-page, no network
            await route.continue_()
            return
        from urllib.parse import urlsplit
        key = urlsplit(url).netloc.lower()
        if key not in verdicts:
            try:
                await check_url(url)
                verdicts[key] = True
            except BlockedURL:
                verdicts[key] = False
        if verdicts[key]:
            await route.continue_()
        else:
            refused.append(url)
            await route.abort("blockedbyclient")

    await page.route("**/*", _route)
    return refused


class BrowserStep(ToolParams):
    """One action on the session's page."""
    action: Literal["navigate", "click", "type", "screenshot", "get_text", "evaluate"] = Field(
        ..., description="navigate (go to url), click / type (selector), screenshot, get_text, evaluate (javascript)")
    url: Optional[str] = Field(None, description="For navigate; for other actions, opened first if given")
    selector: Optional[str] = Field(None, description="CSS selector: required for click and type; "
                                                      "optional for screenshot and get_text")
    text: Optional[str] = Field(None, description="Text to type (type)")
    javascript: Optional[str] = Field(None, description="Script to run (evaluate)")
    wait_for: Optional[Literal["load", "domcontentloaded", "networkidle", "commit"]] = Field(
        None, description="Wait condition after navigating (default load)")


class HeadlessBrowserParams(ToolParams):
    url: Optional[str] = Field(None, description="A page to open before the steps")
    steps: List[BrowserStep] = Field(..., min_length=1, max_length=10, description=(
        "The actions, run in order on one page in one session: e.g. navigate, type the user name, "
        "click submit, get_text. Nothing is kept between calls."))
    timeout_ms: int = Field(_DEFAULT_TIMEOUT_MS, ge=1000, le=_MAX_TIMEOUT_MS,
                            description="Timeout per action in milliseconds (default 30000, at most 120000)")

    @model_validator(mode="before")
    @classmethod
    def _one_action_is_one_step(cls, data: Any) -> Any:
        # The single-action form the tool took before TL-62 (and old plans use).
        if isinstance(data, dict) and "action" in data and "steps" not in data:
            step_keys = set(BrowserStep.model_fields)
            step = {k: v for k, v in data.items() if k in step_keys}
            rest = {k: v for k, v in data.items() if k not in step_keys}
            return {**rest, "steps": [step]}
        return data


class HeadlessBrowserTool(Tool):
    """
    Interact with web pages using a headless Chromium browser.

    Supports navigation, clicking, typing, screenshots, text extraction,
    and JavaScript evaluation. Each invocation creates an isolated browser
    context that is automatically destroyed after execution.
    """

    name = "headless_browser"
    category = "browser"
    description = (
        "Interact with web pages using a headless browser (Chromium). Each call is one "
        "browser session: give the actions as 'steps', run in order on one page "
        "(navigate, click, type, screenshot, get_text, evaluate), so a login and a read "
        "happen in one call. Nothing is kept between calls. Returns JSON with each step's result."
    )
    Params = HeadlessBrowserParams

    async def execute(self, params: "HeadlessBrowserParams", ctx: Dict[str, Any]) -> ToolOutput:
        try:
            result = await self._run_session(params, ctx)
        except ImportError:
            return ToolOutput.failed("Playwright is not installed. Run: pip install playwright && "
                                     "playwright install chromium", code="not_installed")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"HeadlessBrowserTool unexpected error: {exc}", exc_info=True)
            return ToolOutput.failed(f"Browser session failed: {exc}")
        if result.get("status") == "error":
            return ToolOutput(success=False, output=json.dumps(result), error=result.get("error"),
                              error_code="browser_step_failed")
        return ToolOutput(output=json.dumps(result))

    async def _run_session(self, params: "HeadlessBrowserParams", context: Dict[str, Any]) -> Dict[str, Any]:
        """One browser session: the steps in order on one page (TL-62).

        The runtime owns the browser's lifecycle; nothing outlives the call.
        Stops at the first step that fails.
        """
        import time as _time

        from src.ai.tools.sandbox.runtime import (
            resolve_persistent_browser_dir,
            resolve_sandbox_runtime,
        )

        runtime = await resolve_sandbox_runtime(context)
        user_data_dir = await resolve_persistent_browser_dir(context)
        timeout_ms = params.timeout_ms
        steps = [step.model_dump(exclude_none=True) for step in params.steps]
        if params.url:
            steps.insert(0, {"action": "navigate", "url": params.url})
        done: list[Dict[str, Any]] = []
        refused: list[str] = []
        _session_start = _time.monotonic()
        try:
            async with runtime.open_browser_session(
                timeout_ms=timeout_ms, user_data_dir=user_data_dir
            ) as session:
                page = session.page
                refused = await guard_requests(page)
                for step in steps:
                    outcome = await self._step(page, step, timeout_ms, context)
                    done.append(outcome)
                    if outcome.get("status") == "error":
                        break
        finally:
            try:
                from src.ai.tools.sandbox.metering import meter_sandbox_usage
                await meter_sandbox_usage(
                    context,
                    duration_ms=int((_time.monotonic() - _session_start) * 1000),
                    runtime_name=type(runtime).__name__,
                    kind="browser",
                )
            except Exception:  # noqa: BLE001 - metering must never break a tool
                pass
        failed = next((d for d in done if d.get("status") == "error"), None)
        result: Dict[str, Any] = {
            "status": "error" if failed else "success",
            "steps": done,
            "url": next((d.get("url") for d in reversed(done) if d.get("url")), None),
            "title": next((d.get("title") for d in reversed(done) if d.get("title")), None),
        }
        if failed:
            result["error"] = f"step {len(done)} ({failed.get('action')}): {failed.get('error')}"
        if refused:
            result["blocked_requests"] = refused[:20]
        return result

    async def _step(self, page: Any, step: Dict[str, Any], timeout_ms: int, context: Dict[str, Any]) -> Dict[str, Any]:
        action = step["action"]
        if action == "navigate":
            return await self._action_navigate(page, step, timeout_ms)
        if action == "click":
            return await self._action_click(page, step, timeout_ms)
        if action == "type":
            return await self._action_type(page, step, timeout_ms)
        if action == "screenshot":
            return await self._action_screenshot(page, step, timeout_ms, context)
        if action == "get_text":
            return await self._action_get_text(page, step, timeout_ms)
        return await self._action_evaluate(page, step)

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    async def _action_navigate(self, page, args: dict, timeout_ms: int) -> dict:
        url = (args.get("url") or "").strip()
        if not url:
            return {"status": "error", "action": "navigate", "error": "'url' is required for navigate action."}
        from src.common.net_guard import BlockedURL, check_url
        try:
            await check_url(url)
        except BlockedURL as exc:
            return {"status": "error", "action": "navigate", "error": f"URL refused: {exc}"}

        wait_until = args.get("wait_for", "load")
        if wait_until not in _VALID_WAIT_UNTIL:
            wait_until = "load"

        await page.goto(url, wait_until=wait_until, timeout=timeout_ms)

        title = await page.title()
        text = await page.inner_text("body")
        if len(text) > _MAX_OUTPUT_CHARS:
            text = text[:_MAX_OUTPUT_CHARS] + f"\n... [truncated, {len(text)} total chars]"

        return {
            "status": "success",
            "action": "navigate",
            "url": page.url,
            "title": title,
            "content": text,
        }

    async def _action_click(self, page, args: dict, timeout_ms: int) -> dict:
        url = (args.get("url") or "").strip()
        selector = (args.get("selector") or "").strip()
        if not selector:
            return {"status": "error", "action": "click", "error": "'selector' is required for click action."}

        # Navigate first if URL provided
        if url:
            if _is_url_blocked(url):
                return {"status": "error", "action": "click", "error": f"URL scheme blocked: {url}"}
            wait_until = args.get("wait_for", "load")
            if wait_until not in _VALID_WAIT_UNTIL:
                wait_until = "load"
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)

        await page.click(selector, timeout=timeout_ms)
        # Wait for any navigation/network that clicking might trigger
        await page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 10000))

        title = await page.title()
        return {
            "status": "success",
            "action": "click",
            "url": page.url,
            "title": title,
            "selector": selector,
            "message": f"Clicked element matching '{selector}'",
        }

    async def _action_type(self, page, args: dict, timeout_ms: int) -> dict:
        url = (args.get("url") or "").strip()
        selector = (args.get("selector") or "").strip()
        text = args.get("text", "")
        if not selector:
            return {"status": "error", "action": "type", "error": "'selector' is required for type action."}
        if text is None:
            return {"status": "error", "action": "type", "error": "'text' is required for type action."}

        if url:
            if _is_url_blocked(url):
                return {"status": "error", "action": "type", "error": f"URL scheme blocked: {url}"}
            wait_until = args.get("wait_for", "load")
            if wait_until not in _VALID_WAIT_UNTIL:
                wait_until = "load"
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)

        await page.fill(selector, str(text), timeout=timeout_ms)
        title = await page.title()
        return {
            "status": "success",
            "action": "type",
            "url": page.url,
            "title": title,
            "selector": selector,
            "message": f"Typed into element matching '{selector}'",
        }

    async def _action_screenshot(
        self, page, args: dict, timeout_ms: int, context: Optional[dict] = None
    ) -> dict:
        url = (args.get("url") or "").strip()
        selector = (args.get("selector") or "").strip()

        if url:
            if _is_url_blocked(url):
                return {"status": "error", "action": "screenshot", "error": f"URL scheme blocked: {url}"}
            wait_until = args.get("wait_for", "load")
            if wait_until not in _VALID_WAIT_UNTIL:
                wait_until = "load"
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)

        _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        import uuid
        file_name = f"screenshot_{uuid.uuid4().hex[:8]}.png"
        file_path = _SCREENSHOT_DIR / file_name

        if selector:
            element = await page.query_selector(selector)
            if element:
                await element.screenshot(path=str(file_path), timeout=timeout_ms)
            else:
                return {"status": "error", "action": "screenshot", "error": f"Element '{selector}' not found."}
        else:
            await page.screenshot(path=str(file_path), full_page=True, timeout=timeout_ms)

        title = await page.title()

        # Try to save as artifact if context provides company_id
        artifact_id = None
        try:
            if context and context.get("company_id"):
                from src.common.database import AsyncSessionLocal
                from src.ai.artifact_service import ArtifactService, ORIGIN_SYSTEM

                async with AsyncSessionLocal() as db_session:
                    art_svc = ArtifactService(db_session)
                    with open(file_path, "rb") as f:
                        content_bytes = f.read()
                    saved = await art_svc.save_artifact(
                        file_bytes=content_bytes,
                        file_name=file_name,
                        mime_type="image/png",
                        file_category="screenshots",
                        origin=ORIGIN_SYSTEM,
                        company_id=context["company_id"],
                        purpose=f"Browser screenshot of {url or 'current page'}",
                        generated_by="headless_browser",
                        campaign_id=context.get("campaign_id"),
                        agent_id=context.get("agent_id"),
                        run_id=context.get("run_id"),
                    )
                    artifact_id = str(saved.id)
        except Exception as art_err:
            logger.warning(f"Failed to save screenshot as artifact: {art_err}")

        return {
            "status": "success",
            "action": "screenshot",
            "url": page.url,
            "title": title,
            "screenshot_path": str(file_path),
            **({"artifact_id": artifact_id} if artifact_id else {}),
            "message": f"Screenshot saved to {file_path}",
        }

    async def _action_get_text(self, page, args: dict, timeout_ms: int) -> dict:
        url = (args.get("url") or "").strip()
        selector = (args.get("selector") or "").strip()

        if url:
            if _is_url_blocked(url):
                return {"status": "error", "action": "get_text", "error": f"URL scheme blocked: {url}"}
            wait_until = args.get("wait_for", "load")
            if wait_until not in _VALID_WAIT_UNTIL:
                wait_until = "load"
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)

        if selector:
            element = await page.query_selector(selector)
            if not element:
                return {"status": "error", "action": "get_text", "error": f"Element '{selector}' not found."}
            text = await element.inner_text()
        else:
            text = await page.inner_text("body")

        if len(text) > _MAX_OUTPUT_CHARS:
            text = text[:_MAX_OUTPUT_CHARS] + f"\n... [truncated, {len(text)} total chars]"

        title = await page.title()
        return {
            "status": "success",
            "action": "get_text",
            "url": page.url,
            "title": title,
            "content": text,
        }

    async def _action_evaluate(self, page, args: dict) -> dict:
        url = (args.get("url") or "").strip()
        javascript = (args.get("javascript") or "").strip()
        if not javascript:
            return {"status": "error", "action": "evaluate", "error": "'javascript' is required for evaluate action."}

        if url:
            if _is_url_blocked(url):
                return {"status": "error", "action": "evaluate", "error": f"URL scheme blocked: {url}"}
            await page.goto(url, wait_until="load")

        result = await page.evaluate(javascript)
        result_str = str(result)
        if len(result_str) > _MAX_OUTPUT_CHARS:
            result_str = result_str[:_MAX_OUTPUT_CHARS] + f"\n... [truncated]"

        title = await page.title()
        return {
            "status": "success",
            "action": "evaluate",
            "url": page.url,
            "title": title,
            "result": result_str,
        }

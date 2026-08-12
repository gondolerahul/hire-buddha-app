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
import re
from typing import Any, Dict, Optional
from pathlib import Path

from src.ai.tools.base import Tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------
_MAX_OUTPUT_CHARS = 16384
_DEFAULT_TIMEOUT_MS = 30000
_MAX_TIMEOUT_MS = 120000
_SCREENSHOT_DIR = Path("/tmp/browser_screenshots")

_BLOCKED_URL_SCHEMES = re.compile(r"^(file|javascript|data|ftp):", re.IGNORECASE)

_VALID_ACTIONS = {"navigate", "click", "type", "screenshot", "get_text", "evaluate"}

_VALID_WAIT_UNTIL = {"load", "domcontentloaded", "networkidle", "commit"}


def _is_url_blocked(url: str) -> bool:
    """Check if a URL uses a blocked protocol."""
    return bool(_BLOCKED_URL_SCHEMES.match(url.strip()))


class HeadlessBrowserTool(Tool):
    """
    Interact with web pages using a headless Chromium browser.

    Supports navigation, clicking, typing, screenshots, text extraction,
    and JavaScript evaluation. Each invocation creates an isolated browser
    context that is automatically destroyed after execution.
    """

    name = "headless_browser"
    description = (
        "Interact with web pages using a headless browser (Chromium). "
        "Supports actions: navigate (go to URL), click (click element), "
        "type (type into input), screenshot (capture page image), "
        "get_text (extract page text), evaluate (run JavaScript). "
        "Input must be a JSON string with 'action' and action-specific fields. "
        "Returns JSON with status, page title, content, and any action results."
    )

    async def run(self, input_data: str) -> str:
        """Execute browser action and return structured JSON result."""
        return await self._execute(input_data)

    async def run_with_context(
        self, input_data: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        return await self._execute(input_data, context)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _execute(
        self, input_data: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        # 1. Parse input
        try:
            if isinstance(input_data, dict):
                args = input_data
            else:
                args = json.loads(input_data)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({
                "error": "Input must be a JSON string with an 'action' key."
            })

        action = (args.get("action") or "").strip().lower()
        if action not in _VALID_ACTIONS:
            return json.dumps({
                "error": f"Invalid action '{action}'. Must be one of: {', '.join(sorted(_VALID_ACTIONS))}"
            })

        timeout_ms = min(
            int(args.get("timeout_ms", _DEFAULT_TIMEOUT_MS)),
            _MAX_TIMEOUT_MS,
        )

        # 2. Launch browser and execute action
        try:
            return await self._run_browser_action(action, args, timeout_ms, context)
        except Exception as exc:
            logger.error(f"HeadlessBrowserTool unexpected error: {exc}", exc_info=True)
            return json.dumps({
                "status": "error",
                "action": action,
                "error": f"Browser action failed: {exc}",
            })

    async def _run_browser_action(
        self,
        action: str,
        args: dict,
        timeout_ms: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Open a browser session via the SandboxRuntime, execute the action on
        its page, and return the result. The runtime owns browser lifecycle
        (launch/context/teardown); the action logic stays here."""
        import time as _time

        from src.ai.tools.sandbox.runtime import (
            resolve_persistent_browser_dir,
            resolve_sandbox_runtime,
        )

        runtime = await resolve_sandbox_runtime(context)
        user_data_dir = await resolve_persistent_browser_dir(context)
        _session_start = _time.monotonic()
        try:
            async with runtime.open_browser_session(
                timeout_ms=timeout_ms, user_data_dir=user_data_dir
            ) as session:
                page = session.page
                if action == "navigate":
                    result = await self._action_navigate(page, args, timeout_ms)
                elif action == "click":
                    result = await self._action_click(page, args, timeout_ms)
                elif action == "type":
                    result = await self._action_type(page, args, timeout_ms)
                elif action == "screenshot":
                    result = await self._action_screenshot(page, args, timeout_ms, context)
                elif action == "get_text":
                    result = await self._action_get_text(page, args, timeout_ms)
                elif action == "evaluate":
                    result = await self._action_evaluate(page, args)
                else:
                    result = {"error": f"Unknown action: {action}"}

                result_json = json.dumps(result)
        except ImportError:
            return json.dumps({
                "error": "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            })
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
        return result_json

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    async def _action_navigate(self, page, args: dict, timeout_ms: int) -> dict:
        url = (args.get("url") or "").strip()
        if not url:
            return {"status": "error", "action": "navigate", "error": "'url' is required for navigate action."}
        if _is_url_blocked(url):
            return {"status": "error", "action": "navigate", "error": f"URL scheme blocked: {url}"}

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

    # ------------------------------------------------------------------
    # Function schema for LLM function calling
    # ------------------------------------------------------------------

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "The browser action to perform. One of: "
                            "navigate, click, type, screenshot, get_text, evaluate"
                        ),
                        "enum": list(sorted(_VALID_ACTIONS)),
                    },
                    "url": {
                        "type": "string",
                        "description": (
                            "URL to navigate to. Required for 'navigate'. "
                            "Optional for other actions (navigates first if provided)."
                        ),
                    },
                    "selector": {
                        "type": "string",
                        "description": (
                            "CSS selector for the target element. "
                            "Required for click, type. Optional for screenshot, get_text."
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to type into the element. Required for 'type' action.",
                    },
                    "javascript": {
                        "type": "string",
                        "description": (
                            "JavaScript code to evaluate on the page. "
                            "Required for 'evaluate' action."
                        ),
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Action timeout in milliseconds (default 30000, max 120000).",
                        "default": 30000,
                    },
                    "wait_for": {
                        "type": "string",
                        "description": (
                            "Wait condition after navigation: "
                            "load, domcontentloaded, networkidle, commit"
                        ),
                        "default": "load",
                    },
                },
                "required": ["action"],
            },
        }

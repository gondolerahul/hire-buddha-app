"""
HeadlessBrowserTool — Headless browser interaction for AI agents.

One call is one Chromium session: the model gives ``steps`` (navigate, click,
type, screenshot, get_text, evaluate), run in order on one page. The steps are
a request the sandbox runtime runs with
:mod:`~src.ai.tools.sandbox.browser_runner` (TL-18): inside the company's
``web`` container under the container runtime — its only way out the egress
proxy that refuses private addresses — or in-process behind the host's SSRF
guard. Screenshots go to the call's drop box and are kept as the run's
artifacts (TL-36).

Output (JSON string): ``status``, ``steps`` (each step's result), the last
``url`` and ``title``, ``error`` naming the first step that failed, and
``blocked_requests`` the host guard refused.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, model_validator

from src.ai.tools.base import Tool, ToolOutput, ToolParams

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS = 30000
_MAX_TIMEOUT_MS = 120000


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
    """Interact with web pages using a headless Chromium browser: one session
    per call, the steps in order, nothing kept between calls (unless the
    company keeps a browser profile, S5)."""
    timeout_seconds = 180  # per call (EP-08)

    name = "headless_browser"
    category = "browser"
    description = (
        "Interact with web pages using a headless browser (Chromium). Each call is one "
        "browser session: give the actions as 'steps', run in order on one page "
        "(navigate, click, type, screenshot, get_text, evaluate), so a login and a read "
        "happen in one call. Nothing is kept between calls. Returns JSON with each step's result; "
        "a screenshot is kept as a file of the run."
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
        """One browser session, run by the runtime the company's switch picks;
        stops at the first step that fails."""
        import time as _time

        from src.ai.tools.sandbox.drop_box import drop_box
        from src.ai.tools.sandbox.runtime import (
            resolve_persistent_browser_dir,
            resolve_sandbox_runtime,
        )

        runtime = await resolve_sandbox_runtime(context)
        steps = [step.model_dump(exclude_none=True) for step in params.steps]
        if params.url:
            steps.insert(0, {"action": "navigate", "url": params.url})
        request: Dict[str, Any] = {
            "steps": steps,
            "timeout_ms": params.timeout_ms,
            "user_data_dir": await resolve_persistent_browser_dir(context),
        }
        _session_start = _time.monotonic()
        try:
            async with drop_box(context, generated_by="headless_browser") as box:
                request["out_dir"] = box.path if box else None
                session = await runtime.run_browser(request, timeout=float(self.timeout_seconds - 10))
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
        done: List[Dict[str, Any]] = list(session.get("steps") or [])
        _attach_screenshots(done, box.saved if box else [])
        failed = next((d for d in done if d.get("status") == "error"), None)
        result: Dict[str, Any] = {
            "status": "error" if failed else "success",
            "steps": done,
            "url": next((d.get("url") for d in reversed(done) if d.get("url")), None),
            "title": next((d.get("title") for d in reversed(done) if d.get("title")), None),
        }
        if failed:
            result["error"] = f"step {done.index(failed) + 1} ({failed.get('action')}): {failed.get('error')}"
        refused = session.get("blocked_requests") or []
        if refused:
            result["blocked_requests"] = refused[:20]
        return result


def _attach_screenshots(steps: List[Dict[str, Any]], saved: List[Dict[str, Any]]) -> None:
    """A screenshot step names the file it wrote; after the drop box is
    collected it names the artifact instead, or fails if it was not kept."""
    kept = {r["file"]: r for r in saved}
    for step in steps:
        name = step.pop("file", None)
        if name is None:
            continue
        record = kept.get(name)
        if record is None:
            step.update(status="error", error="could not keep the screenshot")
            continue
        step.update(artifact_id=record["artifact_id"], download_url=record["download_url"],
                    message=f"Screenshot kept: {record['download_url']}")

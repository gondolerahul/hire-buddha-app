"""Tool execution module for parsing and executing tool calls from LLM responses."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional, Any, Tuple
from src.ai.tools.base import Tool as _BaseTool, ToolOutput
from src.ai.core.trace import span as _trace_span
import json
import logging
import re

if TYPE_CHECKING:
    from src.ai.governance.tool_access import ToolAccess, Via

logger = logging.getLogger(__name__)

def _stamp_tool_span(sp, tr: "ToolResult") -> None:
    """Copy a finished ToolResult onto its trace span (best-effort)."""
    try:
        sp.set_output(tr.output)
        sp.update(success=tr.success, skipped=tr.skipped)
        if tr.error:
            sp.set_error(tr.error)
        elif tr.skipped and tr.skip_reason:
            sp.update(skip_reason=tr.skip_reason)
    except Exception:
        pass


# A tool reports failure in its result, not by raising: ``{"error": …}``,
# ``{"success": false, …}``, or a string starting ``Error: …`` /
# ``Error <doing x>: …`` / ``[ERROR] …``.
_ERROR_PREFIX = re.compile(r"^\s*(\[error\]|error(\s+\w+)?\s*:)", re.IGNORECASE)


def result_error(output: Any) -> Optional[str]:
    """The error a tool reported in its own result, or None (TL-52)."""
    if isinstance(output, dict):
        if output.get("error"):
            return str(output["error"])
        if output.get("success") is False:
            return str(output.get("message") or output.get("error_message")
                       or "the tool reported success=false")
        return None
    if isinstance(output, str):
        text = output.strip()
        if _ERROR_PREFIX.match(text):
            return text[:1000]
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except ValueError:
                return None
            return result_error(parsed) if isinstance(parsed, dict) else None
    return None


def settle_result(tr: "ToolResult") -> "ToolResult":
    """A result whose payload reports an error is a failure, whatever the
    call path said: it is logged and treated as failed and is not billed."""
    if tr.success and not tr.skipped:
        err = result_error(tr.output)
        if err:
            tr.success = False
            tr.error = err
    return tr


# ---------------------------------------------------------------------------
# P3.2 — Typed ToolResult (replaces raw dict returns)
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    """
    Canonical, typed return value for all tool executions.

    All methods in ToolExecutor now return List[ToolResult] instead of
    List[Dict]. The .to_dict() method is provided for backward compatibility
    with code that still expects a plain dict (e.g. format_tool_results).
    """
    tool: str
    args: Dict[str, Any]
    output: Any
    success: bool
    latency_ms: int = 0
    error: Optional[str] = None    # Set when success=False
    skipped: bool = False          # Set when rate limit exceeded
    skip_reason: Optional[str] = None
    # The call ran on input an LLM rewrote after a format error (EP-24): it was
    # billed as a reformat retry and is marked on its log row and in the trace.
    reformatted: bool = False
    # Priced units the call used (``ToolOutput.metadata["billable_units"]``):
    # a batch search's paid sub-queries; 0 when a free backend answered.
    units: float = 1.0
    # Other tools' prices the call also used (``ToolOutput.metadata["also_bill"]``,
    # tool id -> units): video_add_sound's generated narration is billed as
    # text_to_speech seconds, its generated music as a music_generation clip.
    also_bill: Dict[str, float] = field(default_factory=dict)
    # A call that writes carries its key (TL-39). ``replayed``: the run had
    # already made this exact write, so its earlier result was returned and
    # nothing was written, billed or counted again.
    idempotency_key: Optional[str] = None
    replayed: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Backward-compatible dict representation."""
        return asdict(self)

    def charges(self) -> List[Tuple[str, float]]:
        """What the call is billed as: (tool id, units) — itself, then ``also_bill``."""
        return [(self.tool, self.units), *((tool, float(units)) for tool, units in self.also_bill.items())]


def _refused(tool_name: Any, args: Any, denied: Any) -> ToolResult:
    """A call that never ran: the tool may not run here (P3.1). It is not
    retried, not re-routed to a fallback, and not billed."""
    message = getattr(denied, "message", None) or f"Error: tool '{tool_name}' is not available."
    return ToolResult(
        tool=str(tool_name), args=args if isinstance(args, dict) else {"input": args},
        output=message, success=False, error=message,
        skipped=True, skip_reason=getattr(denied, "reason", "refused"),
    )


async def _plan_refusal(name: str, context: Optional[Dict[str, Any]]) -> Optional[str]:
    """Why the company's plan does not include this tool (Phase 15 T6-2), or ``None``.
    A plan that cannot be read lets the call run: every feature is on by default."""
    from src.billing.features import check_feature, feature_for_tool

    key = feature_for_tool(name)
    company_id = (context or {}).get("company_id")
    if key is None or not company_id:
        return None
    try:
        from uuid import UUID as _UUID

        from src.common.tenancy.session import control_session
        async with control_session() as db:
            return await check_feature(db, _UUID(str(company_id)), key)
    except Exception:  # noqa: BLE001
        return None


async def _run(tool: _BaseTool, name: str, args: Any, logged_args: Dict[str, Any],
               context: Optional[Dict[str, Any]], timeout_s: Optional[float] = None) -> ToolResult:
    """One call through the tool's one entry point, ``invoke`` (TL-41).

    A call that writes runs once per run (TL-39): when the run already made
    this exact write successfully, its result is returned instead.
    """
    from src.ai.governance.idempotency import earlier_result, write_key

    locked = await _plan_refusal(name, context)
    if locked:
        return ToolResult(tool=name, args=logged_args, output=f"Error: {locked}", success=False, error=locked,
                          skipped=True, skip_reason="feature_locked")
    from src.ai.governance.connector_actions import hold

    held = await hold(name, args, context)
    if held is not None:  # a write to a connected account waits for a person (SH-E4); not billed
        return ToolResult(tool=name, args=logged_args, output=held, success="error" not in held,
                          error=held.get("error"), units=0)
    key = write_key((context or {}).get("run_id"), name, args)
    if key:
        try:
            prior = await earlier_result((context or {}).get("run_id"), key,
                                         (context or {}).get("company_id"))
        except Exception:  # noqa: BLE001 - the lookup never blocks a call
            prior = None
        if prior is not None:
            return ToolResult(tool=name, args=logged_args, output=prior, success=True,
                              units=0, idempotency_key=key, replayed=True)
    from src.connections import source_data

    start = datetime.now(timezone.utc)
    units = 1.0
    also_bill: Dict[str, float] = {}
    limit = float(timeout_s or tool.timeout_seconds)
    with source_data.watch() as used:
        try:
            # One call may not hold the worker past its timeout (EP-08): before,
            # only the enclosing step's timeout bounded it.
            out: ToolOutput = await asyncio.wait_for(tool.invoke(args, context), timeout=limit)
            error = None if out.success else (out.error or "the tool failed")
            output = out.output
            units = float(out.metadata.get("billable_units", 1))
            extra = out.metadata.get("also_bill") or {}
            also_bill = {str(k): float(v) for k, v in extra.items() if float(v) > 0} if isinstance(extra, dict) else {}
        except asyncio.TimeoutError:
            error = f"tool_timeout: '{name}' did not finish within {limit:g}s"
            output = f"Error: {error}"
        except Exception as exc:
            error, output = str(exc), f"Error: {exc}"
    if error is None and used:  # the run read through a connection: its provider's rules follow (SH-E2)
        try:
            await source_data.mark(context, name, args, used)
        except Exception:  # noqa: BLE001 - never lose a result to the mark; it is logged
            logger.warning("the read of %s through %s was not marked", name, used, exc_info=True)
    if error is None:  # mail, comments and messages from outside: screened and quoted (SH-E3)
        from src.ai.governance.untrusted import guard_tool_output

        try:
            output, _screening = await guard_tool_output(name, args, output)
        except Exception:  # noqa: BLE001 - never lose a result to the screen; it is logged
            logger.warning("connector content of %s not screened", name, exc_info=True)
    latency = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    return ToolResult(tool=name, args=logged_args, output=output, success=error is None,
                      latency_ms=latency, error=error, units=units, also_bill=also_bill,
                      idempotency_key=key)


class ToolExecutor:
    """Handles parsing and execution of tool calls from LLM responses.

    Every lookup goes through ``ToolAccess`` (``ai.governance.tool_access``): there is
    no entry point that runs a tool by name alone (TL-50, TL-10).
    """

    @staticmethod
    async def execute_from_function_calls(
        function_calls: List[Dict[str, Any]],
        extra_context: Optional[Dict[str, Any]] = None,
        *,
        access: "ToolAccess",
    ) -> List[ToolResult]:
        """
        Execute tools from native Gemini function call format.

        P3.2: Returns List[ToolResult] instead of List[Dict].

        Args:
            function_calls: [{"name": "tool_name", "args": {...}}]
            extra_context:  Optional context injected into every tool call
                            (must contain at least {"company_id": ..., "user_id": ...})
            access:         What this entity may run (``ToolAccess``), including
                            the run's call limits. The model names the tool, so
                            it resolves as an LLM call.
        Returns:
            List[ToolResult] with typed results
        """
        async def _one(call: Dict[str, Any]) -> ToolResult:
            """Execute a single function call and return its typed result.

            Extracted verbatim from the legacy loop body so each call can be
            wrapped in a trace span; ``continue``/append became ``return``.
            """
            tool_name = call.get("name")
            tool_args = call.get("args", {})
            tool = access.resolve(tool_name, "llm")
            if not isinstance(tool, _BaseTool):
                return _refused(tool_name, tool_args, tool)
            return await _run(tool, str(tool_name), tool_args, tool_args, extra_context,
                              access.timeout_for(str(tool_name), tool))

        results: List[ToolResult] = []
        for call in function_calls:
            async with _trace_span(
                "tool", call.get("name"), args=call.get("args", {}),
            ) as _sp:
                tr = settle_result(await _one(call))
                _stamp_tool_span(_sp, tr)
            results.append(tr)

        return results

    @staticmethod
    async def execute_tools(
        tool_calls: List[Dict[str, str]],
        extra_context: Optional[Dict[str, Any]] = None,
        *,
        access: "ToolAccess",
        via: "Via" = "plan",
    ) -> List[ToolResult]:
        """
        Execute tool calls and return results (legacy method, now returns ToolResult).

        ``via`` says who asked: ``"plan"`` for a plan step, ``"llm"`` for a
        retry of a call the model made.
        """
        async def _one(call: Dict[str, str]) -> ToolResult:
            tool = access.resolve(call["tool"], via)
            if not isinstance(tool, _BaseTool):
                return _refused(call["tool"], {"input": call.get("input", "")}, tool)
            # The tool's input is the plan's; who the call is for travels only
            # in ``context`` (an ExecutionContext, P3.2), never in params.
            return await _run(tool, call["tool"], call["input"], {"input": call["input"]}, extra_context,
                              access.timeout_for(call["tool"], tool))

        results: List[ToolResult] = []
        for call in tool_calls:
            async with _trace_span(
                "tool", call.get("tool"), input=call.get("input", ""),
            ) as _sp:
                tr = settle_result(await _one(call))
                _stamp_tool_span(_sp, tr)
            results.append(tr)
        return results

    @staticmethod
    def format_tool_results(results: List) -> str:
        """
        Format tool execution results for inclusion in LLM context.
        Accepts both List[ToolResult] and List[Dict] for backward compatibility.
        """
        if not results:
            return ""

        formatted = "\n\n=== Tool Execution Results ===\n"
        for i, result in enumerate(results, 1):
            # Support both ToolResult and plain dict
            if isinstance(result, ToolResult):
                r = result.to_dict()
            else:
                r = result
            formatted += f"\n{i}. Tool: {r['tool']}\n"
            if r.get("skipped"):
                formatted += f"   ⚠️  SKIPPED — {r.get('skip_reason', 'Rate limit exceeded')}\n"
                continue
            if "args" in r:
                formatted += f"   Args: {json.dumps(r['args'])}\n"
            elif "input" in r:
                formatted += f"   Input: {r['input']}\n"
            output_str = str(r.get("output", ""))
            formatted += f"   Output: {output_str[:500]}{'...' if len(output_str) > 500 else ''}\n"
            formatted += f"   Success: {r.get('success', 'N/A')} | Latency: {r.get('latency_ms', 0)}ms\n"
        formatted += "=== End Tool Results ===\n"
        return formatted

    @staticmethod
    def format_function_call_response(results: List) -> List[Dict[str, Any]]:
        """
        Format tool results for Gemini function response format.
        Accepts both List[ToolResult] and List[Dict].
        """
        responses = []
        for result in results:
            if isinstance(result, ToolResult):
                tool_name = result.tool
                output = result.output
                success = result.success
            else:
                tool_name = result["tool"]
                output = result.get("output")
                success = result.get("success", True)
            responses.append({
                "function_response": {
                    "name": tool_name,
                    "response": {"output": output, "success": success}
                }
            })
        return responses



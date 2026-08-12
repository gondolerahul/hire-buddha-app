"""Tool execution module for parsing and executing tool calls from LLM responses."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from src.ai.tools import ToolRegistry
from src.ai.tools.base import Tool as _BaseTool, ToolParams as _BaseToolParams
from src.ai.core.trace import span as _trace_span
import json
import logging

logger = logging.getLogger(__name__)

# Cache base references for introspection in execute_from_function_calls
_base_run_typed = _BaseTool.run_typed
_base_tool_params = _BaseToolParams


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
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Backward-compatible dict representation."""
        return asdict(self)


class ToolExecutor:
    """Handles parsing and execution of tool calls from LLM responses."""

    @staticmethod
    async def execute_from_function_calls(
        function_calls: List[Dict[str, Any]],
        extra_context: Optional[Dict[str, Any]] = None,
        # P3.3 — per-run call budget (mutated in-place by caller)
        call_counts: Optional[Dict[str, int]] = None,
    ) -> List[ToolResult]:
        """
        Execute tools from native Gemini function call format.

        P3.2: Returns List[ToolResult] instead of List[Dict].
        P3.3: Enforces per-run rate limits via call_counts dict.

        Args:
            function_calls: [{"name": "tool_name", "args": {...}}]
            extra_context:  Optional context injected into every tool call
                            (must contain at least {"company_id": ..., "user_id": ...})
            call_counts:    Mutable dict tracking how many times each tool has
                            been called in this run. Pass a fresh {} per
                            ExecutionRun and keep it alive across all REACT turns.
                            Keys are tool names, values are call counts.
        Returns:
            List[ToolResult] with typed results
        """
        if call_counts is None:
            call_counts = {}

        async def _one(call: Dict[str, Any]) -> ToolResult:
            """Execute a single function call and return its typed result.

            Extracted verbatim from the legacy loop body so each call can be
            wrapped in a trace span; ``continue``/append became ``return``.
            """
            tool_name = call.get("name")
            tool_args = call.get("args", {})
            # rate_limit_per_run can be passed alongside args by the worker
            rate_limit = call.get("rate_limit_per_run")

            # P3.3 — Enforce per-run rate limit
            if rate_limit is not None:
                current_count = call_counts.get(tool_name, 0)
                if current_count >= rate_limit:
                    return ToolResult(
                        tool=tool_name,
                        args=tool_args,
                        output=None,
                        success=False,
                        skipped=True,
                        skip_reason=(
                            f"Rate limit exceeded: tool '{tool_name}' has been called "
                            f"{current_count}/{rate_limit} times in this run."
                        ),
                    )

            tool = ToolRegistry.get_tool(tool_name)

            if tool:
                _start = datetime.now(timezone.utc)
                try:
                    # Prefer run_typed() if the tool has overridden it
                    _has_typed = type(tool).run_typed is not _base_run_typed
                    if _has_typed and isinstance(tool_args, dict):
                        # Discover params class from run_typed type hints
                        import typing as _typing_mod
                        hints = _typing_mod.get_type_hints(tool.run_typed)
                        params_cls = hints.get("params")
                        if params_cls and params_cls is not _base_tool_params:
                            clean_args = {k: v for k, v in tool_args.items()
                                          if k not in ("company_id", "user_id")}
                            typed_params = params_cls(**clean_args)
                            # Forward extra_context to run_typed() if supported.
                            # This is critical for tools like WebSearchTool that
                            # need company_id to resolve API keys from the registry.
                            import inspect as _inspect
                            _rtyped_sig = _inspect.signature(tool.run_typed)
                            if "context" in _rtyped_sig.parameters:
                                typed_result = await tool.run_typed(typed_params, context=extra_context)
                            else:
                                typed_result = await tool.run_typed(typed_params)
                            _latency = int((datetime.now(timezone.utc) - _start).total_seconds() * 1000)
                            call_counts[tool_name] = call_counts.get(tool_name, 0) + 1
                            return ToolResult(
                                tool=tool_name,
                                args=tool_args,
                                output=typed_result.output,
                                success=typed_result.success,
                                latency_ms=_latency,
                                error=typed_result.error_message,
                            )
                except Exception as _typed_err:
                    # Typed path failed (type hint resolution, param mismatch, etc.)
                    # Fall through to legacy string-based path silently.
                    logger.debug(f"Typed tool path failed for {tool_name}, using legacy: {_typed_err}")

                try:

                    # Legacy path: build raw input string
                    if isinstance(tool_args, dict) and "input" in tool_args:
                        raw_input = tool_args["input"]
                    elif isinstance(tool_args, str):
                        raw_input = tool_args
                    else:
                        clean_args = {k: v for k, v in tool_args.items()
                                      if k not in ("company_id", "user_id")}
                        raw_input = json.dumps(clean_args)

                    output = await tool.run_with_context(raw_input, context=extra_context)
                    _latency = int((datetime.now(timezone.utc) - _start).total_seconds() * 1000)

                    # P3.3 — Increment counter on successful call
                    call_counts[tool_name] = call_counts.get(tool_name, 0) + 1

                    return ToolResult(
                        tool=tool_name,
                        args=tool_args,
                        output=output,
                        success=True,
                        latency_ms=_latency,
                    )
                except Exception as e:
                    _latency = int((datetime.now(timezone.utc) - _start).total_seconds() * 1000)
                    return ToolResult(
                        tool=tool_name,
                        args=tool_args,
                        output=f"Error: {str(e)}",
                        success=False,
                        latency_ms=_latency,
                        error=str(e),
                    )
            else:
                return ToolResult(
                    tool=tool_name,
                    args=tool_args,
                    output=(
                        f"Error: Tool '{tool_name}' not found. "
                        f"Available: {[t['name'] for t in ToolRegistry.list_tools()]}"
                    ),
                    success=False,
                    error=f"Tool '{tool_name}' not registered",
                )

        results: List[ToolResult] = []
        for call in function_calls:
            async with _trace_span(
                "tool", call.get("name"), args=call.get("args", {}),
            ) as _sp:
                tr = await _one(call)
                _stamp_tool_span(_sp, tr)
            results.append(tr)

        return results

    @staticmethod
    async def execute_tools(
        tool_calls: List[Dict[str, str]],
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> List[ToolResult]:
        """
        Execute tool calls and return results (legacy method, now returns ToolResult).
        """
        async def _one(call: Dict[str, str]) -> ToolResult:
            tool = ToolRegistry.get_tool(call["tool"])
            _start = datetime.now(timezone.utc)
            if tool:
                try:
                    tool_input = call["input"]
                    if extra_context:
                        try:
                            input_dict = json.loads(tool_input) if isinstance(tool_input, str) else tool_input
                            if isinstance(input_dict, dict):
                                input_dict.update(extra_context)
                                tool_input = json.dumps(input_dict)
                        except Exception:
                            pass
                    # Use run_with_context to pass execution context (company_id, user_id)
                    # so tools can look up API keys from the integration registry
                    output = await tool.run_with_context(tool_input, context=extra_context)
                    _latency = int((datetime.now(timezone.utc) - _start).total_seconds() * 1000)
                    return ToolResult(
                        tool=call["tool"],
                        args={"input": call["input"]},
                        output=output,
                        success=True,
                        latency_ms=_latency,
                    )
                except Exception as e:
                    _latency = int((datetime.now(timezone.utc) - _start).total_seconds() * 1000)
                    return ToolResult(
                        tool=call["tool"],
                        args={"input": call["input"]},
                        output=f"Error: {str(e)}",
                        success=False,
                        latency_ms=_latency,
                        error=str(e),
                    )
            else:
                _latency = int((datetime.now(timezone.utc) - _start).total_seconds() * 1000)
                return ToolResult(
                    tool=call["tool"],
                    args={"input": call.get("input", "")},
                    output=f"Error: Tool '{call['tool']}' not found",
                    success=False,
                    latency_ms=_latency,
                    error=f"Tool '{call['tool']}' not registered",
                )

        results: List[ToolResult] = []
        for call in tool_calls:
            async with _trace_span(
                "tool", call.get("tool"), input=call.get("input", ""),
            ) as _sp:
                tr = await _one(call)
                _stamp_tool_span(_sp, tr)
            results.append(tr)
        return results

    @staticmethod
    def get_tool_schemas(
        tool_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get provider-agnostic JSON function schemas for specified tools.
        Schemas are consumed by LLMRouter adapters (Gemini, Anthropic, Azure)."""
        all_schemas = ToolRegistry.get_all_schemas()
        if tool_ids is None:
            return all_schemas
        return [s for s in all_schemas if s["name"] in tool_ids]

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



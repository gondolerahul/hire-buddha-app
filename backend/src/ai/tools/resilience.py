"""
ai.tools.resilience — Phase 11 Track 8 reformat-retry + fallback chain.

Wraps :class:`ToolExecutor` so that *both* the direct ``TOOL_CALL``
path and the REACT AFC path share one implementation of:

  1. **Classify** the failure (FORMAT / IO / EMPTY / TIMEOUT / OTHER).
  2. **Reformat-retry** on recoverable failures by asking the LLM to
     rewrite the tool input given the exact error message.
  3. **Fallback chain** via ``tool_fallback.get_fallback_tool`` when
     the primary tool still doesn't produce usable output.
  4. **Final empty marker** so the agent reasoning over the result
     receives a structured ``[TOOL_EMPTY]`` string instead of an
     ambiguous empty cell.

Until Track 8 the REACT path silently skipped step 1 and step 2,
producing a quiet asymmetry between paths. Now both go through
:meth:`ToolResilience.run`.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional

from src.ai.tool_executor import ToolExecutor, ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------


class FailureKind(str, Enum):
    NONE     = "NONE"
    FORMAT   = "FORMAT"
    IO       = "IO"
    EMPTY    = "EMPTY"
    TIMEOUT  = "TIMEOUT"
    ERROR_MSG = "ERROR_MSG"
    OTHER    = "OTHER"


_FORMAT_ERROR_KEYWORDS = {
    "invalid json", "json", "parse", "format", "delimiter",
    "control character", "expecting", "decode",
}
_IO_ERROR_KEYWORDS = {
    "no such file or directory", "errno 2", "errno 22",
    "invalid argument", "file name too long",
}
_EMPTY_KEYWORDS = {"no results", "empty response", "0 results"}
_TIMEOUT_KEYWORDS = {"timeout", "timed out", "deadline exceeded"}
_INFRA_KEYWORDS = {
    "api key", "not configured", "timeout", "connection",
    "unauthorized", "403", "401", "rate limit",
}


def classify_tool_failure(tr: ToolResult) -> FailureKind:
    """Map a :class:`ToolResult` to a :class:`FailureKind`.

    Extracted from the inline keyword logic in ``step_executor._execute_tool_call``
    so the REACT path and direct path use the same rules.
    """
    output_str = str(getattr(tr, "output", "") or "")
    output_lower = output_str.lower()

    is_empty = (
        not getattr(tr, "output", None)
        or (isinstance(tr.output, str) and not tr.output.strip())
        or any(kw in output_lower for kw in _EMPTY_KEYWORDS)
    )
    if is_empty:
        return FailureKind.EMPTY

    # Order matters: prefer the most specific buckets before falling
    # through to the generic ``ERROR_MSG`` / ``OTHER`` catch-alls. An
    # output like ``"ERROR: invalid json ..."`` is both an error-message
    # AND a format error; the FORMAT bucket carries the actionable
    # signal so it wins.
    success = getattr(tr, "success", True)
    if any(kw in output_lower for kw in _TIMEOUT_KEYWORDS):
        return FailureKind.TIMEOUT
    if any(kw in output_lower for kw in _IO_ERROR_KEYWORDS):
        return FailureKind.IO
    if _is_format_error(output_lower):
        return FailureKind.FORMAT

    is_error_msg = (
        isinstance(tr.output, str)
        and tr.output.strip().upper().startswith("ERROR:")
    )
    if is_error_msg:
        return FailureKind.ERROR_MSG
    if not success:
        return FailureKind.OTHER

    return FailureKind.NONE


def _is_format_error(output_lower: str) -> bool:
    if '"error"' not in output_lower and "error:" not in output_lower:
        return False
    if any(k in output_lower for k in _INFRA_KEYWORDS):
        return False
    return any(k in output_lower for k in _FORMAT_ERROR_KEYWORDS)


# ---------------------------------------------------------------------------
# Resilience wrapper
# ---------------------------------------------------------------------------


__all__ = [
    "ToolResilience",
    "FailureKind",
    "classify_tool_failure",
]


class ToolResilience:
    """Reformat-retry + fallback-chain wrapper around tool execution.

    Construct one per (db, llm_router) pair. ``fallback_table`` is a
    callable matching :func:`ai.tool_fallback.get_fallback_tool` —
    injectable so tests can stub it.
    """

    REFORMAT_RECOVERABLE_KINDS: tuple[FailureKind, ...] = (
        FailureKind.FORMAT,
        FailureKind.IO,
        FailureKind.EMPTY,
        FailureKind.ERROR_MSG,
    )

    def __init__(
        self,
        *,
        llm_router: Any = None,
        reformat_fn: Any = None,
        fallback_table: Any = None,
        tool_executor: Any = None,
        emit_event: Any = None,
    ):
        self.llm = llm_router
        self.reformat_fn = reformat_fn
        if fallback_table is None:
            try:
                from src.ai.tool_fallback import get_fallback_tool
                fallback_table = get_fallback_tool
            except Exception:                                               # pragma: no cover
                fallback_table = None
        self.fallback_table = fallback_table
        self.executor = tool_executor or ToolExecutor
        self.emit = emit_event

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        *,
        run: Any = None,
        entity: Any = None,
        tool_id: str,
        raw_input: str,
        extra_context: Optional[dict] = None,
        step_name: str = "",
        step_description: str = "",
    ) -> ToolResult:
        """Execute a tool with reformat-retry + fallback chain."""
        extra_context = dict(extra_context or {})
        tr = await self._exec_one(tool_id, raw_input, extra_context)
        kind = classify_tool_failure(tr)
        if kind is FailureKind.NONE:
            return tr

        await self._emit(
            "agent.tool.resilience.reformat_attempt",
            run_id=str(getattr(run, "id", "")) if run else None,
            tool_id=tool_id, failure_kind=kind.value,
        )

        # Step 1 — reformat-retry on recoverable failures.
        if kind in self.REFORMAT_RECOVERABLE_KINDS and self.reformat_fn is not None:
            new_input = await self._reformat_input(
                run=run, entity=entity, tool_id=tool_id,
                raw_input=raw_input,
                error_message=str(tr.output or "[EMPTY OUTPUT]"),
                step_description=step_description or step_name,
            )
            if new_input and new_input != raw_input:
                retry = await self._exec_one(tool_id, new_input, extra_context)
                if classify_tool_failure(retry) is FailureKind.NONE:
                    return retry
                tr = retry  # carry the retry's output forward

        # Step 2 — fallback chain.
        if self.fallback_table is not None:
            try:
                alt_tool_id, alt_input = self.fallback_table(tool_id, raw_input)
            except Exception as exc:                                        # pragma: no cover
                logger.debug(f"fallback_table call failed: {exc}")
                alt_tool_id, alt_input = (None, raw_input)
            if alt_tool_id and self._fallback_allowed(entity, alt_tool_id):
                alt_tr = await self._exec_one(alt_tool_id, alt_input, extra_context)
                alt_kind = classify_tool_failure(alt_tr)
                success = alt_kind is FailureKind.NONE
                await self._emit(
                    "agent.tool.resilience.fallback_taken",
                    run_id=str(getattr(run, "id", "")) if run else None,
                    from_tool=tool_id, to_tool=alt_tool_id, success=success,
                )
                if success:
                    alt_tr.tool = f"{tool_id}→{alt_tool_id}"
                    return alt_tr

        # Step 3 — final empty marker.
        await self._emit(
            "agent.tool.resilience.final_empty",
            run_id=str(getattr(run, "id", "")) if run else None,
            tool_id=tool_id, failure_kind=kind.value,
        )
        tr.output = (
            f"[TOOL_EMPTY] Tool '{tool_id}' returned no usable output after "
            f"retries. Failure kind: {kind.value}."
        )
        tr.success = False
        return tr

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _exec_one(
        self, tool_id: str, raw_input: Any, extra_context: dict,
    ) -> ToolResult:
        result = await self.executor.execute_tools(
            [{"tool": tool_id, "input": raw_input}],
            extra_context=extra_context,
        )
        if not result:
            return ToolResult(
                tool=tool_id, args={}, output="[TOOL_EMPTY]",
                success=False,
            )
        return result[0]

    async def run_function_call(
        self,
        *,
        run: Any = None,
        entity: Any = None,
        function_call: dict[str, Any],
        extra_context: Optional[dict] = None,
        call_counts: Optional[dict] = None,
        step_name: str = "",
        step_description: str = "",
    ) -> ToolResult:
        """REACT/AFC variant of :meth:`run`.

        Accepts a native ``function_call`` dict (``{name, args, ...}``) from
        the LLM and preserves the typed-params dispatch in
        :meth:`ToolExecutor.execute_from_function_calls`. Falls back to the
        string-input path only for the reformat-retry and fallback chain,
        matching the direct TOOL_CALL path's recovery story.
        """
        extra_context = dict(extra_context or {})
        call_counts = call_counts if call_counts is not None else {}
        tool_id = str(function_call.get("name") or "")
        tool_args = function_call.get("args", {})

        tr_list = await self.executor.execute_from_function_calls(
            [function_call], extra_context=extra_context, call_counts=call_counts,
        )
        tr = tr_list[0] if tr_list else ToolResult(
            tool=tool_id, args=tool_args, output="[TOOL_EMPTY]", success=False,
        )
        kind = classify_tool_failure(tr)
        if kind is FailureKind.NONE:
            return tr

        await self._emit(
            "agent.tool.resilience.reformat_attempt",
            run_id=str(getattr(run, "id", "")) if run else None,
            tool_id=tool_id, failure_kind=kind.value, path="react_afc",
        )

        # Step 1 — reformat-retry. The reformatter operates on a string
        # payload, so we serialise the original args (sans context keys).
        if kind in self.REFORMAT_RECOVERABLE_KINDS and self.reformat_fn is not None:
            import json as _json
            if isinstance(tool_args, dict):
                clean = {k: v for k, v in tool_args.items()
                         if k not in ("company_id", "user_id")}
                if "input" in clean and len(clean) == 1:
                    original_str = str(clean["input"])
                else:
                    original_str = _json.dumps(clean, default=str)
            else:
                original_str = str(tool_args)

            new_input = await self._reformat_input(
                run=run, entity=entity, tool_id=tool_id,
                raw_input=original_str,
                error_message=str(tr.output or "[EMPTY OUTPUT]"),
                step_description=step_description or step_name,
            )
            if new_input and new_input != original_str:
                retry = await self._exec_one(tool_id, new_input, extra_context)
                if classify_tool_failure(retry) is FailureKind.NONE:
                    return retry
                tr = retry

        # Step 2 — fallback chain (string-input path).
        if self.fallback_table is not None:
            try:
                # Use whatever string form we have for the fallback table.
                seed_input = (
                    tool_args.get("input")
                    if isinstance(tool_args, dict) and "input" in tool_args
                    else str(tool_args)
                )
                alt_tool_id, alt_input = self.fallback_table(tool_id, seed_input)
            except Exception as exc:                                          # pragma: no cover
                logger.debug(f"fallback_table call failed: {exc}")
                alt_tool_id, alt_input = (None, None)
            if alt_tool_id and self._fallback_allowed(entity, alt_tool_id):
                alt_tr = await self._exec_one(alt_tool_id, alt_input, extra_context)
                alt_kind = classify_tool_failure(alt_tr)
                success = alt_kind is FailureKind.NONE
                await self._emit(
                    "agent.tool.resilience.fallback_taken",
                    run_id=str(getattr(run, "id", "")) if run else None,
                    from_tool=tool_id, to_tool=alt_tool_id, success=success,
                    path="react_afc",
                )
                if success:
                    alt_tr.tool = f"{tool_id}→{alt_tool_id}"
                    return alt_tr

        await self._emit(
            "agent.tool.resilience.final_empty",
            run_id=str(getattr(run, "id", "")) if run else None,
            tool_id=tool_id, failure_kind=kind.value, path="react_afc",
        )
        tr.output = (
            f"[TOOL_EMPTY] Tool '{tool_id}' returned no usable output after "
            f"retries. Failure kind: {kind.value}."
        )
        tr.success = False
        return tr

    async def _reformat_input(
        self,
        *,
        run: Any,
        entity: Any,
        tool_id: str,
        raw_input: str,
        error_message: str,
        step_description: str,
    ) -> Optional[str]:
        try:
            return await self.reformat_fn(
                run=run,
                entity=entity,
                tool_id=tool_id,
                original_input=raw_input,
                error_message=error_message,
                step_description=step_description,
            )
        except Exception as exc:                                            # pragma: no cover
            logger.debug(f"reformat_fn failed for {tool_id}: {exc}")
            return None

    @staticmethod
    def _fallback_allowed(entity: Any, alt_tool_id: str) -> bool:
        if entity is None:
            return True
        caps = getattr(entity, "capabilities", None) or {}
        if isinstance(entity, dict):
            caps = entity.get("capabilities") or {}
        tools = [t.get("tool_id") if isinstance(t, dict) else t
                 for t in (caps.get("tools") or [])]
        return not tools or alt_tool_id in tools

    async def _emit(self, name: str, **payload: Any) -> None:
        if self.emit is not None:
            try:
                await self.emit(name, **payload)
                return
            except Exception:                                               # pragma: no cover
                pass
        try:
            from src.ai.core.events import event
            event(name, **payload)
        except Exception:                                                   # pragma: no cover
            pass

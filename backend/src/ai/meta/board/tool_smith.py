"""ai.meta.board.tool_smith — Role 8: synthesize a Tool subclass from a ToolSpec.

The marquee Phase 12 `06` §2 capability. Given a typed :class:`ToolSpec`, the
ToolSmith asks an LLM to write the *body* of a single ``Tool`` subclass that
honours the base contract, the import allow-list, the declared network policy,
and never touches the filesystem outside the sandbox workdir or any secret.

The ToolSmith only *produces source*. It does not execute it — that is the job
of the sandbox tester (container-only, `02`) — nor decide whether to register
it. The :class:`~src.ai.meta.tool_validator.ToolValidator` is the static gate
that follows. The LLM is injected so the synthesis loop is unit-testable
without live credentials.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from src.ai.schemas.tools import NetworkPolicy, ToolSpec

logger = logging.getLogger(__name__)

__all__ = ["ToolSmith", "SynthesisResult"]


_CODE_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


@dataclass
class SynthesisResult:
    source: str
    raw_response: str = ""
    model_used: str = ""


def _build_system_prompt(spec: ToolSpec) -> str:
    net = spec.network_policy
    if net == NetworkPolicy.NONE:
        net_line = "You MUST NOT import or use any network module (no socket, http, urllib, requests, httpx, ...)."
    else:
        net_line = (
            f"Network policy is '{net.value}': you MAY use http/urllib/httpx, but egress is "
            "enforced by the sandbox; assume only allow-listed hosts resolve."
        )
    allowed = ", ".join(sorted(spec.allowed_imports)) or "(none beyond the safe stdlib baseline)"
    return (
        "You are ToolSmith, an expert Python engineer writing ONE self-contained "
        "tool for a sandboxed agent platform.\n\n"
        "Hard constraints (a static analyser will reject violations):\n"
        "  - Define exactly ONE class subclassing `Tool` (from src.ai.tools.base).\n"
        "  - Implement `async def run(self, input_data: str) -> str`. `input_data` is a "
        "JSON string; return a JSON string.\n"
        "  - Set the class attribute `name` to exactly the spec name.\n"
        "  - Allowed imports beyond the safe stdlib (json, math, re, datetime, decimal, "
        "uuid, hashlib, collections, itertools, functools, statistics, ...): "
        f"{allowed}.\n"
        "  - No eval/exec/compile/__import__, no subprocess/os.system/os.popen, no "
        "os.environ/getenv, no dunder traversal (__subclasses__/__globals__/...), no "
        "filesystem writes outside the working directory.\n"
        f"  - {net_line}\n\n"
        "Return ONLY the Python source in a single ```python code block. No prose."
    )


def _build_user_prompt(spec: ToolSpec) -> str:
    examples = ""
    if spec.examples:
        lines = []
        for ex in spec.examples[:6]:
            tail = (
                "should raise/return an error"
                if ex.should_error
                else f"output should contain: {ex.expected_contains!r}"
                if ex.expected_contains
                else "produces a valid result"
            )
            lines.append(f"  - input={ex.input!r} -> {tail}")
        examples = "\nExamples:\n" + "\n".join(lines)
    return (
        f"Tool name: {spec.name}\n"
        f"Description: {spec.description}\n"
        f"Input schema (JSON): {spec.input_schema}\n"
        f"Output contract: {spec.output_contract or '(a JSON string)'}"
        f"{examples}\n\n"
        "Write the tool now."
    )


def extract_source(text: str) -> str:
    """Pull the Python body out of an LLM response (fenced or bare)."""
    m = _CODE_FENCE.search(text or "")
    if m:
        return m.group(1).strip()
    return (text or "").strip()


class ToolSmith:
    """Drives the LLM that writes a synthesized tool's source."""

    async def synthesize(
        self,
        spec: ToolSpec,
        *,
        llm: Any,
        model_override: Optional[str] = None,
        task_type: str = "thinking",
    ) -> SynthesisResult:
        system = _build_system_prompt(spec)
        user = _build_user_prompt(spec)
        response = await llm.call_llm(
            task_type=task_type,
            system_prompt=system,
            user_prompt=user,
            temperature=0.1,
            max_tokens=1800,
            model_override=model_override,
        )
        raw = getattr(response, "output", "") or ""
        return SynthesisResult(
            source=extract_source(raw),
            raw_response=raw,
            model_used=getattr(response, "model_name", "") or (model_override or ""),
        )

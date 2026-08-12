"""tools.sandbox.synthesized_tool — runtime wrapper for a synthesized DRAFT tool.

A synthesized tool's source is **never** imported in-process (`06` §2.2). When a
DRAFT tool is invoked at runtime, this wrapper replays the call through the same
sandbox harness used for testing: the source executes only inside the per-tenant
container (`02`), and only its stdout result crosses back. The wrapper carries
``status = DRAFT`` so the registry visibility gate keeps it opt-in + tenant-only.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from src.ai.schemas.tools import ToolExample, ToolSpec
from src.ai.tools.base import Tool, ToolStatus


class SandboxedSynthesizedTool(Tool):
    """Wraps synthesized source so every call runs in the sandbox, not in-process."""

    status = ToolStatus.DRAFT

    def __init__(self, spec: ToolSpec, source: str) -> None:
        self.name = spec.name
        self.description = spec.description
        self._spec = spec
        self._source = source

    async def run(self, input_data: str) -> str:
        return json.dumps({
            "error": "synthesized tools require execution context (sandbox). Use run_with_context().",
        })

    async def run_with_context(
        self, input_data: str, context: Optional[dict[str, Any]] = None,
    ) -> str:
        from src.ai.meta.tool_sandbox_tester import ToolSandboxTester

        call_spec = self._spec.model_copy(update={"examples": [ToolExample(input=input_data)]})
        report = await ToolSandboxTester().run_examples(self._source, call_spec, context or {})
        if report.error:
            return json.dumps({"error": report.error})
        out = report.outcomes[0]
        if not out.passed and not out.output:
            return json.dumps({"error": out.detail or "sandbox execution failed"})
        return out.output


__all__ = ["SandboxedSynthesizedTool"]

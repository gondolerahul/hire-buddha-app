"""tools.meta.tool_synthesis — the gated meta-tool that synthesizes a new tool.

The single entry point an agent uses to request a brand-new tool (`06` §2). It
is the most dangerous capability on the platform, so it is hard-gated:

  1. **Meta-Agent only** — the caller must carry ``__is_meta_agent__`` in its
     execution context (the registry visibility layer makes the tool itself
     opt-in via ``tools.experimental.tool_synthesis``).
  2. **Kill switch** — ``meta_agent.tool_synthesis_enabled`` (default OFF).
  3. **Container-only execution** — the synthesized source is exercised solely
     through the sandbox (`02`); it never runs in-process.
  4. **DRAFT registration only** — the result enters the registry as DRAFT /
     trust=low, opt-in + tenant-scoped, until a human promotes it.

Input (JSON) is a :class:`ToolSpec` payload. Output is the full
:class:`SynthesisReport` so the verdict at every stage is auditable.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

from src.ai.tools.base import Tool, ToolStatus

logger = logging.getLogger(__name__)

__all__ = ["ToolSynthesisTool"]


class ToolSynthesisTool(Tool):
    name = "tool_synthesis"
    status = ToolStatus.EXPERIMENTAL
    description = (
        "META-AGENT ONLY. Synthesize a brand-new tool from a ToolSpec: an LLM "
        "writes a Tool subclass, which is statically validated, sandbox-tested "
        "against its examples, and red-teamed before being registered as a DRAFT "
        "(trust=low, opt-in, tenant-only) for human promotion. Input JSON is a "
        "ToolSpec {name, description, input_schema, output_contract, examples[], "
        "allowed_imports[], network_policy, est_cost_usd}."
    )

    async def run(self, input_data: str) -> str:
        return json.dumps({"error": "tool_synthesis requires execution context. Use run_with_context()."})

    async def run_with_context(
        self, input_data: str, context: Optional[dict[str, Any]] = None,
    ) -> str:
        from src.ai.core.feature_flags import FeatureFlags
        from src.ai.schemas.tools import ToolSpec

        context = context or {}
        company_id = context.get("company_id")
        if not company_id:
            return json.dumps({"error": "Missing company_id in execution context"})

        if not context.get("__is_meta_agent__", False):
            return json.dumps({
                "error": "tool_synthesis is restricted to the Meta-Agent.",
                "gate": "is_meta_agent",
            })

        company_uuid = UUID(str(company_id))
        flags = context.get("feature_flags") or FeatureFlags()
        try:
            enabled = await flags.is_on("meta_agent.tool_synthesis_enabled", company_id=company_uuid)
        except Exception:  # noqa: BLE001
            enabled = False
        if not enabled:
            return json.dumps({
                "error": "tool synthesis is disabled (meta_agent.tool_synthesis_enabled=off).",
                "gate": "kill_switch",
            })

        try:
            params = json.loads(input_data) if isinstance(input_data, str) else input_data
            spec = ToolSpec(**params)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"Invalid ToolSpec: {type(exc).__name__}: {exc}"})

        from src.ai.llm.router import LLMRouter
        from src.ai.meta.tool_synthesis_pipeline import ToolSynthesisPipeline
        from src.common.database import AsyncSessionLocal

        user_id = context.get("user_id")
        created_by = UUID(str(user_id)) if user_id else None
        try:
            async with AsyncSessionLocal() as db:
                llm = LLMRouter(db=db, company_id=company_uuid)
                pipeline = ToolSynthesisPipeline()
                report = await pipeline.run(
                    spec,
                    llm=llm,
                    context=context,
                    db=db,
                    company_id=company_uuid,
                    created_by=created_by,
                )
            return json.dumps(report.to_dict())
        except Exception as exc:  # noqa: BLE001
            logger.exception("tool_synthesis failed")
            return json.dumps({"error": f"tool_synthesis failed: {type(exc).__name__}: {exc}"})

"""
meta_platform_introspect — Query platform schema for the Meta-Agent.

Provides the Meta-Agent with comprehensive understanding of the platform's
capability surface: available tools, model endpoints, step types,
constraints, and composition rules.

Supports two modes:
  - "full"    — Complete platform schema (at conversation start)
  - "refresh" — Lightweight refresh of mutable sections (tools, models)

Input (JSON):
  { "mode": "full" }
  OR
  { "mode": "refresh" }
  OR
  { "section": "tools" }  — Query a specific section only

Output: Platform schema JSON
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.base import Tool

logger = logging.getLogger(__name__)


class MetaPlatformIntrospectTool(Tool):
    name = "meta_platform_introspect"
    description = (
        "Query the platform's capability schema: available tools, models, step types, "
        "constraints, and composition rules. Use mode='full' for complete schema, "
        "mode='refresh' for updated tools/models only, or 'section' to query a specific part."
    )

    async def run(self, input_data: str) -> str:
        return json.dumps({"error": "meta_platform_introspect requires execution context."})

    async def run_with_context(self, input_data: str, context: Optional[Dict[str, Any]] = None) -> str:
        try:
            params = json.loads(input_data) if isinstance(input_data, str) else input_data
        except json.JSONDecodeError:
            params = {"mode": "full"}

        context = context or {}
        company_id = context.get("company_id")

        mode = params.get("mode", "full")
        section = params.get("section")

        try:
            from uuid import UUID
            from src.ai.meta.platform_schema_compiler import PlatformSchemaCompiler
            from src.common.database import AsyncSessionLocal

            company_uuid = UUID(str(company_id)) if company_id else None

            # Use isolated session to avoid poisoning caller's session
            async with AsyncSessionLocal() as isolated_db:
                compiler = PlatformSchemaCompiler(db=isolated_db, company_id=company_uuid)

                if mode == "refresh":
                    schema = await compiler.refresh()
                else:
                    schema = await compiler.compile(include_tenant_tools=True)

            # If a specific section is requested, extract it
            if section and section in schema:
                return json.dumps({
                    "section": section,
                    "data": schema[section],
                    "schema_version": schema.get("schema_version"),
                }, default=str)

            # For full mode, return a condensed version to fit context
            if mode == "full":
                # Condense tool list to just names + descriptions (not full schemas)
                condensed = dict(schema)
                condensed["tools"] = [
                    {"tool_id": t["tool_id"], "description": t["description"][:200],
                     "category": t.get("category", "utility")}
                    for t in schema.get("tools", [])
                ]
                return json.dumps(condensed, default=str)

            return json.dumps(schema, default=str)

        except Exception as e:
            logger.error(f"meta_platform_introspect failed: {e}")
            return json.dumps({"error": str(e)})

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["full", "refresh"],
                        "description": "full = complete schema, refresh = mutable sections only",
                    },
                    "section": {
                        "type": "string",
                        "description": "Optional specific section to query (e.g., 'tools', 'constraints')",
                    },
                },
            },
        }

"""
meta_registry_search — Search existing agent registry for reuse/adaptation.

Used by the Meta-Agent's RegistryCurator sub-agent to find existing
HierarchicalEntity definitions that match a user's requirement.

Input (JSON):
  {
    "intent": "research competitors and generate a report",
    "required_tools": ["web_search", "scraper_tool", "pdf_generator"],
    "preferred_type": "PROCESS",
    "complexity_class": "MEDIUM",
    "tags": ["research"]
  }

Output (JSON):
  {
    "decision": "ADAPT",
    "candidates": [...],
    "rationale": "Agent 'Deep Research' is a near-match..."
  }
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.base import Tool

logger = logging.getLogger(__name__)


class MetaRegistrySearchTool(Tool):
    name = "meta_registry_search"
    description = (
        "Search the agent registry for existing agents that match a requirement. "
        "Input: JSON with 'intent' (required description), 'required_tools' (list of tool IDs), "
        "'preferred_type' (ACTION|SKILL|AGENT|PROCESS), 'complexity_class' (LOW|MEDIUM|HIGH), "
        "and 'tags' (list). Returns ranked candidates with match type "
        "(REUSE/ADAPT/COMPOSE/CREATE) and rationale."
    )

    async def run(self, input_data: str) -> str:
        return json.dumps({
            "error": "meta_registry_search requires execution context. Use run_with_context()."
        })

    async def run_with_context(self, input_data: str, context: Optional[Dict[str, Any]] = None) -> str:
        try:
            params = json.loads(input_data) if isinstance(input_data, str) else input_data
        except (json.JSONDecodeError, TypeError):
            # Graceful fallback: raw text input → wrap as intent query
            params = {"intent": str(input_data)[:2000]}

        context = context or {}
        company_id = context.get("company_id")

        if not company_id:
            return json.dumps({"error": "Missing company_id in execution context"})

        try:
            from uuid import UUID
            from src.ai.meta.registry_search_service import RegistrySearchService, SearchRequest
            from src.common.database import AsyncSessionLocal

            company_uuid = UUID(str(company_id)) if not isinstance(company_id, UUID) else company_id

            request = SearchRequest(
                intent=params.get("intent", ""),
                required_tools=params.get("required_tools", []),
                preferred_type=params.get("preferred_type"),
                io_schema=params.get("io_schema"),
                complexity_class=params.get("complexity_class", "MEDIUM"),
                tags=params.get("tags", []),
            )

            # Use isolated session to avoid poisoning caller's session on SQL errors
            async with AsyncSessionLocal() as isolated_db:
                service = RegistrySearchService(db=isolated_db, company_id=company_uuid)
                result = await service.recommend(request)

            return json.dumps(result, default=str)

        except Exception as e:
            logger.error(f"meta_registry_search failed: {e}")
            return json.dumps({"error": str(e), "decision": "CREATE", "candidates": []})

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "Natural language description of the desired agent capability",
                    },
                    "required_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tool IDs the agent must have access to",
                    },
                    "preferred_type": {
                        "type": "string",
                        "enum": ["ACTION", "SKILL", "AGENT", "PROCESS"],
                        "description": "Preferred entity type",
                    },
                    "complexity_class": {
                        "type": "string",
                        "enum": ["LOW", "MEDIUM", "HIGH"],
                        "description": "Expected complexity of the agent",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags to filter candidates",
                    },
                },
                "required": ["intent"],
            },
        }

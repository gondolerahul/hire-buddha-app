"""
meta_entity_creator — Creates or versions HierarchicalEntity definitions.

Used by the Meta-Agent's AgentArchitect sub-agent to persist validated
entity definitions to the database.

Supports two modes:
  1. CREATE — New entity from scratch
  2. VERSION — Bump version of existing entity (clone + modify)

Input (JSON):
  {
    "mode": "CREATE",
    "entity_payload": { ...HierarchicalEntityCreate fields... }
  }
  OR
  {
    "mode": "VERSION",
    "source_entity_id": "uuid",
    "modifications": { ...HierarchicalEntityUpdate fields... },
    "version_bump": "minor"  // "major" | "minor" | "patch"
  }

Output (JSON):
  { "success": true, "entity_id": "uuid", "name": "...", "version": "..." }
"""
import json
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from src.ai.tools.base import Tool

logger = logging.getLogger(__name__)


def _bump_version(current: str, bump_type: str = "minor") -> str:
    """Bump a semver string."""
    try:
        parts = current.split(".")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        return "1.1.0"

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


class MetaEntityCreatorTool(Tool):
    name = "meta_entity_creator"
    description = (
        "Create a new agent entity or version an existing one. "
        "For CREATE mode: provide 'entity_payload' with full HierarchicalEntityCreate fields. "
        "For VERSION mode: provide 'source_entity_id', 'modifications', and 'version_bump'. "
        "Returns the created/versioned entity ID."
    )

    async def run(self, input_data: str) -> str:
        return json.dumps({"error": "meta_entity_creator requires execution context."})

    async def run_with_context(self, input_data: str, context: Optional[Dict[str, Any]] = None) -> str:
        import re as _re
        try:
            params = json.loads(input_data) if isinstance(input_data, str) else input_data
        except (json.JSONDecodeError, TypeError):
            # Try extracting JSON from markdown code fences (```json ... ```)
            _match = _re.search(r'```(?:json)?\s*(\{.*?\})\s*```', str(input_data), _re.DOTALL)
            if _match:
                try:
                    params = json.loads(_match.group(1))
                except json.JSONDecodeError:
                    return json.dumps({"success": False, "error": f"Invalid JSON: {input_data[:200]}"})
            else:
                return json.dumps({"success": False, "error": f"Invalid JSON: {input_data[:200]}"})

        context = context or {}
        company_id = context.get("company_id")
        user_id = context.get("user_id")

        if not company_id:
            return json.dumps({"success": False, "error": "Missing company_id"})

        mode = params.get("mode", "CREATE").upper()

        # ── Tier 3 Runtime Creation Governance ─────────────────────────
        # When an entity creates children at runtime (Tier 3 self-modification),
        # enforce additional governance beyond the dedicated Meta-Agent.
        is_meta_agent = context.get("__is_meta_agent__", False)
        if not is_meta_agent:
            # Check runtime creation count limit
            runtime_count_key = f"__meta_runtime_creations_{company_id}__"
            current_count = context.get(runtime_count_key, 0)
            max_creations = context.get("__meta_max_runtime_creations__", 3)
            if current_count >= max_creations:
                return json.dumps({
                    "success": False,
                    "error": (
                        f"Runtime entity creation limit reached: {current_count}/{max_creations} "
                        f"entities created in this execution. This limit prevents unbounded "
                        f"agent proliferation during a single run."
                    ),
                    "gate": "runtime_creation_limit",
                })
            # Increment counter in context
            context[runtime_count_key] = current_count + 1

            logger.info(
                f"Tier 3: Runtime entity creation by non-Meta-Agent "
                f"(count={current_count + 1}/{max_creations}, mode={mode})"
            )

            # Tag the payload with runtime provenance
            if mode == "CREATE":
                payload = params.get("entity_payload", {})
                metadata = payload.get("metadata_extensions", {}) or {}
                metadata["runtime_created"] = True
                metadata["created_by_entity"] = context.get("__entity_name__", "unknown")
                payload["metadata_extensions"] = metadata
                params["entity_payload"] = payload
        # ───────────────────────────────────────────────────────────────

        try:
            from src.common.database import AsyncSessionLocal

            company_uuid = UUID(str(company_id))
            user_uuid = UUID(str(user_id)) if user_id else None

            # Use isolated session to avoid poisoning caller's session on SQL errors
            async with AsyncSessionLocal() as db:
                if mode == "CREATE":
                    result = await self._create_entity(params, db, company_uuid, user_uuid)
                elif mode == "VERSION":
                    result = await self._version_entity(params, db, company_uuid, user_uuid)
                else:
                    return json.dumps({"success": False, "error": f"Unknown mode: {mode}"})
                await db.commit()
            return result

        except Exception as e:
            logger.error(f"meta_entity_creator failed: {e}")
            return json.dumps({"success": False, "error": str(e)})

    async def _create_entity(self, params: Dict, db, company_id: UUID,
                              user_id: Optional[UUID]) -> str:
        """Create a new entity from the provided payload.

        V2: Enforces anti-sprawl hard gates before creation:
          1. Daily creation limit check
          2. Semantic deduplication check
        """
        from src.ai.schemas import HierarchicalEntityCreate
        from src.ai.service import AIService
        from src.ai.meta.anti_sprawl import AntiSprawlGuard

        payload = params.get("entity_payload", {})

        # --- Anti-Sprawl Hard Gate 1: Daily creation limit ---
        anti_sprawl = AntiSprawlGuard(db, company_id)
        creation_check = await anti_sprawl.check_creation_allowed(user_id)
        if not creation_check["allowed"]:
            return json.dumps({
                "success": False,
                "error": creation_check["message"],
                "gate": "daily_limit",
            })

        # --- Anti-Sprawl Hard Gate 2: Semantic deduplication ---
        description = payload.get("description", "")
        tools = []
        caps = payload.get("capabilities", {})
        if isinstance(caps, dict):
            tools = [
                t.get("tool_id", "") for t in caps.get("tools", [])
                if isinstance(t, dict) and t.get("tool_id")
            ]
        preferred_type = payload.get("type")

        dup_check = await anti_sprawl.check_semantic_duplicate(
            description=description,
            required_tools=tools,
            preferred_type=preferred_type,
        )
        if dup_check.get("is_duplicate"):
            return json.dumps({
                "success": False,
                "error": dup_check["message"],
                "gate": "semantic_duplicate",
                "existing_entity_id": dup_check.get("existing_entity_id"),
                "similarity_score": dup_check.get("similarity_score"),
            })

        # Validate via Pydantic first
        try:
            entity_in = HierarchicalEntityCreate.model_validate(payload)
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Schema validation failed: {str(e)}",
            })

        service = AIService(db)
        entity = await service.create_entity(entity_in, company_id, user_id)

        logger.info(f"Meta-Agent created entity: {entity.name} (id={entity.id})")

        return json.dumps({
            "success": True,
            "entity_id": str(entity.id),
            "name": entity.name,
            "type": entity.type if isinstance(entity.type, str) else entity.type.value,
            "version": entity.version,
        })

    async def _version_entity(self, params: Dict, db, company_id: UUID,
                               user_id: Optional[UUID]) -> str:
        """Create a new version of an existing entity (clone + modify)."""
        from src.ai.models import HierarchicalEntity
        from src.ai.schemas import HierarchicalEntityCreate
        from src.ai.service import AIService
        from src.ai.entity_clone_helpers import clone_entity_fields
        from sqlalchemy import select

        source_id = params.get("source_entity_id")
        modifications = params.get("modifications", {})
        bump_type = params.get("version_bump", "minor")

        if not source_id:
            return json.dumps({"success": False, "error": "source_entity_id required for VERSION mode"})

        # Load source entity
        source_uuid = UUID(str(source_id))
        result = await db.execute(
            select(HierarchicalEntity).where(
                HierarchicalEntity.id == source_uuid,
            )
        )
        source = result.scalar_one_or_none()
        if not source:
            return json.dumps({"success": False, "error": f"Source entity {source_id} not found"})

        # Clone fields
        cloned = clone_entity_fields(source)

        # Apply modifications
        for key, value in modifications.items():
            if key in cloned:
                cloned[key] = value

        # Bump version
        cloned["version"] = _bump_version(source.version or "1.0.0", bump_type)

        # Set name to indicate it's a new version
        if "name" not in modifications:
            cloned["name"] = f"{source.name} (v{cloned['version']})"

        # Set template_source_id to track lineage
        cloned["template_source_id"] = str(source.id)

        # Create via Pydantic validation
        try:
            entity_in = HierarchicalEntityCreate.model_validate(cloned)
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Schema validation failed after modifications: {str(e)}",
            })

        service = AIService(db)
        entity = await service.create_entity(entity_in, company_id, user_id)

        logger.info(
            f"Meta-Agent versioned entity: {source.name} v{source.version} "
            f"→ {entity.name} v{entity.version} (id={entity.id})"
        )

        return json.dumps({
            "success": True,
            "entity_id": str(entity.id),
            "source_entity_id": str(source.id),
            "name": entity.name,
            "type": entity.type if isinstance(entity.type, str) else entity.type.value,
            "version": entity.version,
            "version_bump": bump_type,
        })

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["CREATE", "VERSION"],
                        "description": "CREATE for new entity, VERSION to bump existing",
                    },
                    "entity_payload": {
                        "type": "object",
                        "description": "Full entity definition for CREATE mode",
                    },
                    "source_entity_id": {
                        "type": "string",
                        "description": "Entity ID to version (VERSION mode)",
                    },
                    "modifications": {
                        "type": "object",
                        "description": "Fields to modify in the new version (VERSION mode)",
                    },
                    "version_bump": {
                        "type": "string",
                        "enum": ["major", "minor", "patch"],
                        "description": "Semver bump type (VERSION mode)",
                    },
                },
                "required": ["mode"],
            },
        }

"""
meta_schema_validator — Validates entity JSON against platform schemas.

Used by the Meta-Agent's AgentArchitect sub-agent to ensure generated
entity definitions are valid before creation.

Validates:
  1. Pydantic schema compliance (HierarchicalEntityCreate)
  2. Tool references exist in ToolRegistry
  3. Step type validity
  4. CHILD_ENTITY_INVOCATION target entity_ids exist
  5. Governance constraints are within platform limits

Input (JSON):
  { "entity_payload": { ...HierarchicalEntityCreate fields... } }

Output (JSON):
  { "valid": true/false, "errors": [...], "warnings": [...] }
"""
import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from src.ai.tools.base import Tool

logger = logging.getLogger(__name__)


class MetaSchemaValidatorTool(Tool):
    name = "meta_schema_validator"
    description = (
        "Validate an entity definition (HierarchicalEntityCreate payload) against "
        "platform schemas. Input: JSON with 'entity_payload' dict containing entity fields. "
        "Returns validation result with errors and warnings."
    )

    async def run(self, input_data: str) -> str:
        return json.dumps({"error": "meta_schema_validator requires execution context."})

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
                    return json.dumps({"valid": False, "errors": [f"Invalid JSON: {input_data[:200]}"]})
            else:
                return json.dumps({"valid": False, "errors": [f"Invalid JSON: {input_data[:200]}"]})

        context = context or {}
        company_id = context.get("company_id")

        payload = params.get("entity_payload", params)
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Pydantic schema validation
        try:
            from src.ai.schemas import HierarchicalEntityCreate
            entity = HierarchicalEntityCreate.model_validate(payload)
        except Exception as e:
            errors.append(f"Schema validation failed: {str(e)}")
            return json.dumps({"valid": False, "errors": errors, "warnings": warnings})

        # 2. Tool references exist in registry
        self._validate_tools(payload, errors, warnings, company_id)

        # 3. Step type validity
        self._validate_steps(payload, errors, warnings)

        # 4. CHILD_ENTITY_INVOCATION references (uses isolated session)
        try:
            from src.common.database import AsyncSessionLocal
            async with AsyncSessionLocal() as isolated_db:
                await self._validate_child_refs(payload, errors, warnings, isolated_db, company_id)
        except Exception as e:
            warnings.append(f"Child ref validation skipped: {e}")

        # 5. Governance constraints
        self._validate_governance(payload, errors, warnings)

        # 6. Meta-Agent recursion guard
        self._validate_no_meta_recursion(payload, errors, warnings)

        valid = len(errors) == 0
        return json.dumps({
            "valid": valid,
            "errors": errors,
            "warnings": warnings,
        })

    def _validate_tools(self, payload: Dict, errors: List, warnings: List,
                        company_id=None):
        """Check that all referenced tools exist in ToolRegistry."""
        from src.ai.tools.base import ToolRegistry

        caps = payload.get("capabilities", {})
        if not caps or not isinstance(caps, dict):
            return

        tools = caps.get("tools", [])
        for tool_ref in tools:
            tool_id = tool_ref.get("tool_id", "") if isinstance(tool_ref, dict) else str(tool_ref)
            if not tool_id:
                continue

            cid = None
            if company_id:
                try:
                    cid = UUID(str(company_id))
                except (ValueError, AttributeError):
                    pass

            if not ToolRegistry.get_tool(tool_id, company_id=cid):
                warnings.append(
                    f"Tool '{tool_id}' not found in registry. "
                    f"It may be a tenant-specific or future tool."
                )

    def _validate_steps(self, payload: Dict, errors: List, warnings: List):
        """Validate step types and structure."""
        from src.ai.schemas import StepType

        valid_types = {e.value for e in StepType}

        planning = payload.get("planning", {})
        if not planning or not isinstance(planning, dict):
            return

        static_plan = planning.get("static_plan", {})
        if not static_plan or not isinstance(static_plan, dict):
            return

        steps = static_plan.get("steps", [])
        step_ids = set()
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"Step {i}: must be a dict, got {type(step).__name__}")
                continue

            step_type = step.get("type")
            if step_type and step_type not in valid_types:
                errors.append(
                    f"Step {i} ('{step.get('name', '?')}'): invalid type '{step_type}'. "
                    f"Valid types: {sorted(valid_types)}"
                )

            # Check for duplicate step_ids
            sid = step.get("step_id")
            if sid:
                if sid in step_ids:
                    errors.append(f"Step {i}: duplicate step_id '{sid}'")
                step_ids.add(sid)

            # TOOL_CALL must have target.tool_id
            if step_type == "TOOL_CALL":
                target = step.get("target", {})
                if not target or not target.get("tool_id"):
                    errors.append(
                        f"Step {i} ('{step.get('name', '?')}'): TOOL_CALL requires target.tool_id"
                    )

            # CHILD_ENTITY_INVOCATION must have target.entity_id
            if step_type == "CHILD_ENTITY_INVOCATION":
                target = step.get("target", {})
                if not target or not target.get("entity_id"):
                    errors.append(
                        f"Step {i} ('{step.get('name', '?')}'): "
                        f"CHILD_ENTITY_INVOCATION requires target.entity_id"
                    )

            # Validate input_dependencies reference existing steps
            target = step.get("target", {})
            if target and isinstance(target, dict):
                deps = target.get("input_dependencies", [])
                for dep in deps:
                    if dep not in step_ids and dep not in {
                        s.get("step_id") for s in steps
                    }:
                        warnings.append(
                            f"Step {i}: input_dependency '{dep}' not found in earlier steps"
                        )

    async def _validate_child_refs(self, payload: Dict, errors: List,
                                    warnings: List, db=None, company_id=None):
        """Validate CHILD_ENTITY_INVOCATION entity_ids exist."""
        if not db or not company_id:
            return

        planning = payload.get("planning", {})
        if not planning or not isinstance(planning, dict):
            return

        static_plan = planning.get("static_plan", {})
        steps = static_plan.get("steps", []) if isinstance(static_plan, dict) else []

        for step in steps:
            if not isinstance(step, dict):
                continue
            if step.get("type") != "CHILD_ENTITY_INVOCATION":
                continue

            target = step.get("target", {})
            entity_id = target.get("entity_id") if isinstance(target, dict) else None
            if not entity_id:
                continue

            try:
                from src.ai.models import HierarchicalEntity
                from sqlalchemy import select

                eid = UUID(str(entity_id))
                cid = UUID(str(company_id))
                result = await db.execute(
                    select(HierarchicalEntity.id).where(
                        HierarchicalEntity.id == eid,
                        HierarchicalEntity.company_id == cid,
                        HierarchicalEntity.status != "DELETED",
                    )
                )
                if not result.scalar_one_or_none():
                    errors.append(
                        f"Step '{step.get('name', '?')}': entity_id {entity_id} "
                        f"not found in company scope"
                    )
            except (ValueError, AttributeError):
                errors.append(
                    f"Step '{step.get('name', '?')}': invalid entity_id format '{entity_id}'"
                )

    def _validate_governance(self, payload: Dict, errors: List, warnings: List):
        """Validate governance constraints are within platform limits."""
        governance = payload.get("governance", {})
        if not governance or not isinstance(governance, dict):
            return

        max_depth = governance.get("max_recursion_depth", 5)
        if max_depth > 10:
            warnings.append(
                f"max_recursion_depth={max_depth} is very high. "
                f"Recommended max: 5. Risk of exponential execution cost."
            )

        timeout = governance.get("timeout_ms", 60000)
        if timeout > 3600000:  # 1 hour
            warnings.append(
                f"timeout_ms={timeout} exceeds 1 hour. "
                f"Consider using CORTEX mode for long-running tasks."
            )

    def _validate_no_meta_recursion(self, payload: Dict, errors: List,
                                     warnings: List):
        """Prevent Meta-Agent from creating entities that reference itself."""
        tags = payload.get("tags", [])
        if isinstance(tags, list) and "meta_agent" in tags:
            errors.append(
                "Cannot create an entity with 'meta_agent' tag. "
                "This would create a recursive Meta-Agent which is forbidden."
            )

        # Check if any step references a meta_ tool
        planning = payload.get("planning", {})
        static_plan = planning.get("static_plan", {}) if isinstance(planning, dict) else {}
        steps = static_plan.get("steps", []) if isinstance(static_plan, dict) else []

        for step in steps:
            if not isinstance(step, dict):
                continue
            target = step.get("target", {})
            if isinstance(target, dict) and target.get("tool_id", "").startswith("meta_"):
                errors.append(
                    f"Step '{step.get('name', '?')}' references meta-tool "
                    f"'{target['tool_id']}'. Generated agents cannot use meta-tools."
                )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_payload": {
                        "type": "object",
                        "description": "Complete HierarchicalEntityCreate payload to validate",
                    },
                },
                "required": ["entity_payload"],
            },
        }

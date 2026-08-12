"""
meta_entity_executor — Trigger test executions of generated agents.

Used by the Meta-Agent's ExecutionValidator sub-agent to dry-run
newly created agents with test input and inspect results.

Safety: Test executions are capped at $1.00 max cost to prevent
runaway billing from generated agents with flawed configurations.

Input (JSON):
  {
    "entity_id": "uuid",
    "test_input": {"instruction": "test query"},
    "max_cost_usd": 0.50
  }

Output (JSON):
  {
    "success": true,
    "run_id": "uuid",
    "status": "COMPLETED",
    "output_preview": "...",
    "cost_usd": 0.12,
    "execution_time_ms": 3400
  }
"""
import json
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from src.ai.tools.base import Tool

logger = logging.getLogger(__name__)

# Safety cap: Meta-Agent test executions are limited to this cost
META_TEST_MAX_COST_USD = 1.00


class MetaEntityExecutorTool(Tool):
    name = "meta_entity_executor"
    description = (
        "Trigger a test execution of a generated agent to validate it works. "
        "Input: JSON with 'entity_id' and 'test_input' dict. "
        "Optionally set 'max_cost_usd' (default: $0.50, max: $1.00). "
        "Returns execution status, output preview, cost, and timing."
    )

    async def run(self, input_data: str) -> str:
        return json.dumps({"error": "meta_entity_executor requires execution context."})

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

        entity_id = params.get("entity_id")
        test_input = params.get("test_input", {"instruction": "test"})
        max_cost = min(
            float(params.get("max_cost_usd", 0.50)),
            META_TEST_MAX_COST_USD,
        )

        if not entity_id:
            return json.dumps({"success": False, "error": "entity_id required"})

        try:
            from src.common.database import AsyncSessionLocal

            company_uuid = UUID(str(company_id))
            entity_uuid = UUID(str(entity_id))
            user_uuid = UUID(str(user_id)) if user_id else None

            # Use isolated session to avoid poisoning caller's session
            async with AsyncSessionLocal() as db:
                # Temporarily inject a cost cap into the entity's governance
                await self._inject_cost_cap(db, entity_uuid, max_cost)

                # Trigger execution
                from src.ai.schemas import ExecutionRunCreate
                from src.ai.service import AIService

                service = AIService(db)
                exec_create = ExecutionRunCreate(
                    entity_id=entity_uuid,
                    input_data=test_input,
                )

                run = await service.trigger_execution(exec_create, company_uuid, user_uuid)
                await db.commit()

                # Wait for completion (poll with timeout)
                result = await self._poll_execution(db, run.id, company_uuid, timeout_sec=120)

            return json.dumps(result, default=str)

        except Exception as e:
            logger.error(f"meta_entity_executor failed: {e}")
            return json.dumps({"success": False, "error": str(e)})

    async def _inject_cost_cap(self, db, entity_id: UUID, max_cost: float):
        """Temporarily set governance.max_cost_usd on the entity for safety."""
        from src.ai.models import HierarchicalEntity
        from sqlalchemy import select

        result = await db.execute(
            select(HierarchicalEntity).where(HierarchicalEntity.id == entity_id)
        )
        entity = result.scalar_one_or_none()
        if not entity:
            return

        governance = entity.governance or {}
        if not governance.get("max_cost_usd") or governance["max_cost_usd"] > max_cost:
            governance["max_cost_usd"] = max_cost
            entity.governance = {**governance}  # Trigger SQLAlchemy mutation detection
            await db.flush()

    async def _poll_execution(self, db, run_id: UUID, company_id: UUID,
                               timeout_sec: int = 120) -> Dict[str, Any]:
        """Poll for execution completion."""
        import asyncio
        from src.ai.models import ExecutionRun
        from sqlalchemy import select

        deadline = asyncio.get_event_loop().time() + timeout_sec

        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(2)

            result = await db.execute(
                select(ExecutionRun).where(
                    ExecutionRun.id == run_id,
                    ExecutionRun.company_id == company_id,
                )
            )
            run = result.scalar_one_or_none()
            if not run:
                return {"success": False, "error": f"Run {run_id} not found"}

            if run.status in ("COMPLETED", "FAILED", "PARTIAL_COMPLETE", "CANCELLED"):
                output = ""
                if run.result_data:
                    output = str(run.result_data)[:2000]

                return {
                    "success": run.status == "COMPLETED",
                    "run_id": str(run.id),
                    "status": run.status,
                    "output_preview": output,
                    "error_message": run.error_message if run.status == "FAILED" else None,
                    "cost_usd": float(run.total_cost_usd or 0),
                    "execution_time_ms": run.execution_time_ms,
                }

        return {
            "success": False,
            "run_id": str(run_id),
            "status": "TIMEOUT",
            "error": f"Execution did not complete within {timeout_sec}s",
        }

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "ID of the entity to test-execute",
                    },
                    "test_input": {
                        "type": "object",
                        "description": "Input data for the test execution",
                    },
                    "max_cost_usd": {
                        "type": "number",
                        "description": "Maximum cost cap for test execution (default: 0.50, max: 1.00)",
                    },
                },
                "required": ["entity_id"],
            },
        }

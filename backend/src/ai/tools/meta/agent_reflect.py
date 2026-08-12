"""``agent_reflect`` — structured-reflection meta-tool (Phase 12 `06` §3.1).

Lets an AGENT/PROCESS persist a structured reflection ("what did I learn / what
would I do differently?") so it survives the run and can be promoted into the
entity's IntelligenceTree. Per the §1 matrix, reflections are written as
*candidates*; Dreaming validates them against subsequent runs before promotion
to confirmed (so a single run can't poison the rule set).

Two writes, both best-effort and independent:
  1. run-scoped state — appended to ``context['__reflections__']`` so later
     steps in the same run can read it back;
  2. CORTEX — a ``finding`` node tagged ``status=candidate`` on the run's tree,
     which the Dreaming/Curator pipeline picks up.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from src.ai.tools.base import Tool

logger = logging.getLogger(__name__)

_VALID_KINDS = ("instruction", "strategy", "preference", "observation")


class AgentReflectTool(Tool):
    name = "agent_reflect"
    description = (
        "Persist a structured reflection about your own execution so it can be "
        "learned from. Input is a JSON object: {'learning': '<what you learned>', "
        "'kind': 'instruction'|'strategy'|'preference'|'observation', "
        "'confidence': 0..1}. The reflection is stored run-scoped and written as "
        "a CANDIDATE rule (validated by Dreaming before it influences future runs)."
    )

    def supports_context(self) -> bool:
        return True

    async def run(self, input_data: str) -> str:
        return await self.run_with_context(input_data, context=None)

    async def run_with_context(
        self, input_data: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        try:
            params = json.loads(input_data) if input_data else {}
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON input"})
        if not isinstance(params, dict):
            return json.dumps({"error": "Input must be a JSON object"})

        learning = (params.get("learning") or "").strip()
        if not learning:
            return json.dumps({"error": "agent_reflect requires a non-empty 'learning'"})
        kind = params.get("kind", "observation")
        if kind not in _VALID_KINDS:
            kind = "observation"
        try:
            confidence = float(params.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        reflection = {"learning": learning, "kind": kind, "confidence": confidence}

        # 1. run-scoped state (synchronous, never fails).
        persisted_run_scoped = False
        if isinstance(context, dict):
            bucket = context.setdefault("__reflections__", [])
            if isinstance(bucket, list):
                bucket.append(reflection)
                persisted_run_scoped = True

        # 2. CORTEX candidate node (best-effort, DB).
        persisted_candidate = await self._write_candidate(context, reflection)

        return json.dumps(
            {
                "reflected": True,
                "kind": kind,
                "confidence": confidence,
                "persisted_run_scoped": persisted_run_scoped,
                "persisted_candidate": persisted_candidate,
            }
        )

    async def _write_candidate(
        self, context: Optional[Dict[str, Any]], reflection: Dict[str, Any]
    ) -> bool:
        """Write the reflection as a candidate CORTEX finding on the run tree."""
        if not isinstance(context, dict):
            return False
        tree_id = context.get("cortex_tree_id") or context.get("__cortex_tree_id__")
        cursor_id = context.get("__cortex_cursor__")
        company_id = context.get("company_id")
        if not tree_id or not cursor_id or not company_id:
            return False
        try:
            from uuid import UUID

            from src.ai.memory.cortex_service import CortexService
            from src.common.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                cortex = CortexService(db, company_id=UUID(str(company_id)))
                # The node status must be a valid CortexNodeStatus; the
                # *candidate* lifecycle lives in metadata, which Dreaming reads
                # to decide what to validate/promote.
                await cortex.write(
                    parent_id=UUID(str(cursor_id)),
                    node_type="finding",
                    title=f"💡 Reflection ({reflection['kind']})",
                    content=reflection["learning"],
                    summary=reflection["learning"][:200],
                    status="active",
                    metadata_extra={
                        "reflection": True,
                        "candidate": True,
                        "lifecycle": "candidate",
                        "kind": reflection["kind"],
                        "confidence": reflection["confidence"],
                        "tree_id": str(tree_id),
                    },
                )
            return True
        except Exception as exc:  # noqa: BLE001 - candidate write is best-effort
            logger.debug("agent_reflect candidate write skipped: %s", exc)
            return False

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "learning": {
                        "type": "string",
                        "description": "What you learned or would do differently",
                    },
                    "kind": {
                        "type": "string",
                        "enum": list(_VALID_KINDS),
                        "description": "Reflection category",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence 0..1 that this should become a rule",
                    },
                },
                "required": ["learning"],
            },
        }

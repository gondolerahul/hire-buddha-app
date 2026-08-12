"""``agent_introspect`` — self-introspection meta-tool (Phase 12 `06` §3.1).

Lets any AGENT/PROCESS (per the §1 meta-cognition matrix) ask "what's my
budget? current viewport node? which intelligence rules apply? what has this
entity failed at recently?" without engine-side magic. It reads the signals the
AgentLoop already publishes into the materialised context
(``__agent_state__``, ``__intelligence__``/``__intelligence_rules__``,
``__cortex_cursor__``) and optionally augments with a best-effort recent-failure
query.

Read-only: it never mutates state. The companion ``agent_reflect`` writes.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from src.ai.tools.base import Tool

logger = logging.getLogger(__name__)


class AgentIntrospectTool(Tool):
    name = "agent_introspect"
    description = (
        "Introspect your own execution state: remaining budget and budget "
        "pressure, current iteration, open subgoals, the intelligence rules "
        "that apply to you, your current CORTEX viewport position, and "
        "(optionally) what this entity has failed at recently. Input is an "
        "optional JSON object: {'include_failures': true, 'failure_days': 7}."
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
            params = {}
        if not isinstance(params, dict):
            params = {}
        context = context or {}

        snapshot: Dict[str, Any] = {}

        astate = context.get("__agent_state__")
        if isinstance(astate, dict):
            snapshot["iteration"] = astate.get("iteration")
            snapshot["budget_pressure"] = astate.get("budget_pressure")
            snapshot["open_subgoals"] = astate.get("open_subgoals", [])

        # Execution-metadata mirror (legacy path) covers the same fields.
        exec_meta = context.get("__execution_metadata__")
        if isinstance(exec_meta, dict):
            snapshot.setdefault("iteration", exec_meta.get("iteration"))
            snapshot.setdefault("budget_pressure", exec_meta.get("budget_pressure"))
            snapshot.setdefault("open_subgoals", exec_meta.get("open_subgoals", []))

        snapshot["applicable_rules"] = self._extract_rules(context)
        snapshot["viewport_cursor"] = context.get("__cortex_cursor__")

        if params.get("include_failures"):
            days = int(params.get("failure_days", 7))
            snapshot["recent_failures"] = await self._recent_failures(context, days)

        return json.dumps(snapshot, default=str)

    @staticmethod
    def _extract_rules(context: Dict[str, Any]) -> List[Any]:
        """Pull applicable intelligence rules from whichever key the loop set."""
        for key in ("__intelligence__", "__intelligence_rules__"):
            rules = context.get(key)
            if rules:
                return rules if isinstance(rules, list) else [rules]
        return []

    async def _recent_failures(
        self, context: Dict[str, Any], days: int
    ) -> List[Dict[str, Any]]:
        """Best-effort: this entity's failed runs in the last ``days`` days."""
        entity_id = context.get("entity_id") or context.get("__entity_id__")
        if not entity_id:
            return []
        try:
            from datetime import datetime, timedelta
            from uuid import UUID

            from sqlalchemy import select

            from src.ai.orm.execution import ExecutionRun
            from src.common.database import AsyncSessionLocal

            # ExecutionRun.created_at is naive UTC (datetime.utcnow default).
            cutoff = datetime.utcnow() - timedelta(days=days)
            async with AsyncSessionLocal() as db:
                rows = await db.execute(
                    select(ExecutionRun.id, ExecutionRun.status, ExecutionRun.created_at)
                    .where(
                        ExecutionRun.entity_id == UUID(str(entity_id)),
                        ExecutionRun.status == "FAILED",
                        ExecutionRun.created_at >= cutoff,
                    )
                    .order_by(ExecutionRun.created_at.desc())
                    .limit(10)
                )
                return [
                    {"run_id": str(r[0]), "status": r[1], "at": str(r[2])}
                    for r in rows.all()
                ]
        except Exception as exc:  # noqa: BLE001 - introspection is best-effort
            logger.debug("agent_introspect failure-history lookup skipped: %s", exc)
            return []

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "include_failures": {
                        "type": "boolean",
                        "description": "Also return this entity's recent failed runs",
                    },
                    "failure_days": {
                        "type": "integer",
                        "description": "Look-back window for failures (default 7)",
                    },
                },
            },
        }

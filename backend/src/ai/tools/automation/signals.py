"""``emit_event`` (tech spec §7.10): an agent's signal to other agents' triggers."""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from src.ai.tools.automation.common import caller_of, commit, sessions
from src.ai.tools.base import Tool, ToolOutput, ToolParams
from src.automation import agent_actions, store
from src.automation.agent_actions import AgentActionError


class EmitEventParams(ToolParams):
    type: str = Field(..., description="The signal's type, starting with 'custom.', e.g. custom.lead.qualified.")
    data: Dict[str, Any] = Field(default_factory=dict, description="What the agents it wakes need to know.")
    subject: Optional[str] = Field(None, description="What it is about, e.g. 'lead:42'.")


class EmitEventTool(Tool):
    name = "emit_event"
    description = (
        "Send a signal (a custom event) that starts the agents whose triggers listen for it, e.g. "
        "custom.lead.qualified wakes the sales agent. Only custom.* types; it does not wait for them."
    )
    category = "automation"
    Params = EmitEventParams

    async def execute(self, params: EmitEventParams, ctx: Dict[str, Any]) -> ToolOutput:
        caller, refused = caller_of(ctx)
        if refused:
            return refused
        async with sessions(caller.company_id) as (db, control_db):
            try:
                event = await agent_actions.emit(db, control_db, caller.company_id, run_id=caller.run_id,
                                                 event_type=params.type, data=params.data, subject=params.subject)
            except AgentActionError as error:
                return ToolOutput.failed(str(error), code="refused")
            await commit(db, control_db)
            event_id, depth = event.id, event.chain_depth
        await store.nudge(caller.company_id, event_id)
        return ToolOutput(output={"event_id": str(event_id), "type": params.type, "chain_depth": depth,
                                  "note": "sent; the agents listening for it start on their own"})

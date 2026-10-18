"""``wait_for_event`` (tech spec §7.9, §7.10): a run waits for an event."""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from src.ai.tools.automation.common import caller_of, commit, sessions
from src.ai.tools.base import Tool, ToolOutput, ToolParams
from src.automation import waits
from src.automation.waits import WaitError


class WaitForEventParams(ToolParams):
    type: str = Field(..., description="The event to wait for, e.g. email.received, custom.lead.replied, or a "
                                       "prefix like whatsapp.message.*")
    match: Optional[Dict[str, Any]] = Field(None, description=(
        'Which event: a filter on its fields, e.g. {"path": "data.from", "op": "eq", "value": "priya@example.com"}; '
        'several with {"all": [...]}. Without it, the next event of the type answers.'))
    timeout: str = Field(..., description="How long to wait at most: weeks, days, hours, minutes, e.g. 48h, 3d.")


class WaitForEventTool(Tool):
    name = "wait_for_event"
    description = (
        "Wait for something to happen before going on, e.g. until the customer replies, up to 48 hours. "
        "After this call, finish your current step: the run pauses (using nothing while it waits) and "
        "continues when the event arrives — the event becomes this step's result — or when the timeout "
        "passes, with a notice that it timed out."
    )
    category = "automation"
    Params = WaitForEventParams

    async def execute(self, params: WaitForEventParams, ctx: Dict[str, Any]) -> ToolOutput:
        caller, refused = caller_of(ctx)
        if refused:
            return refused
        async with sessions(caller.company_id) as (db, control_db):
            try:
                wait = await waits.create(db, control_db, caller.company_id, run_id=caller.run_id,
                                          event_type=params.type, match=params.match, timeout=params.timeout)
            except WaitError as error:
                return ToolOutput.failed(str(error), code="refused")
            await commit(db, control_db)
            deadline = wait.deadline_at.isoformat() + "Z"
            return ToolOutput(output={
                "wait_id": str(wait.id), "waiting_for": wait.event_type, "until": deadline,
                "note": "Waiting. End this step now; the run continues when the event arrives or at the deadline.",
            })

"""``schedule_agent``, ``cancel_schedule``, ``list_schedules`` (tech spec §7.10)."""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import Field

from src.ai.tools.automation.common import caller_of, commit, sessions
from src.ai.tools.base import Tool, ToolOutput, ToolParams
from src.automation import agent_actions
from src.automation.agent_actions import AgentActionError


class ScheduleAgentParams(ToolParams):
    at: Optional[str] = Field(None, description=(
        "Run once at this time, ISO-8601, e.g. 2026-10-21T15:00 (the business's local time unless an "
        "offset is given). Give exactly one of at, after, cron."))
    after: Optional[str] = Field(None, description="Run once after this long: weeks, days, hours, minutes, "
                                                   "e.g. 3d, 2h30m, 1w.")
    cron: Optional[str] = Field(None, description="Repeat on this five-field cron schedule, e.g. '0 9 * * 1-5' "
                                                  "for weekdays at 09:00.")
    timezone: Optional[str] = Field(None, description="IANA time zone of the cron schedule; default: the "
                                                      "business's.")
    agent: Optional[str] = Field(None, description="The agent to run (its id or exact name); default: yourself.")
    input: Optional[str] = Field(None, description="What the scheduled run is asked to do, with everything it "
                                                   "needs to know: it does not see this conversation.")
    name: Optional[str] = Field(None, description="A short name the owner sees, e.g. 'Follow up with Priya'.")
    until: Optional[str] = Field(None, description="A repeating schedule stops after this ISO-8601 time.")
    max_runs: Optional[int] = Field(None, ge=1, description="A repeating schedule stops after this many runs.")


class ScheduleAgentTool(Tool):
    name = "schedule_agent"
    description = (
        "Schedule work for later: run yourself (or an agent you may schedule) once at a time, once after a "
        "delay, or repeatedly on a cron schedule, with an input. Use it for follow-ups and reminders. "
        "Nothing runs now; the owner sees the schedule as made by you and can stop it. Returns the "
        "schedule id and its next run time."
    )
    category = "automation"
    Params = ScheduleAgentParams

    async def execute(self, params: ScheduleAgentParams, ctx: Dict[str, Any]) -> ToolOutput:
        caller, refused = caller_of(ctx)
        if refused:
            return refused
        given = {k: v for k, v in (("at", params.at), ("in", params.after), ("cron", params.cron)) if v}
        if len(given) != 1:
            return ToolOutput.failed("give exactly one of at, after or cron", code="invalid_arguments")
        when: Dict[str, Any] = dict(given)
        if params.cron and params.timezone:
            when["timezone"] = params.timezone
        async with sessions(caller.company_id) as (db, control_db):
            try:
                trigger = await agent_actions.schedule(
                    db, control_db, caller.company_id, caller_id=caller.entity_id, run_id=caller.run_id,
                    agent=params.agent, when=when, input=params.input, name=params.name, until=params.until,
                    max_runs=params.max_runs)
            except AgentActionError as error:
                return ToolOutput.failed(str(error), code="refused")
            await commit(db, control_db)
            return ToolOutput(output=agent_actions.describe(trigger))


class CancelScheduleParams(ToolParams):
    schedule_id: str = Field(..., description="The id schedule_agent or list_schedules gave.")


class CancelScheduleTool(Tool):
    name = "cancel_schedule"
    description = ("Cancel a schedule you (or your process) made, e.g. a follow-up that is no longer needed. "
                   "It stops running; the owner still sees what it did.")
    category = "automation"
    Params = CancelScheduleParams

    async def execute(self, params: CancelScheduleParams, ctx: Dict[str, Any]) -> ToolOutput:
        caller, refused = caller_of(ctx)
        if refused:
            return refused
        async with sessions(caller.company_id) as (db, control_db):
            try:
                trigger = await agent_actions.cancel(db, control_db, caller.company_id, caller_id=caller.entity_id,
                                                     trigger_id=params.schedule_id)
            except AgentActionError as error:
                return ToolOutput.failed(str(error), code="refused")
            await commit(db, control_db)
            return ToolOutput(output=agent_actions.describe(trigger))


class ListSchedulesParams(ToolParams):
    scope: Literal["mine", "process", "runs_me"] = Field(
        "mine", description="mine: schedules you made; process: made by any agent of your process; "
                            "runs_me: every schedule or trigger that runs you.")


class ListSchedulesTool(Tool):
    name = "list_schedules"
    description = "List schedules: the ones you made, your process's, or the ones that run you; with their next run."
    category = "automation"
    Params = ListSchedulesParams

    async def execute(self, params: ListSchedulesParams, ctx: Dict[str, Any]) -> ToolOutput:
        caller, refused = caller_of(ctx)
        if refused:
            return refused
        async with sessions(caller.company_id) as (db, _control_db):
            try:
                rows = await agent_actions.list_for(db, caller.company_id, caller_id=caller.entity_id,
                                                    scope=params.scope)
            except AgentActionError as error:
                return ToolOutput.failed(str(error), code="refused")
            return ToolOutput(output={"schedules": [agent_actions.describe(t) for t in rows]})

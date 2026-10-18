"""Automation tools (Phase 14 WS3, tech spec §7.10): an agent schedules work,
cancels and lists its schedules, sends signals that wake other agents'
triggers, and waits for an event. The logic is ``src.automation.agent_actions``
and ``src.automation.waits``; these classes are the tool contract around it."""
from src.ai.tools.automation.scheduling import CancelScheduleTool, ListSchedulesTool, ScheduleAgentTool
from src.ai.tools.automation.signals import EmitEventTool
from src.ai.tools.automation.waiting import WaitForEventTool

__all__ = ["ScheduleAgentTool", "CancelScheduleTool", "ListSchedulesTool", "EmitEventTool", "WaitForEventTool"]

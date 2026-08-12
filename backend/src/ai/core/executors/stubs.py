"""
Stub executors — Dialog / ToolBurst / Skill.

These are reserved for later Tracks:
  * DialogExecutor       — Track 5 (Meta-Agent Dialog / multi-role chat)
  * ToolBurstExecutor    — Track 7 / 8 (planner-driven tool bursts)
  * SkillExecutor        — Track 5 (SkillLibrary playback)

They are registered so ``registered_executor_names()`` covers all
seven, but the Strategist NEVER picks them in Track 2. If the
registry mistakenly hands one back, ``execute`` raises immediately
so the failure is loud rather than silently mis-billing.
"""
from __future__ import annotations

from typing import Any

from src.ai.core.agent_state import AgentState, ExecutorName
from src.ai.core.executors.base import ActionResult, register_executor
from src.ai.core.strategist import Move

__all__ = ["DialogExecutor", "ToolBurstExecutor", "SkillExecutor"]


class _StubMixin:
    track: str

    async def execute(
        self,
        move: Move,                 # noqa: ARG002
        state: AgentState,          # noqa: ARG002
        db: Any,                    # noqa: ARG002
    ) -> ActionResult:
        raise NotImplementedError(
            f"{self.__class__.__name__} is a Track 2 stub; "
            f"implementation lands in {self.track}."
        )


class DialogExecutor(_StubMixin):
    name: ExecutorName = "Dialog"
    track = "Track 5"


class ToolBurstExecutor(_StubMixin):
    name: ExecutorName = "ToolBurst"
    track = "Track 7/8"


class SkillExecutor(_StubMixin):
    name: ExecutorName = "Skill"
    track = "Track 5"


register_executor(DialogExecutor())
register_executor(ToolBurstExecutor())
register_executor(SkillExecutor())

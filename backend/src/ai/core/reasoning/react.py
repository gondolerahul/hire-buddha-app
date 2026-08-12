"""REACT reasoning — thin adapter; full body stays in llm/router (Track 2)."""
from __future__ import annotations

from typing import Any, Optional, cast

from src.ai.core.reasoning.base import register_reasoning
from src.ai.schemas.enums import ReasoningMode


class ReactReasoning:
    name = ReasoningMode.REACT

    async def run(
        self,
        *,
        llm_router: Any,
        system_prompt: str,
        user_prompt: str,
        task_type: str,
        config: dict[str, Any],
        tool_schemas: list[dict[str, Any]],
        execute_tool_fn: Any,
        model_override: Optional[str] = None,
    ) -> tuple[str, Any]:
        fn = getattr(llm_router, "call_llm_react", None)
        if fn is None:
            raise NotImplementedError(
                "llm_router has no call_llm_react; cannot dispatch REACT"
            )
        return cast("tuple[str, Any]", await fn(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            task_type=task_type,
            config=config,
            tool_schemas=tool_schemas,
            execute_tool_fn=execute_tool_fn,
            model_override=model_override,
        ))


register_reasoning(ReactReasoning())

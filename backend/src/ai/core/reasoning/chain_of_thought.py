"""Chain-of-thought reasoning — Track 2 adapter."""
from __future__ import annotations

from typing import Any, Optional

from src.ai.core.reasoning.base import register_reasoning
from src.ai.schemas.enums import ReasoningMode


class ChainOfThoughtReasoning:
    name = ReasoningMode.CHAIN_OF_THOUGHT

    async def run(
        self,
        *,
        llm_router: Any,
        system_prompt: str,
        user_prompt: str,
        task_type: str,
        config: dict[str, Any],
        tool_schemas: list[dict[str, Any]],          # noqa: ARG002
        execute_tool_fn: Any,              # noqa: ARG002
        model_override: Optional[str] = None,
    ) -> tuple[str, Any]:
        fn = getattr(llm_router, "call_llm", None)
        if fn is None:
            raise NotImplementedError("llm_router missing call_llm")
        resp = await fn(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            task_type=task_type,
            config=config,
            model_override=model_override,
        )
        text = getattr(resp, "output", None) or getattr(resp, "content", "") or str(resp)
        return text, resp


register_reasoning(ChainOfThoughtReasoning())

"""
ai.services.attributed_usage — Shared best-effort attributed usage helper.

A single function used by every non-tool LLM call site (critic
pipeline, planner, plan judge, dreaming, meta_spec_critic, goal
alignment) to write attributed input/output usage rows for an
``LLMResponse``. Wraps :class:`UsageService.log_usage` with the right
attribution and swallows any error so a billing hiccup never bubbles
up into the calling pipeline.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

__all__ = ["log_llm_response_usage"]


async def log_llm_response_usage(
    *,
    db: Any,
    response: Any,
    attribution: str,
    company_id: Optional[UUID],
    run_id: Optional[UUID] = None,
    system_prompt: str = "",
    user_prompt: str = "",
) -> None:
    """Write input+output usage rows for one LLM call and, when the call
    belongs to a run, its ``llm_interaction_logs`` row. Never raises.

    The interaction row (LP-I9) is what the run page shows of a model call:
    before, only a step's own calls had one, so the planner's and the critics'
    calls — the ones a user did not directly cause — could not be inspected.
    """
    if db is None or company_id is None or response is None:
        return
    model_name = getattr(response, "model_name", "") or ""
    prompt_tokens = int(getattr(response, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(response, "completion_tokens", 0) or 0)
    if not model_name or (prompt_tokens + completion_tokens) == 0:
        return
    try:
        from src.ai.usage_service import UsageService
        svc = UsageService(db)
        rows = []
        if prompt_tokens:
            rows.append(await svc.log_usage(
                company_id=company_id,
                service_sku=f"{model_name}-in",
                raw_quantity=float(prompt_tokens),
                execution_id=run_id,
                attribution=attribution,
            ))
        if completion_tokens:
            rows.append(await svc.log_usage(
                company_id=company_id,
                service_sku=f"{model_name}-out",
                raw_quantity=float(completion_tokens),
                execution_id=run_id,
                attribution=attribution,
            ))
        if run_id is not None:
            from decimal import Decimal

            from src.ai.orm.execution import LLMInteractionLog
            prompt = (f"System: {system_prompt[:2000]}\nUser: {user_prompt[:2000]}"
                      if (system_prompt or user_prompt) else f"[{attribution}]")
            db.add(LLMInteractionLog(
                run_id=run_id,
                model_provider=str(getattr(response, "provider", "") or "unknown"),
                model_name=model_name,
                input_prompt=prompt,
                output_response=str(getattr(response, "output", "") or ""),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=getattr(response, "latency_ms", None),
                cost_usd=sum((Decimal(str(r.calculated_cost)) for r in rows if r is not None),
                             Decimal("0")),
                reasoning_mode=attribution.upper(),
                step_name=f"__{attribution}__",
            ))
            await db.commit()
    except Exception as exc:                                                  # pragma: no cover
        # A lost usage row is a lost charge — surface it rather than hiding it.
        logger.warning("attributed usage logging failed (%s): %s", attribution, exc)

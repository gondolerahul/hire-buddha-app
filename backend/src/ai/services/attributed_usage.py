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
) -> None:
    """Write input+output usage rows for one LLM call. Never raises."""
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
        if prompt_tokens:
            await svc.log_usage(
                company_id=company_id,
                service_sku=f"{model_name}-in",
                raw_quantity=float(prompt_tokens),
                execution_id=run_id,
                attribution=attribution,
            )
        if completion_tokens:
            await svc.log_usage(
                company_id=company_id,
                service_sku=f"{model_name}-out",
                raw_quantity=float(completion_tokens),
                execution_id=run_id,
                attribution=attribution,
            )
    except Exception as exc:                                                  # pragma: no cover
        logger.debug("attributed usage logging failed (%s): %s", attribution, exc)

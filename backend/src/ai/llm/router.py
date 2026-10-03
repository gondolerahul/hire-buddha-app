"""
ai.llm.router — LLM Router and provider factory.

Main entry point for all LLM calls. Resolves the configured model for a
task type from the IntegrationRegistry and routes calls to the appropriate
provider adapter (Gemini, Anthropic, Azure OpenAI).

Extracted from llm_router.py during Phase 10B restructuring.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.llm.types import Attachment, LLMResponse
from src.ai.llm.base import BaseLLMAdapter
from src.ai.core.trace import span as _trace_span
from src.config.resolution_cache import ResolutionCache, current_generation

logger = logging.getLogger(__name__)

# Resolved adapters per (company, task type, override), shared by every router
# in the process and valid while the integration generation is (LP-I5, LP-22).
# A run used to resolve its model on every call: each call site built its own
# router, and each router its own cache.
_RESOLUTIONS = ResolutionCache()


def _record_llm_span(sp, resp: "LLMResponse") -> None:
    """Stamp a trace span with an LLMResponse's output, tokens, and model."""
    try:
        sp.set_output(getattr(resp, "output", ""), key="response")
        sp.set_tokens(
            getattr(resp, "prompt_tokens", None),
            getattr(resp, "completion_tokens", None),
        )
        sp.update(
            model_name=getattr(resp, "model_name", None),
            provider=getattr(resp, "provider", None),
            finish_reason=getattr(resp, "finish_reason", None),
            function_calls=getattr(resp, "function_calls", None),
            thinking_tokens=getattr(resp, "thinking_tokens", None),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def _sanitize_model_name(model_name: str) -> str:
    """
    Strip Vertex AI resource-path prefixes if present.

    The google-genai SDK automatically builds the full resource URL, so
    the model_name must be the *short* form (e.g. 'gemini-2.5-flash').
    If someone stores 'publishers/google/models/gemini-2.5-flash' in the
    DB, this helper strips the prefix to avoid a doubled path that returns 404.
    """
    _PREFIXES = (
        "publishers/google/models/",
        "publishers/anthropic/models/",
        "models/",
    )
    for prefix in _PREFIXES:
        if model_name.startswith(prefix):
            model_name = model_name[len(prefix):]
            break
    return model_name


def _get_adapter(provider_name: str, api_key: str, model_name: str, service_metadata: Dict) -> BaseLLMAdapter:
    """
    Instantiate the correct adapter given a provider name.
    provider_name (from IntegrationRegistry) → adapter class mapping.
    """
    from src.ai.llm.gemini_adapter import GeminiAdapter
    from src.ai.llm.anthropic_adapter import AnthropicAdapter
    from src.ai.llm.azure_adapter import AzureOpenAIAdapter

    model_name = _sanitize_model_name(model_name)
    pn = (provider_name or "").lower()
    if pn in ("google", "gemini", "google_vertex"):
        return GeminiAdapter(api_key=api_key, model_name=model_name, service_metadata=service_metadata)
    elif pn in ("anthropic", "anthropic_vertex"):
        return AnthropicAdapter(api_key=api_key, model_name=model_name, service_metadata=service_metadata)
    elif pn in ("azure_openai", "azure", "openai"):
        return AzureOpenAIAdapter(api_key=api_key, model_name=model_name, service_metadata=service_metadata)
    else:
        # Default: try Gemini-compatible
        logger.warning(f"Unknown provider '{provider_name}', defaulting to GeminiAdapter")
        return GeminiAdapter(api_key=api_key, model_name=model_name, service_metadata=service_metadata)


# ---------------------------------------------------------------------------
# LLM Router — main entry point
# ---------------------------------------------------------------------------

class LLMRouter:
    """
    Main LLM dispatch class. Resolves the configured model for a task type
    and routes calls to the appropriate provider adapter.

    Usage:
        router = LLMRouter(db=db, company_id=company_id)
        response = await router.call_llm(task_type="text_generation", ...)
    """

    def __init__(self, db: AsyncSession, company_id: UUID):
        self.db = db
        self.company_id = company_id

    async def _resolve_adapter(self, task_type: str, model_override: Optional[str] = None) -> BaseLLMAdapter:
        """Resolve the correct adapter based on task defaults.

        Cached per (company, task type, override) for every router in the
        process until a registry or task-default write changes the integration
        generation (``src/config/resolution_cache.py``).

        Args:
            task_type: The task type to resolve the model for.
            model_override: Optional model name override from entity config.
                           When set, the adapter uses this model instead of the
                           integration's default (e.g. "gemini-3.1-pro-preview").
        """
        cache_key = (self.company_id, task_type, model_override or "")
        generation = await current_generation()
        cached = _RESOLUTIONS.get(cache_key, generation)
        if cached is not ResolutionCache.MISS:
            return cached

        from src.config.service import ConfigService
        config_svc = ConfigService(self.db)
        if model_override:
            # An override resolves through the registry like any model: its own
            # provider, key and settings, and it must be billable (LP-05).
            # Before, it replaced only the model name, so "gpt-4o" was sent to
            # Vertex with the default's key, and a model with no SKU billed $0.
            effective_model = _sanitize_model_name(model_override)
            integration, api_key = await config_svc.resolve_model_by_name(
                company_id=self.company_id, model_name=effective_model,
            )
            if not integration:
                raise RuntimeError(
                    f"Model override '{effective_model}' has no active, billable integration "
                    f"(an LLM row with '{effective_model}-in' and '{effective_model}-out' SKUs) "
                    f"for company {self.company_id} or the platform. Configure it in Service "
                    f"Integrations, or remove the entity's model override."
                )
            logger.info(f"LLMRouter: model override '{effective_model}' via {integration.provider_name}")
        else:
            integration, api_key = await config_svc.resolve_model_for_task(
                company_id=self.company_id,
                task_type=task_type,
            )
            if not integration:
                from src.config.model_health import HOW_TO_CONFIGURE
                raise RuntimeError(
                    f"No model configured for task type '{task_type}' "
                    f"(company {self.company_id}, and no platform default). {HOW_TO_CONFIGURE}"
                )
            effective_model = integration.model_name or ""
        from src.config.models import needs_api_key
        if not api_key and needs_api_key(integration.provider_name):
            raise RuntimeError(
                f"No API key found for integration '{integration.provider_name}/{effective_model}'. "
                f"Please check the Service Integration configuration."
            )
        adapter = _get_adapter(
            provider_name=integration.provider_name,
            api_key=api_key or "",
            model_name=effective_model,
            service_metadata=integration.service_metadata or {},
        )
        _RESOLUTIONS.put(cache_key, adapter, generation)
        return adapter

    async def call_llm(
        self,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
        history: Optional[List[Dict]] = None,
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        top_p: float = 1.0,
        model_override: Optional[str] = None,
        attachments: Optional[List[Attachment]] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Single-turn (or last-turn) LLM call.
        Constructs messages from history + current user_prompt, with any
        ``attachments`` (images, PDFs) as parts beside the text (LP-24).
        """
        adapter = await self._resolve_adapter(task_type, model_override=model_override)
        messages = list(history or [])
        messages.append({"role": "user", "parts": [{"text": user_prompt}, *(a.part() for a in attachments or [])]})

        async with _trace_span(
            "llm", model_override or task_type,
            task_type=task_type,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            history=history,
            attachments=[a.describe() for a in attachments] if attachments else None,
        ) as _sp:
            resp = await adapter.generate(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                **kwargs,
            )
            _record_llm_span(_sp, resp)
            return resp

    async def call_llm_react(
        self,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
        tool_schemas: List[Dict[str, Any]],
        execute_tool_fn,
        history: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        max_react_turns: int = 10,
        model_override: Optional[str] = None,
        top_p: float = 1.0,
        **kwargs,
    ) -> LLMResponse:
        """
        Full REACT loop for agentic tasks.
        execute_tool_fn: async(function_calls: list) -> list of {tool, output, success},
        one per call in order; each call carries an ``id`` (LP-17).
        """
        adapter = await self._resolve_adapter(task_type, model_override=model_override)
        messages = list(history or [])
        messages.append({"role": "user", "parts": [{"text": user_prompt}]})

        # ReAct turn span — tool spans opened by ``execute_tool_fn`` nest under
        # this node, so the UI shows which tools each model turn invoked.
        async with _trace_span(
            "llm", (model_override or task_type) + " (react)",
            task_type=task_type,
            mode="react",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tool_schemas=[s.get("name") for s in (tool_schemas or []) if isinstance(s, dict)],
        ) as _sp:
            resp = await adapter.generate_with_tools_react(
                system_prompt=system_prompt,
                initial_messages=messages,
                tool_schemas=tool_schemas,
                execute_tool_fn=execute_tool_fn,
                temperature=temperature,
                max_tokens=max_tokens,
                max_react_turns=max_react_turns,
                top_p=top_p,
                **kwargs,
            )
            _record_llm_span(_sp, resp)
            return resp

    async def get_adapter_for_task(self, task_type: str) -> BaseLLMAdapter:
        """Expose the resolved adapter (useful for streaming modules)."""
        return await self._resolve_adapter(task_type)

"""
ai.llm.azure_adapter — Azure OpenAI adapter (GPT-4o and compatible models).

Handles Azure-specific SDK initialization, deployment name resolution,
and the OpenAI REACT loop protocol (tool_calls / tool messages).

Extracted from llm_router.py during Phase 10B restructuring.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from src.ai.llm.types import LLMResponse
from src.ai.llm.base import BaseLLMAdapter

logger = logging.getLogger(__name__)


class AzureOpenAIAdapter(BaseLLMAdapter):
    """Adapter for Azure OpenAI models (GPT-4o, GPT-4 Turbo, etc.)"""

    @property
    def _provider_name(self):
        return "azure_openai"

    def _build_client(self):
        """
        Build the appropriate async OpenAI client based on the endpoint type.

        Azure has three endpoint patterns, each requiring different SDK setup:

        1. **Classic Azure OpenAI** (``*.openai.azure.com``)
           → ``AsyncAzureOpenAI(azure_endpoint=..., api_version=...)``
           SDK builds: ``{endpoint}/openai/deployments/{model}/chat/completions?api-version=...``

        2. **AI Foundry project** (``*.services.ai.azure.com``)
           → ``AsyncOpenAI(base_url=https://{host}/openai/v1/)``
           The ``/api/projects/...`` path is for the management SDK, not
           the OpenAI SDK.  The OpenAI-compatible inference path is
           ``/openai/v1/`` directly on the resource host.

        3. **Serverless model** (``*.models.ai.azure.com``)
           → ``AsyncOpenAI(base_url={endpoint}/v1)``
           Plain OpenAI-compatible endpoint, no api-version needed.
        """
        try:
            from openai import AsyncAzureOpenAI, AsyncOpenAI
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai")

        azure_endpoint = self.service_metadata.get("azure_endpoint", "").strip()
        api_version = self.service_metadata.get("api_version", "2025-01-01-preview")
        if not azure_endpoint:
            raise ValueError("service_metadata.azure_endpoint is required for azure_openai provider")

        lower = azure_endpoint.lower().rstrip("/")

        # ── Case 3: Serverless model endpoints (*.models.ai.azure.com) ──
        # OpenAI-compatible /v1 API, rejects api-version.
        if ".models.ai.azure.com" in lower:
            base_url = azure_endpoint.rstrip("/")
            if not base_url.endswith("/v1"):
                base_url += "/v1"
            logger.info(
                "Azure adapter: serverless model endpoint → AsyncOpenAI(base_url=%s)",
                base_url,
            )
            return AsyncOpenAI(
                api_key=self.api_key,
                base_url=base_url,
            )

        # ── Case 2: AI Foundry project endpoints (*.services.ai.azure.com) ──
        # Users often paste the full portal URL like:
        #   https://res.services.ai.azure.com/api/projects/proj/openai/v1/responses
        # The OpenAI SDK should hit:
        #   https://res.services.ai.azure.com/openai/v1/
        # We extract the scheme+host and build the correct base_url.
        # Note: Do not pass api-version to services.ai.azure.com endpoints, as they reject it.
        if ".services.ai.azure.com" in lower:
            from urllib.parse import urlparse
            parsed = urlparse(azure_endpoint)
            base_url = f"{parsed.scheme}://{parsed.netloc}/openai/v1"
            logger.info(
                "Azure adapter: Foundry project endpoint → AsyncOpenAI(base_url=%s) [raw: %s]",
                base_url,
                azure_endpoint,
            )
            return AsyncOpenAI(
                api_key=self.api_key,
                base_url=base_url,
            )

        # ── Case 1: Classic Azure OpenAI (*.openai.azure.com) ──
        # Also handles any other unrecognised Azure endpoint shapes.
        # Clean up if the user accidentally pasted a path with /openai/...
        cleaned = azure_endpoint.rstrip("/")
        idx = cleaned.lower().find("/openai")
        if idx != -1:
            cleaned = cleaned[:idx]
            logger.info(
                "Azure adapter: cleaned classic endpoint %s → %s",
                azure_endpoint,
                cleaned,
            )

        return AsyncAzureOpenAI(
            api_key=self.api_key,
            azure_endpoint=cleaned,
            api_version=api_version,
        )

    def _get_deployment(self) -> str:
        """Get deployment name from metadata or fall back to model_name."""
        return self.service_metadata.get("deployment_name", self.model_name)

    def _build_messages(self, system_prompt: str, messages: List[Dict]) -> List[Dict]:
        """Convert unified format to OpenAI messages format."""
        result = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system":
                continue
            if role == "model":
                role = "assistant"

            parts = msg.get("parts", [])
            content = ""
            if isinstance(parts, list):
                for p in parts:
                    if isinstance(p, dict) and "text" in p:
                        content += p["text"]
                    elif isinstance(p, str):
                        content += p
            elif isinstance(parts, str):
                content = parts

            if content:
                result.append({"role": role, "content": content})

        return result

    def get_tool_declarations(self, tool_schemas: List[Dict]) -> List[Dict]:
        """Convert JSON Schema tool defs to OpenAI tool format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": schema["name"],
                    "description": schema.get("description", ""),
                    "parameters": schema.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for schema in tool_schemas
        ]

    def _prepare_completion_args(
        self,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Prepare chat completion arguments based on model type requirements."""
        args: Dict[str, Any] = {}

        # Determine if we should map max_tokens to max_completion_tokens
        # o1, o3, and newer models (like gpt-5) use max_completion_tokens instead of max_tokens
        model_lower = (self.model_name or "").lower()
        use_max_completion_tokens = any(x in model_lower for x in ["gpt-5", "gpt-5.5", "o1", "o3"])

        if max_tokens is not None:
            if use_max_completion_tokens:
                args["max_completion_tokens"] = max_tokens
            else:
                args["max_tokens"] = max_tokens

        # Reasoning / frontier models only support temperature=1.0
        # This applies to o1, o3, gpt-5, and gpt-5.5
        is_reasoning_model = use_max_completion_tokens  # same set of models
        if is_reasoning_model:
            args["temperature"] = 1.0
        else:
            args["temperature"] = temperature

        return args

    async def generate(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        top_p: float = 1.0,
        **kwargs,
    ) -> LLMResponse:
        client = self._build_client()
        oai_messages = self._build_messages(system_prompt, messages)

        kwargs_extra: Dict[str, Any] = self._prepare_completion_args(
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs_extra["tools"] = self.get_tool_declarations(tools)
            kwargs_extra["tool_choice"] = "auto"

        start = time.monotonic()
        response = await client.chat.completions.create(
            model=self._get_deployment(),
            messages=oai_messages,
            top_p=top_p,
            **kwargs_extra,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        output = choice.message.content or ""
        function_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                args = {}
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {"raw": tc.function.arguments}
                function_calls.append({"name": tc.function.name, "args": args, "_id": tc.id})

        return LLMResponse(
            output=output,
            function_calls=function_calls,
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            latency_ms=latency_ms,
            model_name=self.model_name,
            provider=self._provider_name,
            finish_reason=choice.finish_reason or "stop",
        )

    async def generate_with_tools_react(
        self,
        system_prompt: str,
        initial_messages: List[Dict[str, Any]],
        tool_schemas: List[Dict[str, Any]],
        execute_tool_fn,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        max_react_turns: int = 10,
        **kwargs,
    ) -> LLMResponse:
        """Azure OpenAI REACT loop — uses tool_calls / tool message protocol."""
        client = self._build_client()
        messages = self._build_messages(system_prompt, initial_messages)
        tool_defs = self.get_tool_declarations(tool_schemas)

        total_prompt = 0
        total_completion = 0
        total_latency = 0
        combined_output = ""
        all_function_calls = []

        completion_args = self._prepare_completion_args(
            temperature=temperature,
            max_tokens=max_tokens,
        )

        for turn in range(max_react_turns):
            start = time.monotonic()
            response = await client.chat.completions.create(
                model=self._get_deployment(),
                messages=messages,
                tools=tool_defs if tool_defs else [],
                tool_choice="auto" if tool_defs else "none",
                **completion_args,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            total_latency += latency_ms

            if response.usage:
                total_prompt += response.usage.prompt_tokens
                total_completion += response.usage.completion_tokens

            choice = response.choices[0]
            turn_text = choice.message.content or ""
            function_calls = []

            # Append assistant message
            messages.append({"role": "assistant", "content": choice.message.content, "tool_calls": choice.message.tool_calls})

            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    args = {}
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {"raw": tc.function.arguments}
                    function_calls.append({"name": tc.function.name, "args": args, "_id": tc.id})

            if function_calls:
                all_function_calls.extend(function_calls)
                tool_results = await execute_tool_fn(function_calls)

                # Append one tool message per result
                for tr, fc in zip(tool_results, function_calls):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": fc.get("_id", fc["name"]),
                        "content": str(tr["output"]),
                    })

                if turn_text:
                    combined_output += turn_text
                continue
            else:
                combined_output += turn_text
                break

        return LLMResponse(
            output=combined_output,
            function_calls=all_function_calls,
            prompt_tokens=total_prompt,
            completion_tokens=total_completion,
            latency_ms=total_latency,
            model_name=self.model_name,
            provider=self._provider_name,
        )

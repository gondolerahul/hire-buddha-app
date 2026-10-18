"""
ai.llm.anthropic_adapter — Anthropic Claude adapter.

Handles Anthropic-specific SDK initialization, tool declaration conversion,
and the Anthropic REACT loop protocol (tool_use / tool_result blocks).

Where Claude runs is the integration's ``service_metadata.provider``
(Phase 14 WS1 1.6, tech spec §12.4), else ``settings.ANTHROPIC_PROVIDER``:

* ``vertex`` — Vertex AI (``project_id``, ``region``), Google credentials.
* ``foundry`` — Microsoft Foundry (``resource`` or ``foundry_endpoint``). The
  stored key if the integration has one, else an Entra token from the
  workload's identity (``entra_scope`` overrides the scope).
* ``anthropic`` — the Anthropic API with the stored key.

The request itself is the same on all three.

Extracted from llm_router.py during Phase 10B restructuring.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from src.ai.llm.retry import call_provider
from src.ai.llm.types import FINISH_MAX_TURNS, LLMResponse, TextSink, inline_parts
from src.ai.llm.base import BaseLLMAdapter, call_id, pair_tool_results

logger = logging.getLogger(__name__)


CLAUDE_PROVIDERS = ("vertex", "foundry", "anthropic")


class AnthropicAdapter(BaseLLMAdapter):
    """Adapter for Anthropic Claude models on Vertex AI, Microsoft Foundry or the Anthropic API."""

    @property
    def _provider_name(self):
        return "anthropic"

    def claude_provider(self) -> str:
        from src.common.config import settings

        provider = str(self.service_metadata.get("provider") or settings.ANTHROPIC_PROVIDER or "vertex")
        provider = provider.strip().lower()
        if provider not in CLAUDE_PROVIDERS:
            raise ValueError(f"service_metadata.provider must be one of {', '.join(CLAUDE_PROVIDERS)}, "
                             f"not {provider!r}")
        return provider

    def _build_client(self):
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

        # Retries are ai/llm/retry.py's (LP-03); the SDK's own would multiply them.
        provider = self.claude_provider()
        if provider == "foundry":
            return self._foundry_client(anthropic)
        if provider == "anthropic":
            if not self.api_key:
                raise ValueError("Claude through the Anthropic API needs the integration's API key")
            return anthropic.AsyncAnthropic(api_key=self.api_key, max_retries=0)

        project = self.service_metadata.get("project_id")
        region = self.service_metadata.get("region", "us-east5")
        if not project:
            raise ValueError(
                "service_metadata.project_id is required for Anthropic via Vertex AI. "
                "Please configure the Anthropic integration with your GCP project ID."
            )
        from src.common.genai_factory import google_credentials

        return anthropic.AsyncAnthropicVertex(project_id=project, region=region, max_retries=0,
                                              credentials=google_credentials())

    def _foundry_client(self, anthropic):
        """``AsyncAnthropicFoundry`` for the integration's resource or endpoint.

        Both are passed explicitly: the SDK refuses a ``base_url`` beside a
        resource, and would read ``ANTHROPIC_FOUNDRY_RESOURCE`` from the
        environment otherwise."""
        from src.common.config import settings

        resource = str(self.service_metadata.get("resource") or "").strip() or None
        endpoint = None if resource else (
            str(self.service_metadata.get("foundry_endpoint") or settings.FOUNDRY_ENDPOINT or "").strip() or None)
        if not (resource or endpoint):
            raise ValueError("Claude on Microsoft Foundry needs service_metadata.resource (the Foundry "
                             "resource name) or foundry_endpoint, or FOUNDRY_ENDPOINT")
        location = {"resource": resource} if resource else {"base_url": endpoint}
        if self.api_key:
            return anthropic.AsyncAnthropicFoundry(api_key=self.api_key, max_retries=0, **location)
        from src.common.platform.identity import COGNITIVE_SERVICES_SCOPE, token_provider

        scope = str(self.service_metadata.get("entra_scope") or COGNITIVE_SERVICES_SCOPE)
        return anthropic.AsyncAnthropicFoundry(azure_ad_token_provider=token_provider(scope),
                                               max_retries=0, **location)

    def _build_messages(self, system_prompt: str, messages: List[Dict]) -> Tuple[str, List]:
        """Convert unified format to Anthropic messages format."""
        anthropic_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system":
                continue  # handled as system param
            if role == "model":
                role = "assistant"  # Anthropic uses 'assistant'

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

            blobs = inline_parts(parts)
            if blobs:
                # Images (and PDFs) as content blocks beside the text (LP-24).
                blocks: List[Dict[str, Any]] = [self._file_block(b) for b in blobs]
                if content:
                    blocks.append({"type": "text", "text": content})
                anthropic_messages.append({"role": role, "content": blocks})
            elif content:
                anthropic_messages.append({"role": role, "content": content})

        return system_prompt, anthropic_messages

    @staticmethod
    def _file_block(blob: Dict[str, Any]) -> Dict[str, Any]:
        import base64
        kind = "document" if blob["mime_type"] == "application/pdf" else "image"
        return {"type": kind, "source": {"type": "base64", "media_type": blob["mime_type"],
                                         "data": base64.b64encode(blob["data"]).decode("ascii")}}

    @staticmethod
    def _sampling(temperature: float, top_p: float) -> Dict[str, Any]:
        """``top_p`` only when set: newer Claude models refuse ``temperature``
        and ``top_p`` together, and 1.0 is the default anyway (LP-20)."""
        args: Dict[str, Any] = {"temperature": temperature}
        if top_p is not None and top_p < 1.0:
            args["top_p"] = top_p
        return args

    def get_tool_declarations(self, tool_schemas: List[Dict]) -> List[Dict]:
        """Convert JSON Schema tool defs to Anthropic tool format."""
        tools = []
        for schema in tool_schemas:
            tools.append({
                "name": schema["name"],
                "description": schema.get("description", ""),
                "input_schema": schema.get("parameters", {"type": "object", "properties": {}}),
            })
        return tools

    async def generate(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        top_p: float = 1.0,
        text_sink: Optional[TextSink] = None,
        **kwargs,
    ) -> LLMResponse:
        client = self._build_client()
        _, anthropic_messages = self._build_messages(system_prompt, messages)

        kwargs_extra = {}
        if tools:
            kwargs_extra["tools"] = self.get_tool_declarations(tools)

        start = time.monotonic()
        response = await call_provider(lambda: client.messages.create(
            model=self.model_name,
            system=system_prompt,
            messages=anthropic_messages,
            max_tokens=max_tokens or 8096,
            **self._sampling(temperature, top_p),
            **kwargs_extra,
        ), what=f"anthropic {self.model_name}")
        latency_ms = int((time.monotonic() - start) * 1000)

        output = ""
        function_calls = []
        for block in response.content:
            if block.type == "text":
                output += block.text
            elif block.type == "tool_use":
                function_calls.append({
                    "id": call_id(getattr(block, "id", None), 1, len(function_calls)),
                    "name": block.name,
                    "args": block.input or {},
                })

        if text_sink is not None and output:
            await text_sink.delta(output)  # whole, not streamed (D26)
        return LLMResponse(
            output=output,
            function_calls=function_calls,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            latency_ms=latency_ms,
            model_name=self.model_name,
            provider=self._provider_name,
            finish_reason=response.stop_reason or "stop",
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
        top_p: float = 1.0,
        text_sink: Optional[TextSink] = None,
        **kwargs,
    ) -> LLMResponse:
        """Anthropic REACT loop — uses tool_use/tool_result block protocol."""
        client = self._build_client()
        _, messages = self._build_messages(system_prompt, initial_messages)
        tool_defs = self.get_tool_declarations(tool_schemas)

        total_prompt = 0
        total_completion = 0
        total_latency = 0
        combined_output = ""
        all_function_calls = []

        finish_reason = "stop"
        for turn in range(max_react_turns):
            start = time.monotonic()
            response = await call_provider(lambda: client.messages.create(
                model=self.model_name,
                system=system_prompt,
                messages=messages,
                max_tokens=max_tokens or 8096,
                **self._sampling(temperature, top_p),
                tools=tool_defs if tool_defs else [],
            ), what=f"anthropic {self.model_name} (react turn {turn + 1})")
            latency_ms = int((time.monotonic() - start) * 1000)
            total_latency += latency_ms
            total_prompt += response.usage.input_tokens
            total_completion += response.usage.output_tokens

            turn_text = ""
            function_calls = []

            for block in response.content:
                if block.type == "text":
                    turn_text += block.text
                elif block.type == "tool_use":
                    function_calls.append({"id": call_id(getattr(block, "id", None), turn + 1, len(function_calls)),
                                           "name": block.name, "args": block.input or {}})

            # Append assistant turn
            messages.append({"role": "assistant", "content": response.content})

            if text_sink is not None and turn_text:
                await text_sink.delta(turn_text)  # each turn whole, not streamed (D26)

            if function_calls:
                all_function_calls.extend(function_calls)
                tool_results = await execute_tool_fn(function_calls)

                # One tool_result per tool_use, with that block's id (LP-17).
                tool_result_content = [
                    {"type": "tool_result", "tool_use_id": fc["id"], "content": str(tr["output"])}
                    for fc, tr in pair_tool_results(function_calls, tool_results)
                ]

                messages.append({"role": "user", "content": tool_result_content})
                if turn_text:
                    combined_output += turn_text
                continue
            else:
                combined_output += turn_text
                break
        else:
            # Every turn called tools: the model was cut off, not finished.
            finish_reason = FINISH_MAX_TURNS

        return LLMResponse(
            output=combined_output,
            function_calls=all_function_calls,
            prompt_tokens=total_prompt,
            completion_tokens=total_completion,
            latency_ms=total_latency,
            model_name=self.model_name,
            provider=self._provider_name,
            finish_reason=finish_reason,
        )

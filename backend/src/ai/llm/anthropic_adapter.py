"""
ai.llm.anthropic_adapter — Anthropic Claude adapter via Vertex AI.

Handles Anthropic-specific SDK initialization, tool declaration conversion,
and the Anthropic REACT loop protocol (tool_use / tool_result blocks).

Extracted from llm_router.py during Phase 10B restructuring.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from src.ai.llm.types import LLMResponse
from src.ai.llm.base import BaseLLMAdapter

logger = logging.getLogger(__name__)


class AnthropicAdapter(BaseLLMAdapter):
    """Adapter for Anthropic Claude models via Vertex AI only."""

    @property
    def _provider_name(self):
        return "anthropic"

    def _build_client(self):
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

        project = self.service_metadata.get("project_id")
        region = self.service_metadata.get("region", "us-east5")
        if not project:
            raise ValueError(
                "service_metadata.project_id is required for Anthropic via Vertex AI. "
                "Please configure the Anthropic integration with your GCP project ID."
            )
        return anthropic.AsyncAnthropicVertex(project_id=project, region=region)

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

            if content:
                anthropic_messages.append({"role": role, "content": content})

        return system_prompt, anthropic_messages

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
        **kwargs,
    ) -> LLMResponse:
        client = self._build_client()
        _, anthropic_messages = self._build_messages(system_prompt, messages)

        kwargs_extra = {}
        if tools:
            kwargs_extra["tools"] = self.get_tool_declarations(tools)

        start = time.monotonic()
        response = await client.messages.create(
            model=self.model_name,
            system=system_prompt,
            messages=anthropic_messages,
            max_tokens=max_tokens or 8096,
            temperature=temperature,
            top_p=top_p,
            **kwargs_extra,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        output = ""
        function_calls = []
        for block in response.content:
            if block.type == "text":
                output += block.text
            elif block.type == "tool_use":
                function_calls.append({
                    "name": block.name,
                    "args": block.input or {},
                })

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

        for turn in range(max_react_turns):
            start = time.monotonic()
            response = await client.messages.create(
                model=self.model_name,
                system=system_prompt,
                messages=messages,
                max_tokens=max_tokens or 8096,
                temperature=temperature,
                tools=tool_defs if tool_defs else [],
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            total_latency += latency_ms
            total_prompt += response.usage.input_tokens
            total_completion += response.usage.output_tokens

            turn_text = ""
            function_calls = []
            assistant_content = []

            for block in response.content:
                assistant_content.append(block)
                if block.type == "text":
                    turn_text += block.text
                elif block.type == "tool_use":
                    function_calls.append({"name": block.name, "args": block.input or {}})

            # Append assistant turn
            messages.append({"role": "assistant", "content": response.content})

            if function_calls:
                all_function_calls.extend(function_calls)
                tool_results = await execute_tool_fn(function_calls)

                # Build tool_result blocks for Anthropic
                tool_result_content = []
                for tr in tool_results:
                    # Find matching tool_use block id
                    matching_block = next(
                        (b for b in assistant_content if getattr(b, "type", "") == "tool_use" and b.name == tr["tool"]),
                        None
                    )
                    tool_use_id = getattr(matching_block, "id", tr["tool"]) if matching_block else tr["tool"]
                    tool_result_content.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": str(tr["output"]),
                    })

                messages.append({"role": "user", "content": tool_result_content})
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

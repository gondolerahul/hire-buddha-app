"""
ai.llm.gemini_adapter — Google Gemini adapter via Vertex AI.

Handles Gemini-specific SDK initialization, tool declaration conversion
(JSON Schema → Gemini FunctionDeclaration), and the Gemini REACT loop
protocol (function_response parts).

Extracted from llm_router.py during Phase 10B restructuring.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from src.ai.llm.types import LLMResponse
from src.ai.llm.base import BaseLLMAdapter

logger = logging.getLogger(__name__)

# Gemini 2.5 and 3 think before answering, and thinking tokens count against
# ``max_output_tokens``. Callers size ``max_tokens`` for the answer, so a capped
# call gets this thinking allowance on top (LP-25). Override per integration
# with ``service_metadata.thinking_budget``.
DEFAULT_THINKING_BUDGET = 1024
_THINKING_MODEL_PREFIXES = ("gemini-2.5", "gemini-3")


class GeminiAdapter(BaseLLMAdapter):
    """Adapter for Google Gemini models via Vertex AI only."""

    @property
    def _provider_name(self):
        return "google"

    def _build_client(self):
        from src.common.genai_factory import build_vertex_genai_client_sync
        return build_vertex_genai_client_sync(self.service_metadata)

    def _configured_thinking_budget(self) -> Optional[int]:
        raw = self.service_metadata.get("thinking_budget")
        if raw is None:
            return None
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            logger.warning(f"Ignoring invalid service_metadata.thinking_budget {raw!r}")
            return None

    def _apply_output_limits(self, config: Any, max_tokens: Optional[int]) -> None:
        """Keep thinking from starving the answer.

        Without this, ``max_tokens=400`` on gemini-2.5-flash spent nearly all
        400 tokens thinking and returned a cut-off answer. For a thinking model
        a capped call gets an explicit thinking budget, added to the answer
        budget. Uncapped calls keep the model's dynamic thinking unless the
        integration configures a budget.
        """
        from google.genai import types

        budget = self._configured_thinking_budget()
        if budget is None and max_tokens and self.model_name.startswith(_THINKING_MODEL_PREFIXES):
            budget = DEFAULT_THINKING_BUDGET
        if budget is not None:
            config.thinking_config = types.ThinkingConfig(thinking_budget=budget)
        if max_tokens:
            config.max_output_tokens = max_tokens + (budget or 0)

    def _warn_if_truncated(self, response: Any, max_tokens: Optional[int]) -> None:
        if not response.candidates or "MAX_TOKENS" not in str(response.candidates[0].finish_reason):
            return
        usage = response.usage_metadata
        logger.warning(
            f"Gemini {self.model_name} answer truncated at max_tokens={max_tokens} "
            f"(answer {getattr(usage, 'candidates_token_count', 0) or 0} tokens, "
            f"thinking {getattr(usage, 'thoughts_token_count', 0) or 0} tokens)"
        )

    _GEMINI_TYPE_MAP = {
        "string": "STRING",
        "integer": "INTEGER",
        "number": "NUMBER",
        "boolean": "BOOLEAN",
        "array": "ARRAY",
        "object": "OBJECT",
    }

    def _prop_to_schema(self, prop_def: Dict) -> Any:
        """Recursively convert a JSON-Schema property dict to a Gemini types.Schema.

        Handles nested objects, arrays with items, and enum values — all of which
        the Gemini API strictly validates.
        """
        from google.genai import types

        prop_type = self._GEMINI_TYPE_MAP.get(prop_def.get("type", "string"), "STRING")
        kwargs: Dict[str, Any] = {
            "type": prop_type,
            "description": prop_def.get("description", ""),
        }

        # Enum values
        if "enum" in prop_def:
            kwargs["enum"] = [str(v) for v in prop_def["enum"]]

        # Array → must have items
        if prop_type == "ARRAY":
            items_def = prop_def.get("items")
            if items_def and isinstance(items_def, dict):
                kwargs["items"] = self._prop_to_schema(items_def)
            else:
                # Fallback: Gemini requires items for ARRAY; default to STRING
                kwargs["items"] = types.Schema(type="STRING")

        # Nested object → recurse into properties
        if prop_type == "OBJECT":
            nested_props = prop_def.get("properties", {})
            if nested_props and isinstance(nested_props, dict):
                kwargs["properties"] = {
                    k: self._prop_to_schema(v)
                    for k, v in nested_props.items()
                }
            nested_required = prop_def.get("required")
            if nested_required:
                kwargs["required"] = nested_required

        return types.Schema(**kwargs)

    def get_tool_declarations(self, tool_schemas: List[Dict]) -> Any:
        """Convert JSON Schema tool defs to Gemini FunctionDeclaration objects."""
        try:
            from google.genai import types
        except ImportError:
            return []

        declarations = []
        for schema in tool_schemas:
            props = {}
            required = []
            raw_props = schema.get("parameters", {}).get("properties", {})
            raw_required = schema.get("parameters", {}).get("required", [])
            for prop_name, prop_def in raw_props.items():
                try:
                    props[prop_name] = self._prop_to_schema(prop_def)
                except Exception as e:
                    logger.warning(
                        f"Skipping malformed property '{prop_name}' in tool "
                        f"'{schema.get('name', '?')}': {e}"
                    )
                    # Fallback to basic STRING to avoid crashing the whole tool
                    props[prop_name] = types.Schema(
                        type="STRING",
                        description=prop_def.get("description", ""),
                    )
            if raw_required:
                required = raw_required

            declarations.append(
                types.FunctionDeclaration(
                    name=schema["name"],
                    description=schema.get("description", ""),
                    parameters=types.Schema(
                        type="OBJECT",
                        properties=props,
                        required=required,
                    ),
                )
            )
        return declarations

    def _build_contents(self, system_prompt: str, messages: List[Dict]) -> Tuple[str, List]:
        """Convert unified message format to Gemini contents."""
        try:
            from google.genai import types
        except ImportError:
            raise RuntimeError("google-genai not installed")

        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system":
                # Skip — Gemini uses system_instruction separately
                continue
            content_parts = []
            parts = msg.get("parts", [])
            if isinstance(parts, list):
                for p in parts:
                    if isinstance(p, dict) and "text" in p:
                        content_parts.append(types.Part.from_text(text=p["text"]))
                    elif isinstance(p, str):
                        content_parts.append(types.Part.from_text(text=p))
            elif isinstance(parts, str):
                content_parts.append(types.Part.from_text(text=parts))

            if content_parts:
                contents.append(types.Content(role=role, parts=content_parts))

        return system_prompt, contents

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
        from google.genai import types

        client = self._build_client()
        _, contents = self._build_contents(system_prompt, messages)

        generate_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            top_p=top_p,
        )
        self._apply_output_limits(generate_config, max_tokens)

        if tools:
            declarations = self.get_tool_declarations(tools)
            if declarations:
                generate_config.tools = [types.Tool(function_declarations=declarations)]

        start = time.monotonic()
        try:
            response = await client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=generate_config,
            )
        except Exception as e:
            if "ValidationError" in type(e).__name__ and "finish_reason" in str(e):
                logger.warning(f"SDK finish_reason validation error (non-fatal), retrying with raw HTTP: {e}")
                raise RuntimeError(
                    f"Gemini SDK validation error for model {self.model_name}. "
                    f"Consider upgrading google-genai (current: 0.4.0). Error: {e}"
                ) from e
            raise
        latency_ms = int((time.monotonic() - start) * 1000)
        self._warn_if_truncated(response, max_tokens)

        output = ""
        function_calls = []
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    function_calls.append({
                        "name": part.function_call.name,
                        "args": dict(part.function_call.args) if part.function_call.args else {},
                    })
                elif hasattr(part, "text") and part.text:
                    output += part.text
        if not output and response.text:
            output = response.text

        usage = response.usage_metadata
        return LLMResponse(
            output=output,
            function_calls=function_calls,
            prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            completion_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            latency_ms=latency_ms,
            model_name=self.model_name,
            provider=self._provider_name,
            finish_reason=str(response.candidates[0].finish_reason) if response.candidates else "stop",
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
        """Gemini REACT loop — uses Gemini-specific function_response protocol."""
        from google.genai import types

        client = self._build_client()
        _, contents = self._build_contents(system_prompt, initial_messages)

        generate_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
        )
        self._apply_output_limits(generate_config, max_tokens)

        declarations = self.get_tool_declarations(tool_schemas)
        if declarations:
            generate_config.tools = [types.Tool(function_declarations=declarations)]

        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_latency_ms = 0
        combined_output = ""
        all_function_calls_log = []

        for turn in range(max_react_turns):
            start = time.monotonic()
            try:
                response = await client.aio.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=generate_config,
                )
            except Exception as e:
                if "ValidationError" in type(e).__name__ and "finish_reason" in str(e):
                    logger.warning(
                        f"SDK finish_reason validation error on REACT turn {turn}. "
                        f"Treating as end-of-turn. Error: {e}"
                    )
                    # Treat unknown finish_reason as a stop signal
                    break
                raise
            latency_ms = int((time.monotonic() - start) * 1000)
            total_latency_ms += latency_ms
            self._warn_if_truncated(response, max_tokens)

            usage = response.usage_metadata
            total_prompt_tokens += getattr(usage, "prompt_token_count", 0) or 0
            total_completion_tokens += getattr(usage, "candidates_token_count", 0) or 0

            turn_text = ""
            function_calls = []
            model_parts = []

            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    model_parts.append(part)
                    if hasattr(part, "function_call") and part.function_call:
                        function_calls.append({
                            "name": part.function_call.name,
                            "args": dict(part.function_call.args) if part.function_call.args else {},
                        })
                    elif hasattr(part, "text") and part.text:
                        turn_text += part.text

            if not turn_text and not function_calls and response.text:
                turn_text = response.text

            # Append model turn
            contents.append(types.Content(role="model", parts=model_parts))

            if function_calls:
                all_function_calls_log.extend(function_calls)
                # Execute tools
                tool_results = await execute_tool_fn(function_calls)

                # Build function response parts (Gemini protocol)
                response_parts = [
                    types.Part.from_function_response(
                        name=tr["tool"],
                        response={"output": str(tr["output"]), "success": tr["success"]},
                    )
                    for tr in tool_results
                ]
                contents.append(types.Content(role="user", parts=response_parts))
                if turn_text:
                    combined_output += turn_text
                continue
            else:
                combined_output += turn_text
                break

        return LLMResponse(
            output=combined_output,
            function_calls=all_function_calls_log,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            latency_ms=total_latency_ms,
            model_name=self.model_name,
            provider=self._provider_name,
        )

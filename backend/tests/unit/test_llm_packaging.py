"""Every provider the router can route to has its SDK declared (P9.2 — LP-07).

``AnthropicAdapter`` was complete and wired into the factory, and the setup
guide explained how to configure it, but ``anthropic`` was not a dependency:
the first call raised "anthropic package not installed".
"""
from __future__ import annotations

import pathlib
import tomllib

from src.ai.llm.anthropic_adapter import AnthropicAdapter

BACKEND = pathlib.Path(__file__).resolve().parents[2]


def test_every_provider_sdk_is_declared():
    deps = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["poetry"]["dependencies"]
    assert {"google-genai", "anthropic", "openai"} <= set(deps)


def test_the_anthropic_adapter_builds_its_vertex_client():
    adapter = AnthropicAdapter(api_key="", model_name="claude-sonnet-4-5",
                               service_metadata={"project_id": "p", "region": "us-east5"})
    client = adapter._build_client()
    assert type(client).__name__ == "AsyncAnthropicVertex"
    assert client.max_retries == 0  # retries are ai/llm/retry.py's (LP-03)

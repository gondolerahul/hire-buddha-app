"""
tests/harness/mock_llm.py — Mock LLM router for hermetic tests.

A test fixture file maps ``(task_type, prompt_hash)`` keys to recorded
``LLMResponse`` payloads. When a test asks the mock for an LLM call
that has no fixture, the mock falls back to a deterministic stub
generator so the run still terminates (with a clear "STUB:" prefix in
the output) rather than throwing.

Both modes are needed:
  * Recording a golden snapshot uses the real LLM router, captures
    prompts + responses, writes the fixture, and later replays.
  * Pure unit tests for the loop / critic / planner code construct
    a ``MockLLMRouter(fixtures={...})`` inline and assert on the
    *prompt shape*, not the response text.

The mock matches the surface of ``src.ai.llm.router.LLMRouter`` only
loosely — production code should depend on a narrow interface, not the
concrete router. Track 2 (AgentLoop) will use this fixture to test the
loop without burning credits.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Lightweight response wrapper — production code uses
# ``src.ai.llm.types.LLMResponse`` but we don't want to import the heavy
# router module from tests/harness/ (keeps the harness importable even
# when half the kernel is broken mid-refactor).
# ---------------------------------------------------------------------------


@dataclass
class MockLLMResponse:
    output: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    model_name: str = "mock-model"
    model_provider: str = "mock"
    metadata: dict[str, Any] = field(default_factory=dict)


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


@dataclass
class MockLLMRouter:
    """Returns recorded responses by ``(task_type, prompt_hash)`` key.

    Fixtures shape on disk (``backend/tests/fixtures/llm/<name>.json``):

      {
        "fixtures": {
          "PLANNING:abc12345": {
            "output": "[ ... json plan ... ]",
            "prompt_tokens": 412,
            "completion_tokens": 89,
            "cost_usd": 0.002,
            "model_name": "claude-sonnet-4-5"
          },
          ...
        }
      }
    """
    fixtures: dict[str, MockLLMResponse] = field(default_factory=dict)
    strict: bool = False                  # raise on miss instead of stubbing
    calls: list[dict[str, Any]] = field(default_factory=list)   # call log

    # ------------------------------------------------------------------
    # construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: Path, *, strict: bool = False) -> "MockLLMRouter":
        data = json.loads(Path(path).read_text())
        fx_raw = data.get("fixtures", {})
        fixtures = {k: MockLLMResponse(**v) for k, v in fx_raw.items()}
        return cls(fixtures=fixtures, strict=strict)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fixtures": {
                k: {
                    "output": v.output,
                    "prompt_tokens": v.prompt_tokens,
                    "completion_tokens": v.completion_tokens,
                    "cost_usd": v.cost_usd,
                    "latency_ms": v.latency_ms,
                    "model_name": v.model_name,
                    "model_provider": v.model_provider,
                    "metadata": v.metadata,
                }
                for k, v in self.fixtures.items()
            }
        }
        path.write_text(json.dumps(payload, indent=2))

    def record(self, task_type: str, prompt: str, response: MockLLMResponse) -> None:
        self.fixtures[f"{task_type}:{_hash_prompt(prompt)}"] = response

    # ------------------------------------------------------------------
    # core lookup
    # ------------------------------------------------------------------

    async def call_llm(
        self,
        *,
        task_type: str,
        system_prompt: str = "",
        user_prompt: str = "",
        **kw: Any,
    ) -> MockLLMResponse:
        key = f"{task_type}:{_hash_prompt(user_prompt)}"
        self.calls.append({
            "task_type": task_type,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "key": key,
            "kw": dict(kw),
        })
        if key in self.fixtures:
            return self.fixtures[key]
        if self.strict:
            raise LookupError(
                f"MockLLMRouter has no fixture for {key!r}. "
                f"Add it to fixtures or pass strict=False."
            )
        return _stub_response(task_type, user_prompt)

    # Some callers will use a sync helper too.
    def call_llm_sync(self, *, task_type: str, **kw: Any) -> MockLLMResponse:
        import asyncio

        return asyncio.run(self.call_llm(task_type=task_type, **kw))


# ---------------------------------------------------------------------------
# Deterministic stub generator
# ---------------------------------------------------------------------------


def _stub_response(task_type: str, prompt: str) -> MockLLMResponse:
    """Construct a stub response that lets the run terminate.

    The output is deliberately *parseable* for the common task types so
    that downstream JSON-extraction logic doesn't choke before the test
    can assert on something useful.
    """
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
    if task_type.upper().startswith("PLANNING"):
        body = (
            '[{"step_id":"step_1","order":1,"name":"stub step",'
            '"description":"deterministic stub","type":"ACTION","required":true}]'
        )
    elif task_type.upper().startswith(("REVIEW", "CRITIC")):
        body = (
            '{"passed":true,"reason":"stub critic — no fixture",'
            '"suggestion":""}'
        )
    else:
        body = f"STUB::{task_type}::{digest}"

    return MockLLMResponse(
        output=body,
        prompt_tokens=max(len(prompt) // 4, 1),
        completion_tokens=max(len(body) // 4, 1),
        cost_usd=0.0,                       # stubs are free
        latency_ms=1,
        model_name="mock-stub",
        model_provider="mock",
        metadata={"stub": True, "task_type": task_type},
    )

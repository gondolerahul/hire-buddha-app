"""A synthesized tool runs in the sandbox with its context, once installed (TL-02).

The test harness called ``inst.run(input)``, so the tool context never reached
a synthesized tool, and ``SandboxedSynthesizedTool`` replayed the whole harness
on every production call — six files written and graded per call. Now the
harness calls ``run_with_context`` with the call's server-minted context, and a
call execs a small driver beside the tool's files, which are written once per
version under the read-only ``.skills/`` root.

The sandbox exec is the host interpreter here (the same argv the runtime
gets); the real container is ``tests/integration/test_container_runtime_docker.py``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.ai.schemas.tools import NetworkPolicy, ToolExample, ToolSpec
from src.ai.tools.sandbox.runtime import ExecResult
from src.ai.tools.sandbox.synthesized_tool import SandboxedSynthesizedTool

CONTEXT_SRC = '''
import json
from src.ai.tools.base import Tool


class WhoTool(Tool):
    name = "who_tool"

    async def run(self, input_data):
        return "no context"

    async def run_with_context(self, input_data, context=None):
        return json.dumps({"input": input_data, "context": context})
'''

FAILING_SRC = '''
from src.ai.tools.base import Tool


class BrokenTool(Tool):
    name = "who_tool"

    async def run(self, input_data):
        raise ValueError("bad input")
'''

CTX = {"company_id": "00000000-0000-0000-0000-0000000000c2", "run_id": "r-9", "user_id": "u-1",
       "__agent_state__": {"iteration": 3}, "__is_meta_agent__": True}


def _spec(policy: NetworkPolicy = NetworkPolicy.NONE) -> ToolSpec:
    return ToolSpec(name="who_tool", description="d", network_policy=policy,
                    examples=[ToolExample(input="hello", expected_contains="hello")])


@pytest.fixture
def execs(monkeypatch, tmp_path) -> List[Dict[str, Any]]:
    """Run the sandbox exec with this interpreter; record each call."""
    from src.ai.tools.sandbox import runtime
    from src.common.config import settings

    monkeypatch.setattr(settings, "SANDBOX_WORKSPACE_ROOT", str(tmp_path), raising=False)
    calls: List[Dict[str, Any]] = []

    async def _exec(context, argv, *, cwd=None, timeout=30.0, env=None, network="none"):
        calls.append({"argv": list(argv), "cwd": cwd, "network": network})
        proc = subprocess.run([sys.executable, *argv[1:]], cwd=cwd, capture_output=True, text=True,
                              timeout=timeout)
        return ExecResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)

    monkeypatch.setattr(runtime, "run_sandbox_exec", _exec)
    return calls


@pytest.mark.asyncio
async def test_a_call_reaches_the_tool_with_its_context(execs) -> None:
    out = json.loads(await SandboxedSynthesizedTool(_spec(), CONTEXT_SRC).run_with_context("hello", CTX))
    assert out["input"] == "hello"
    assert out["context"] == {"company_id": CTX["company_id"], "run_id": "r-9", "user_id": "u-1"}


@pytest.mark.asyncio
async def test_the_tool_is_installed_once_and_a_call_leaves_nothing(execs, tmp_path) -> None:
    tool = SandboxedSynthesizedTool(_spec(), CONTEXT_SRC)
    await tool.run_with_context("a", CTX)
    await tool.run_with_context("b", CTX)
    first, second = execs
    driver = first["argv"][1]
    assert second["argv"][1] == driver
    skills = os.path.join(str(tmp_path), CTX["company_id"], ".skills", ".synth", "who_tool")
    assert os.path.commonpath([os.path.realpath(driver), os.path.realpath(skills)]) == os.path.realpath(skills)
    assert sorted(os.listdir(os.path.dirname(driver))) == [".content-hash", "_call.py", "src", "synth_tool.py"]
    assert not os.path.exists(first["cwd"]) and not os.path.exists(second["cwd"])


@pytest.mark.asyncio
@pytest.mark.parametrize("policy, network", [(NetworkPolicy.NONE, "none"),
                                             (NetworkPolicy.ALLOWLIST, "allowlist"),
                                             (NetworkPolicy.FULL, "none")])
async def test_a_call_runs_under_the_tools_declared_policy(execs, policy, network) -> None:
    await SandboxedSynthesizedTool(_spec(policy), CONTEXT_SRC).run_with_context("x", CTX)
    assert execs[0]["network"] == network


@pytest.mark.asyncio
async def test_a_tool_that_raises_is_an_error(execs) -> None:
    out = json.loads(await SandboxedSynthesizedTool(_spec(), FAILING_SRC).run_with_context("x", CTX))
    assert out == {"error": "ValueError: bad input"}


@pytest.mark.asyncio
async def test_a_call_without_a_company_is_refused(execs) -> None:
    out = json.loads(await SandboxedSynthesizedTool(_spec(), CONTEXT_SRC).run_with_context("x", {}))
    assert "no company" in out["error"] and execs == []


@pytest.mark.asyncio
async def test_the_harness_tests_the_tool_with_its_context(tmp_path) -> None:
    from src.ai.meta.tool_sandbox_tester import ToolSandboxTester

    async def _exec(context, argv, *, cwd=None, timeout=30.0, env=None, network="none"):
        proc = subprocess.run([sys.executable, "_harness.py"], cwd=cwd, capture_output=True, text=True,
                              timeout=timeout)
        return SimpleNamespace(exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)

    spec = _spec().model_copy(update={"examples": [ToolExample(input="hi", expected_contains="r-9")]})
    report = await ToolSandboxTester().run_examples(CONTEXT_SRC, spec, CTX, exec_fn=_exec,
                                                    workdir=str(tmp_path))
    assert report.ok, report.summary()
    assert "__agent_state__" not in report.outcomes[0].output

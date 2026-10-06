"""A sandbox call's network policy reaches its container (TL-15, TL-18).

``ContainerRuntime.exec`` used to ensure the tenant container with no network
argument, so every container ran ``--network none`` and a synthesized tool that
declared ``ALLOWLIST`` could never reach its hosts: the egress proxy had no
caller. Hermetic: the manager's docker calls are recorded, not run. The real
allow/deny behaviour is ``test_container_runtime_docker.py``.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List

import pytest

from src.ai.schemas.tools import NetworkPolicy, ToolExample, ToolSpec
from src.ai.tools.sandbox import runtime as runtime_mod
from src.ai.tools.sandbox.container_runtime import ContainerRuntime
from src.ai.tools.sandbox.runtime import ExecResult, run_sandbox_exec
from src.ai.tools.sandbox.tenant_manager import TenantSandboxManager


@pytest.fixture
def ensured(monkeypatch) -> List[Any]:
    """Container mode on; record each ``ensure`` and answer the exec."""
    seen: List[Any] = []

    async def _on(_cid):
        return True

    async def _ensure(self, company_id, *, network="none"):
        seen.append((company_id, network))
        return TenantSandboxManager.container_name(company_id, network=network)

    async def _exec(self, argv, **_kw):
        await self.manager.ensure(self.company_id, network=self.network)
        return ExecResult(returncode=0, stdout="ok")

    async def _no_meter(*_a, **_k):
        return None

    from src.ai.tools.sandbox import metering

    monkeypatch.setattr(runtime_mod, "container_runtime_enabled", _on)
    monkeypatch.setattr(TenantSandboxManager, "ensure", _ensure)
    monkeypatch.setattr(ContainerRuntime, "exec", _exec)
    monkeypatch.setattr(metering, "meter_sandbox_usage", _no_meter)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("network", ["none", "allowlist", "web"])
async def test_the_calls_network_reaches_the_container(ensured, network) -> None:
    await run_sandbox_exec({"company_id": "c1"}, ["true"], network=network)
    assert ensured == [("c1", network)]


@pytest.mark.asyncio
async def test_a_call_with_no_policy_has_no_network(ensured) -> None:
    await run_sandbox_exec({"company_id": "c1"}, ["true"])
    assert ensured == [("c1", "none")]


def test_each_policy_has_its_own_container() -> None:
    """A running container's network is fixed, so code that must have no
    network never shares a container with an allow-listed call."""
    names = {TenantSandboxManager.container_name("c1", network=n) for n in ("none", "allowlist", "web")}
    assert names == {"hb-sandbox-c1", "hb-sandbox-c1-allowlist", "hb-sandbox-c1-web"}


@pytest.mark.asyncio
async def test_an_unknown_policy_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown sandbox network policy"):
        await TenantSandboxManager().ensure("c1", network="full")


@pytest.mark.asyncio
async def test_destroy_removes_every_container_of_the_company(monkeypatch) -> None:
    mgr = TenantSandboxManager()
    removed: List[str] = []

    async def _docker(*args, **_kw):
        if args[:2] == ("rm", "-f"):
            removed.append(args[2])
        return (0, "", "")

    monkeypatch.setattr(mgr, "_docker", _docker)
    await mgr.destroy("c1")
    assert removed == ["hb-sandbox-c1", "hb-sandbox-c1-allowlist", "hb-sandbox-c1-web"]


@pytest.mark.asyncio
@pytest.mark.parametrize("policy, network", [
    (NetworkPolicy.NONE, "none"),
    (NetworkPolicy.ALLOWLIST, "allowlist"),
    (NetworkPolicy.FULL, "none"),  # never granted to a synthesized tool
])
async def test_a_synthesized_tool_runs_under_its_declared_policy(tmp_path, policy, network) -> None:
    from src.ai.meta.tool_sandbox_tester import ToolSandboxTester

    seen = {}

    async def _exec(context, argv, *, cwd=None, timeout=30.0, env=None, network="none"):
        seen["network"] = network
        return SimpleNamespace(exit_code=0, stdout='___HARNESS___[]', stderr="")

    spec = ToolSpec(name="probe_tool", description="d", network_policy=policy,
                    examples=[ToolExample(input="x")])
    await ToolSandboxTester().run_examples("", spec, {"company_id": "c1"},
                                           exec_fn=_exec, workdir=str(tmp_path))
    assert seen["network"] == network

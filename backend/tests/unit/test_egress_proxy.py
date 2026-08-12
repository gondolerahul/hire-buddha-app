"""Egress proxy wiring — Phase 12 `02`/`06` (hermetic).

Mocks the docker CLI to assert the argv the EgressProxyManager and the
egress-mode TenantSandboxManager build: the internal network is created
``--internal``, the proxy is dual-homed, and an egress sandbox joins the
internal network with HTTP(S)_PROXY injected. The real allow/deny behavior is
covered by the Docker-gated integration test.
"""
from __future__ import annotations

from typing import List, Tuple

import pytest

from src.ai.tools.sandbox.egress_proxy import EgressProxyManager
from src.ai.tools.sandbox.tenant_manager import TenantSandboxManager


class _DockerRecorder:
    """Fake _docker: records argv; returns rc=1 for inspect/status (absent)."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, ...]] = []

    async def __call__(self, *args: str, timeout: float = 60.0, check: bool = True) -> Tuple[int, str, str]:
        self.calls.append(args)
        # inspect / status probes → "absent" so the create paths run.
        if args[:1] == ("inspect",) or args[:2] == ("network", "inspect"):
            return (1, "", "")
        return (0, "", "")

    def find(self, *needles: str) -> List[Tuple[str, ...]]:
        return [c for c in self.calls if all(n in c for n in needles)]


@pytest.mark.asyncio
async def test_proxy_ensure_creates_networks_and_dual_homes(monkeypatch) -> None:
    mgr = EgressProxyManager(
        internal_network="hb-egress-internal",
        uplink_network="hb-egress-uplink",
        allowlist="googleapis.com",
    )
    rec = _DockerRecorder()
    monkeypatch.setattr(mgr, "_docker", rec)

    url = await mgr.ensure()

    assert url == f"http://hb-egress-proxy:{mgr.proxy_port}"
    # internal network created with --internal; uplink without it.
    assert rec.find("network", "create", "--internal", "hb-egress-internal")
    uplink = rec.find("network", "create", "hb-egress-uplink")
    assert uplink and not any("--internal" in c for c in uplink)
    # proxy launched on the uplink with the allow-list env...
    run = rec.find("run", "hb-egress-proxy")
    assert run
    assert any("ALLOWLIST=googleapis.com" in c for c in run)
    assert any("hb-egress-uplink" in c for c in run)
    # ...then dual-homed onto the internal network.
    assert rec.find("network", "connect", "hb-egress-internal", "hb-egress-proxy")


@pytest.mark.asyncio
async def test_proxy_ensure_idempotent_when_running(monkeypatch) -> None:
    mgr = EgressProxyManager()

    async def fake_docker(*args, timeout=60.0, check=True):
        if args[:2] == ("network", "inspect"):
            return (0, "", "")  # networks already exist
        if args[:1] == ("inspect",):
            return (0, "running\n", "")  # proxy already running
        raise AssertionError(f"unexpected docker call: {args}")

    monkeypatch.setattr(mgr, "_docker", fake_docker)
    url = await mgr.ensure()
    assert url.endswith(str(mgr.proxy_port))


def test_container_name_egress_suffix() -> None:
    assert TenantSandboxManager.container_name("c1") == "hb-sandbox-c1"
    assert TenantSandboxManager.container_name("c1", egress=True) == "hb-sandbox-c1-egress"


@pytest.mark.asyncio
async def test_sandbox_ensure_egress_uses_internal_net_and_proxy_env(monkeypatch) -> None:
    mgr = TenantSandboxManager()
    rec = _DockerRecorder()
    monkeypatch.setattr(mgr, "_docker", rec)
    monkeypatch.setattr(mgr, "_mounts", lambda company_id: [])

    async def fake_proxy_ensure(self):
        return "http://hb-egress-proxy:8888"

    monkeypatch.setattr(EgressProxyManager, "ensure", fake_proxy_ensure)

    name = await mgr.ensure("acme", egress=True)
    assert name == "hb-sandbox-acme-egress"

    run = rec.find("run", "hb-sandbox-acme-egress")
    assert run
    flat = run[0]
    # joined the internal egress network, not --network none.
    assert "hb-egress-internal" in flat
    assert "none" not in flat[flat.index("--network") + 1]
    # proxy env injected (all four casings).
    assert flat.count("HTTP_PROXY=http://hb-egress-proxy:8888") == 1
    assert any("https_proxy=http://hb-egress-proxy:8888" in tok for tok in flat)


@pytest.mark.asyncio
async def test_sandbox_ensure_default_is_network_none(monkeypatch) -> None:
    mgr = TenantSandboxManager()
    rec = _DockerRecorder()
    monkeypatch.setattr(mgr, "_docker", rec)
    monkeypatch.setattr(mgr, "_mounts", lambda company_id: [])

    name = await mgr.ensure("acme")
    assert name == "hb-sandbox-acme"
    run = rec.find("run", "hb-sandbox-acme")[0]
    assert run[run.index("--network") + 1] == "none"
    assert not any("PROXY" in tok for tok in run)

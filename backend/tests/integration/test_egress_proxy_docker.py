"""Egress proxy end-to-end against real Docker — Phase 12 `02`/`06`.

Docker-gated (skips without a daemon + the hb-egress-proxy:local image). Stands
up the proxy + networks via EgressProxyManager and proves the security property:
an allow-listed host is reachable from the internal network through the proxy,
a non-allow-listed host is refused, and there is no direct egress without the
proxy. Uses busybox ``wget`` (honors http_proxy, no package install — which the
internal network couldn't do anyway).
"""
from __future__ import annotations

import shutil
import subprocess
import uuid

import pytest
import pytest_asyncio

from src.ai.tools.sandbox.egress_proxy import EgressProxyManager

_PROXY_IMAGE = "hb-egress-proxy:local"
_CLIENT_IMAGE = "alpine:3.20"


def _docker_ok() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(
            ["docker", "info"], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=15,
        ).returncode == 0
    except Exception:
        return False


def _image_present(image: str) -> bool:
    try:
        return subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
        ).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_ok() or not _image_present(_PROXY_IMAGE),
    reason="Docker unavailable or hb-egress-proxy:local image absent "
           "(build: docker build -t hb-egress-proxy:local backend/docker/egress-proxy)",
)


@pytest_asyncio.fixture()
async def proxy():
    # Unique network names so a failed prior run never collides.
    tag = uuid.uuid4().hex[:8]
    mgr = EgressProxyManager(
        internal_network=f"hb-egress-internal-{tag}",
        uplink_network=f"hb-egress-uplink-{tag}",
        allowlist="example.com",
    )
    await mgr.ensure()
    try:
        yield mgr
    finally:
        await mgr.destroy()


def _wget(network: str, url: str, *, proxy_url: str | None = None) -> int:
    env = []
    if proxy_url:
        env = ["-e", f"http_proxy={proxy_url}", "-e", f"https_proxy={proxy_url}"]
    return subprocess.run(
        ["docker", "run", "--rm", "--network", network, *env, _CLIENT_IMAGE,
         "wget", "-q", "-T", "20", "-O", "/dev/null", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
    ).returncode


@pytest.mark.integration
def test_allowlisted_host_reachable_through_proxy(proxy) -> None:
    rc = _wget(proxy.internal_network, "https://example.com", proxy_url=proxy.proxy_url)
    assert rc == 0, "allow-listed host should be reachable via the proxy"


@pytest.mark.integration
def test_non_allowlisted_host_blocked(proxy) -> None:
    rc = _wget(proxy.internal_network, "https://api.github.com", proxy_url=proxy.proxy_url)
    assert rc != 0, "non-allow-listed host must be refused by the proxy"


@pytest.mark.integration
def test_no_direct_egress_without_proxy(proxy) -> None:
    # On the --internal network with no proxy env there is no route at all.
    rc = _wget(proxy.internal_network, "https://example.com")
    assert rc != 0, "internal network must have no direct internet route"

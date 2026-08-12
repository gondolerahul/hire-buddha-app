"""ContainerRuntime end-to-end against a real Docker daemon — Phase 12 `02` S4.

Docker-gated: the whole module skips when Docker is unavailable, so CI and the
hermetic unit suite never need a daemon (they ride SubprocessRuntime + the mocked
tests in tests/unit/test_container_runtime.py).

To stay fast and avoid a network pull of the heavy hb-sandbox image, these tests
build a tiny local image (``FROM backend-app:latest`` + a ``sleep infinity`` CMD)
that already carries python3 and coreutils ``timeout`` — the two things the
runtime's exec path needs. The real hb-sandbox image is byte-compatible with this
contract; building/verifying it is a documented ops step (docker/sandbox/README.md).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid

import pytest
import pytest_asyncio

from src.ai.tools.sandbox.container_runtime import ContainerRuntime
from src.ai.tools.sandbox.tenant_manager import (
    TenantSandboxConfig,
    TenantSandboxManager,
)

_TEST_IMAGE = "hb-sandbox-test:local"
_BASE_IMAGE = "backend-app:latest"


def _docker_ok() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        ).returncode == 0
    except Exception:
        return False


def _base_present() -> bool:
    try:
        return subprocess.run(
            ["docker", "image", "inspect", _BASE_IMAGE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        ).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_ok() or not _base_present(),
    reason="Docker unavailable or backend-app:latest base image absent",
)


@pytest.fixture(scope="module")
def test_image() -> str:
    stage = tempfile.mkdtemp()
    with open(os.path.join(stage, "Dockerfile"), "w") as fh:
        fh.write(f'FROM {_BASE_IMAGE}\nUSER root\nCMD ["sleep", "infinity"]\n')
    subprocess.run(
        ["docker", "build", "-t", _TEST_IMAGE, stage],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=180,
    )
    shutil.rmtree(stage, ignore_errors=True)
    return _TEST_IMAGE


@pytest_asyncio.fixture
async def runtime(test_image):  # type: ignore[no-untyped-def]
    company_id = f"itest-{uuid.uuid4().hex[:12]}"
    cfg = TenantSandboxConfig(image=test_image, network="none")
    mgr = TenantSandboxManager(config=cfg)
    rt = ContainerRuntime(company_id=company_id, manager=mgr)
    try:
        yield rt
    finally:
        await rt.destroy()


def _host_dir(company_id: str) -> str:
    return os.path.join(tempfile.gettempdir(), "sandbox", company_id)


@pytest.mark.asyncio
async def test_exec_runs_in_container(runtime) -> None:
    res = await runtime.exec(["python3", "-c", "print('in-container', 6*7)"])
    assert res.ok, res.stderr
    assert "in-container 42" in res.stdout


@pytest.mark.asyncio
async def test_bind_mount_identical_path(runtime) -> None:
    host_dir = _host_dir(runtime.company_id)
    # Materialize a script on the host; the container sees it at the same path.
    await runtime.exec(["python3", "-c", "print('warm')"])  # ensure container
    script = os.path.join(host_dir, "job.py")
    with open(script, "w") as fh:
        fh.write("print('from bind mount')\n")
    res = await runtime.exec(["python3", script], cwd=host_dir)
    assert res.ok, res.stderr
    assert "from bind mount" in res.stdout


@pytest.mark.asyncio
async def test_network_default_deny(runtime) -> None:
    res = await runtime.exec(
        [
            "python3",
            "-c",
            "import socket; socket.create_connection(('1.1.1.1', 53), 2)",
        ],
        timeout=10,
    )
    assert res.returncode != 0
    assert res.ok is False


@pytest.mark.asyncio
async def test_exec_timeout_is_enforced_in_container(runtime) -> None:
    res = await runtime.exec(["sleep", "30"], timeout=2)
    assert res.timed_out is True
    assert res.ok is False


@pytest.mark.asyncio
async def test_lifecycle_pause_resume_destroy(runtime) -> None:
    mgr = runtime.manager
    name = await mgr.ensure(runtime.company_id)
    assert await mgr._status(name) == "running"
    await runtime.pause()
    assert await mgr._status(name) == "paused"
    await runtime.resume()
    assert await mgr._status(name) == "running"
    await runtime.destroy()
    assert await mgr._status(name) is None

"""ContainerRuntime end-to-end against a real Docker daemon and the real
``hb-sandbox`` image (Phase 12 `02` S4; P11).

Docker-gated: the module skips when Docker or the image is unavailable, so CI
and the hermetic unit suite never need a daemon (they ride SubprocessRuntime +
the mocked tests in tests/unit/test_container_runtime.py). Build the image with
``backend/docker/sandbox/build.sh``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest
import pytest_asyncio

from src.ai.tools.sandbox.container_runtime import ContainerRuntime
from src.ai.tools.sandbox.tenant_manager import (
    TenantSandboxConfig,
    TenantSandboxManager,
)
from src.ai.tools.sandbox.workspace import company_roots, skills_root, tenant_workspace

_IMAGE = "hb-sandbox:local"


def _docker_ok() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(
            ["docker", "image", "inspect", _IMAGE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        ).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _docker_ok(), reason=f"Docker or {_IMAGE} unavailable")


@pytest_asyncio.fixture
async def runtime():  # type: ignore[no-untyped-def]
    company_id = f"itest-{uuid.uuid4().hex[:12]}"
    cfg = TenantSandboxConfig(image=_IMAGE, network="none")
    rt = ContainerRuntime(company_id=company_id, manager=TenantSandboxManager(config=cfg))
    try:
        yield rt
    finally:
        await rt.destroy()
        for root in company_roots(company_id):
            shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_exec_runs_in_container(runtime) -> None:
    res = await runtime.exec(["python3", "-c", "print('in-container', 6*7)"])
    assert res.ok, res.stderr
    assert "in-container 42" in res.stdout


@pytest.mark.asyncio
async def test_the_workspace_is_the_same_files_on_both_sides(runtime) -> None:
    host_dir = tenant_workspace(runtime.company_id)
    await runtime.exec(["python3", "-c", "print('warm')"])  # creates the dirs
    script = os.path.join(host_dir, "job.py")
    with open(script, "w") as fh:
        fh.write("import os; open('made-inside.txt','w').write('x'); print(os.getcwd())\n")
    res = await runtime.exec(["python3", script], cwd=host_dir)
    assert res.ok, res.stderr
    assert os.path.exists(os.path.join(host_dir, "made-inside.txt"))
    # The path the code printed is the host's path (translated back on Windows).
    assert os.path.normcase(os.path.normpath(res.stdout.strip())) == os.path.normcase(os.path.normpath(host_dir))


@pytest.mark.asyncio
async def test_skill_files_are_read_only_inside(runtime) -> None:
    """TL-16: tenant code cannot rewrite the files a published version ships."""
    skills = skills_root(runtime.company_id)
    await runtime.exec(["true"])
    with open(os.path.join(skills, "tool.py"), "w") as fh:
        fh.write("print('shipped')\n")
    res = await runtime.exec(["python3", os.path.join(skills, "tool.py")])
    assert res.ok and "shipped" in res.stdout, res.stderr
    write = await runtime.exec(["sh", "-c", f"echo evil > {os.path.join(skills, 'tool.py')}"])
    assert write.returncode != 0 and "Read-only" in write.stderr


@pytest.mark.asyncio
async def test_the_companys_artifacts_are_readable_not_writable(runtime) -> None:
    """TL-17: a tool may read an artifact the model names; nothing writes there."""
    system_dir = company_roots(runtime.company_id)[1]
    os.makedirs(system_dir, exist_ok=True)
    with open(os.path.join(system_dir, "clip.txt"), "w") as fh:
        fh.write("frames")
    await runtime.exec(["true"])
    read = await runtime.exec(["cat", os.path.join(system_dir, "clip.txt")])
    assert read.ok and read.stdout == "frames", read.stderr
    write = await runtime.exec(["sh", "-c", f"touch {os.path.join(system_dir, 'x')}"])
    assert write.returncode != 0


@pytest.mark.asyncio
async def test_network_default_deny(runtime) -> None:
    res = await runtime.exec(
        ["python3", "-c", "import socket; socket.create_connection(('1.1.1.1', 53), 2)"],
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

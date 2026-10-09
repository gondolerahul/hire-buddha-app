"""ContainerRuntime end-to-end against a real Docker daemon and the real
``hb-sandbox`` image (Phase 12 `02` S4; P11).

Docker-gated: the module skips when Docker or the image is unavailable, so CI
and the hermetic unit suite never need a daemon (they ride SubprocessRuntime +
the mocked tests in tests/unit/test_container_runtime.py). Build the image with
``backend/docker/sandbox/build.sh``.
"""
from __future__ import annotations

import json
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


pytestmark = [pytest.mark.docker,
              pytest.mark.skipif(not _docker_ok(), reason=f"Docker or {_IMAGE} unavailable")]


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


@pytest.mark.asyncio
async def test_terminal_keeps_what_the_command_put_in_the_drop_box(monkeypatch) -> None:
    """TL-36, in the real container: $ARTIFACTS_DIR is a host directory the
    command writes into; that file is kept, a file elsewhere is not."""
    import json
    from types import SimpleNamespace

    import src.ai.artifact_service as artifacts
    import src.ai.tools.sandbox.runtime as runtime_mod
    from src.ai.tools.sandbox.terminal_tool import TerminalTool
    from src.common.config import settings

    async def on(_company_id):
        return True

    kept = []

    async def save(context, **kw):
        kept.append(kw["file_name"])
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(runtime_mod, "container_runtime_enabled", on)
    monkeypatch.setattr(settings, "SANDBOX_IMAGE", _IMAGE)
    monkeypatch.setattr(artifacts, "save_tool_output", save)
    company_id = f"itest-{uuid.uuid4().hex[:12]}"
    try:
        out = json.loads(await TerminalTool().run_with_context(json.dumps({
            "command": 'echo report > "$ARTIFACTS_DIR/report.txt" && echo junk > not-kept.txt && echo done',
        }), {"company_id": company_id, "run_id": str(uuid.uuid4())}))
        assert out["exit_code"] == 0, out
        assert kept == ["report.txt"]
        assert "report.txt" in out["artifacts"]
        assert os.path.exists(os.path.join(tenant_workspace(company_id), "not-kept.txt"))
    finally:
        await TenantSandboxManager().destroy(company_id)
        for root in company_roots(company_id):
            shutil.rmtree(root, ignore_errors=True)


_PROBE = (
    "import sys, urllib.request\n"
    "try:\n"
    "    urllib.request.urlopen(sys.argv[1], timeout=15)\n"
    "    print('reached')\n"
    "except Exception as exc:\n"
    "    print('refused', type(exc).__name__, exc)\n"
)


@pytest.mark.asyncio
async def test_an_allowlist_call_reaches_only_the_allowlist() -> None:
    """TL-15: the call's network policy reaches the container. An allowlist
    container's only way out is the proxy, which passes only the allow-list."""
    if subprocess.run(["docker", "image", "inspect", "hb-egress-proxy:local"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        pytest.skip("hb-egress-proxy:local not built")
    company_id = f"itest-{uuid.uuid4().hex[:12]}"
    rt = ContainerRuntime(company_id=company_id, network="allowlist",
                          manager=TenantSandboxManager(config=TenantSandboxConfig(image=_IMAGE)))
    try:
        allowed = await rt.exec(["python3", "-c", _PROBE, "https://www.google.com/"], timeout=40)
        other = await rt.exec(["python3", "-c", _PROBE, "https://example.com/"], timeout=40)
        direct = await rt.exec(["python3", "-c",
                                "import socket; socket.create_connection(('1.1.1.1', 443), 3); print('direct')"],
                               timeout=20)
        assert "reached" in allowed.stdout, allowed.stdout + allowed.stderr
        assert "refused" in other.stdout, other.stdout
        assert "direct" not in direct.stdout              # the internal network has no route out
        assert await rt.manager._status(f"hb-sandbox-{company_id}-allowlist") == "running"
    finally:
        await rt.manager.destroy(company_id)
        for root in company_roots(company_id):
            shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_the_browser_runs_in_the_container_behind_the_web_proxy() -> None:
    """TL-18: Chromium runs in the company's ``web`` container. Its only way out
    is the proxy that refuses internal addresses; a screenshot lands in the
    call's drop box."""
    if subprocess.run(["docker", "image", "inspect", "hb-egress-proxy:local"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        pytest.skip("hb-egress-proxy:local not built")
    from src.ai.tools.sandbox.workspace import drop_box_root

    company_id = f"itest-{uuid.uuid4().hex[:12]}"
    rt = ContainerRuntime(company_id=company_id,
                          manager=TenantSandboxManager(config=TenantSandboxConfig(image=_IMAGE)))
    out_dir = os.path.join(drop_box_root(company_id), "run", "call")
    os.makedirs(out_dir)
    try:
        public = await rt.run_browser({"steps": [{"action": "navigate", "url": "https://example.com/"},
                                                 {"action": "screenshot"}],
                                       "timeout_ms": 30000, "out_dir": out_dir}, timeout=150)
        assert [s["status"] for s in public["steps"]] == ["success", "success"], public
        assert public["steps"][0]["title"] == "Example Domain"
        assert os.listdir(out_dir) == [public["steps"][1]["file"]]

        for internal in ("http://169.254.169.254/latest/meta-data/", "http://hb-egress-proxy:8888/",
                         "http://localhost:8000/"):
            res = await rt.run_browser({"steps": [{"action": "navigate", "url": internal}],
                                        "timeout_ms": 15000}, timeout=90)
            [step] = res["steps"]
            assert step["status"] == "error", (internal, step)

        assert await rt.manager._status(f"hb-sandbox-{company_id}-web") == "running"
    finally:
        await rt.manager.destroy(company_id)
        for root in company_roots(company_id):
            shutil.rmtree(root, ignore_errors=True)


_WHO_SRC = '''
import json, os
from src.ai.tools.base import Tool


class WhoTool(Tool):
    name = "who_tool"

    async def run(self, input_data):
        return "no context"

    async def run_with_context(self, input_data, context=None):
        return json.dumps({"input": input_data, "run": (context or {}).get("run_id"),
                           "uid": os.getuid()})
'''


@pytest.mark.asyncio
async def test_a_synthesized_tool_runs_in_the_container_with_its_context(monkeypatch) -> None:
    """TL-02: a call execs the installed tool's driver in the tenant container,
    as the sandbox user, with the server-minted context."""
    from src.ai.schemas.tools import ToolSpec
    from src.ai.tools.sandbox import runtime as runtime_mod
    from src.ai.tools.sandbox.synthesized_tool import SandboxedSynthesizedTool
    from src.common.config import settings

    async def _on(_cid):
        return True

    monkeypatch.setattr(runtime_mod, "container_runtime_enabled", _on)
    monkeypatch.setattr(settings, "SANDBOX_IMAGE", _IMAGE, raising=False)
    company_id = f"itest-{uuid.uuid4().hex[:12]}"
    tool = SandboxedSynthesizedTool(ToolSpec(name="who_tool", description="d"), _WHO_SRC)
    try:
        out = json.loads(await tool.run_with_context("hello", {"company_id": company_id, "run_id": "r-1"}))
        assert out == {"input": "hello", "run": "r-1", "uid": 10001}
    finally:
        await TenantSandboxManager().destroy(company_id)
        for root in company_roots(company_id):
            shutil.rmtree(root, ignore_errors=True)

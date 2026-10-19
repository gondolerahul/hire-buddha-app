"""The sandbox on AKS without a cluster (Phase 14 WS6 6.1, tech spec §11.1).

The sandbox agent (``docker/sandbox/agent.py``) runs here as a process; a
played Kubernetes API says its pod is ready at 127.0.0.1. Through
``KubernetesSandboxRuntime``: the tool's script written in the platform's
workspace is synced in, run by the agent, and what it wrote comes back; host
paths in the output are host paths again; a call past its timeout is killed;
``pause`` saves the workspace to storage and deletes the pod, and the next
call makes a new pod and restores it; the idle reaper does the same for a pod
nobody used; the agent refuses a wrong token and paths outside its root.
"""
from __future__ import annotations

import base64
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

BACKEND = Path(__file__).resolve().parents[2]
TOKEN = "agent-token-for-tests"


class PlayedKube:
    def __init__(self):
        self.objects, self.patched, self.deleted = {}, [], []

    @staticmethod
    def _key(kind, namespace, name):
        return f"{kind}/{namespace}/{name}"

    async def apply(self, body):
        meta = body["metadata"]
        if body["kind"] == "Pod":
            body = {**body, "status": {"phase": "Running", "podIP": "127.0.0.1",
                                       "conditions": [{"type": "Ready", "status": "True"}]}}
        if body["kind"] == "Secret":
            body = {**body, "data": {k: base64.b64encode(v.encode()).decode()
                                     for k, v in body.get("stringData", {}).items()}}
        self.objects[self._key(body["kind"], meta.get("namespace"), meta["name"])] = body
        return body

    def _from_path(self, path):
        parts = path.strip("/").split("/")
        kind = {"pods": "Pod", "secrets": "Secret"}[parts[-2]]
        return self._key(kind, parts[-3], parts[-1])

    async def find(self, path):
        return self.objects.get(self._from_path(path))

    async def get(self, path):
        found = await self.find(path)
        if found is None:
            from src.common.platform.kube import KubeNotFound

            raise KubeNotFound(404, path)
        return found

    async def delete(self, path):
        self.deleted.append(path)
        return self.objects.pop(self._from_path(path), None) is not None

    async def patch(self, path, body):
        self.patched.append((path, body))
        found = self.objects.get(self._from_path(path))
        if found is not None:
            found["metadata"].setdefault("annotations", {}).update(body["metadata"]["annotations"])
        return found

    async def list(self, path, *, labels=None):
        return [o for k, o in self.objects.items() if k.startswith("Pod/")]


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest_asyncio.fixture
async def sandbox(monkeypatch, tmp_path):
    from src.ai.tools.sandbox import k8s_runtime
    from src.common.config import settings
    from src.common.platform.storage import set_storage
    from src.common.tenancy.directory import TenantLocation, directory
    from tests.harness.storage import MemoryStorage

    agent_root = tmp_path / "pod"
    agent_root.mkdir()
    port = _free_port()
    env = {**os.environ, "SANDBOX_ROOT": str(agent_root), "SANDBOX_AGENT_TOKEN": TOKEN,
           "SANDBOX_AGENT_PORT": str(port)}
    agent = subprocess.Popen([sys.executable, str(BACKEND / "docker" / "sandbox" / "agent.py")], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        agent.kill()
        pytest.fail("the sandbox agent did not start")

    company_id = str(uuid.uuid4())
    location = TenantLocation(company_id=uuid.UUID(company_id), key="tstsbx0001", server_host="localhost",
                              db_name="t_tstsbx0001", status="active", schema_version=None,
                              automation_state="running", timezone="UTC")

    async def _get(cid):
        return location

    monkeypatch.setattr(directory, "get", _get)
    monkeypatch.setattr(settings, "SANDBOX_AGENT_PORT", port)
    monkeypatch.setattr(k8s_runtime, "POD_ROOT", agent_root.as_posix())
    monkeypatch.setattr(k8s_runtime.secrets, "token_urlsafe", lambda n=32: TOKEN)
    k8s_runtime._endpoints.clear()
    k8s_runtime._synced.clear()
    storage = MemoryStorage()
    set_storage(storage)
    workspace = tmp_path / "platform-workspace"
    workspace.mkdir()
    kube = PlayedKube()
    try:
        yield {"runtime": k8s_runtime.KubernetesSandboxRuntime(company_id, network="none", kube=kube,
                                                               roots=[str(workspace)]),
               "kube": kube, "workspace": workspace, "storage": storage, "agent_root": agent_root,
               "port": port, "company_id": company_id, "module": k8s_runtime}
    finally:
        set_storage(None)
        k8s_runtime._endpoints.clear()
        k8s_runtime._synced.clear()
        agent.kill()
        agent.wait(timeout=10)


async def test_a_script_runs_in_the_pod_and_its_output_comes_back(sandbox):
    runtime, workspace, kube = sandbox["runtime"], sandbox["workspace"], sandbox["kube"]
    script = workspace / "job.py"
    script.write_text("import pathlib, sys\npathlib.Path('out').mkdir(exist_ok=True)\n"
                      "pathlib.Path('out/result.txt').write_text('42')\n"
                      "print(pathlib.Path(sys.argv[0]).resolve().as_posix())\n",
                      encoding="utf-8")
    result = await runtime.exec([sys.executable, str(script)], cwd=str(workspace), timeout=30)
    assert result.ok, (result.stderr, result.launch_error)
    assert (workspace / "out" / "result.txt").read_text() == "42"         # brought back from the pod
    assert str(workspace) in result.stdout and sandbox["agent_root"].as_posix() not in result.stdout
    pod = kube.objects[f"Pod/t-tstsbx0001/{runtime.name}"]
    assert pod["spec"]["runtimeClassName"] and kube.objects["NetworkPolicy/t-tstsbx0001/sandbox-isolation"]
    assert any(path.endswith(runtime.name) for path, _ in kube.patched)   # last used, for the reaper

    slow = workspace / "slow.py"
    slow.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    timed = await runtime.exec([sys.executable, str(slow)], cwd=str(workspace), timeout=1)
    assert timed.timed_out and not timed.ok


async def test_pause_saves_the_workspace_and_a_new_pod_restores_it(sandbox):
    runtime, workspace, kube, storage = sandbox["runtime"], sandbox["workspace"], sandbox["kube"], sandbox["storage"]
    (workspace / "notes.txt").write_text("keep me", encoding="utf-8")
    assert (await runtime.exec([sys.executable, "-c", "print('hi')"], timeout=30)).ok
    await runtime.pause()
    assert f"Pod/t-tstsbx0001/{runtime.name}" not in kube.objects
    key = f"t-tstsbx0001/scratch/sandbox/{runtime.name}/workspace.tar.gz"
    assert key in storage.objects

    pod_copy = sandbox["agent_root"] / "0" / "notes.txt"
    pod_copy.unlink()                                                    # a new pod starts empty
    check = await runtime.exec([sys.executable, "-c", "import pathlib; print(pathlib.Path('notes.txt').read_text())"],
                               timeout=30)
    assert check.ok and "keep me" in check.stdout                         # restored from storage


async def test_the_idle_reaper_saves_and_deletes_pods_nobody_used(sandbox):
    runtime, kube = sandbox["runtime"], sandbox["kube"]
    assert (await runtime.exec([sys.executable, "-c", "print(1)"], timeout=30)).ok
    pod = kube.objects[f"Pod/t-tstsbx0001/{runtime.name}"]
    pod["metadata"]["annotations"][sandbox["module"].LAST_USED] = str(int(time.time()) - 7200)
    reaped = await sandbox["module"].reap_idle(kube)
    assert reaped == {"reaped": 1, "failed": 0} and f"Pod/t-tstsbx0001/{runtime.name}" not in kube.objects


async def test_the_agent_refuses_strangers_and_paths_outside_its_root(sandbox):
    base = f"http://127.0.0.1:{sandbox['port']}"
    async with httpx.AsyncClient(base_url=base) as client:
        assert (await client.post("/exec", json={"argv": ["echo"]})).status_code == 401
        wrong = {"Authorization": "Bearer nope"}
        assert (await client.get("/list", params={"path": "/"}, headers=wrong)).status_code == 401
        right = {"Authorization": f"Bearer {TOKEN}"}
        outside = await client.get("/files", params={"path": str(Path(sandbox["agent_root"]).parent / "x")},
                                   headers=right)
        assert outside.status_code == 400 and "outside" in outside.json()["error"]
        sneaky = await client.get("/files", params={"path": f"{sandbox['agent_root'].as_posix()}/../escape"},
                                  headers=right)
        assert sneaky.status_code == 400

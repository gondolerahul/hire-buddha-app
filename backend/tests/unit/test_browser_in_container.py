"""Chromium runs inside the container (TL-18).

``ContainerRuntime.open_browser_session`` handed back a page from an embedded
``SubprocessRuntime``: with the container runtime on, Chromium — and the
``evaluate`` step, arbitrary JavaScript by design — still ran on the host as
the backend's OS user. Now a session is a request the runtime runs; the
container runtime execs the platform's runner in the company's ``web``
container, whose only way out is a proxy that refuses internal addresses.

Hermetic: docker is not called. The real browser in the real container is
``tests/integration/test_container_runtime_docker.py``.
"""
from __future__ import annotations

import importlib.util
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.ai.tools.sandbox import browser_runner
from src.ai.tools.sandbox.container_runtime import ContainerRuntime, install_browser_runner
from src.ai.tools.sandbox.runtime import ExecResult

CTX = {"company_id": "c-1", "run_id": "r-1"}


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    from src.common.config import settings

    monkeypatch.setattr(settings, "SANDBOX_WORKSPACE_ROOT", str(tmp_path), raising=False)
    return tmp_path


def _execs(monkeypatch, stdout: str) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    async def _exec(self, argv, *, cwd=None, timeout=30.0, env=None):
        request = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        calls.append({"network": self.network, "argv": list(argv), "cwd": cwd, "env": dict(env or {}),
                      "request": request, "runner": Path(argv[1]).read_text(encoding="utf-8")})
        return ExecResult(returncode=0, stdout=stdout)

    monkeypatch.setattr(ContainerRuntime, "exec", _exec)
    return calls


@pytest.mark.asyncio
async def test_the_session_runs_in_the_companys_web_container(monkeypatch, workspace) -> None:
    result = {"steps": [{"status": "success", "action": "navigate", "title": "Example"}], "blocked_requests": []}
    calls = _execs(monkeypatch, "noise\n" + browser_runner.MARKER + json.dumps(result) + "\n")
    rt = ContainerRuntime(company_id="c-1")           # the call's own runtime has no network
    out = await rt.run_browser({"steps": [{"action": "navigate", "url": "https://example.com"}],
                                "timeout_ms": 5000, "out_dir": "/drop", "user_data_dir": "/profile"},
                               timeout=60)
    assert out == result
    [call] = calls
    assert call["network"] == "web"
    assert call["argv"][0] == "python3"
    assert call["request"] == {"steps": [{"action": "navigate", "url": "https://example.com"}], "timeout_ms": 5000}
    assert call["env"]["ARTIFACTS_DIR"] == "/drop"
    assert call["env"][browser_runner.PROFILE_ENV] == "/profile"
    with open(browser_runner.__file__, encoding="utf-8") as fh:
        assert call["runner"] == fh.read()           # the platform's runner, verbatim
    assert not os.path.exists(call["cwd"])           # the request is removed afterwards


def test_the_runner_lives_under_the_read_only_skills_root(workspace) -> None:
    from src.ai.tools.sandbox.workspace import skills_root

    path = install_browser_runner("c-1")
    assert Path(path).resolve().is_relative_to(Path(skills_root("c-1")).resolve())
    mtime = os.path.getmtime(path)
    assert install_browser_runner("c-1") == path and os.path.getmtime(path) == mtime  # once per version


@pytest.mark.asyncio
async def test_a_runner_that_reports_nothing_is_an_error(monkeypatch, workspace) -> None:
    _execs(monkeypatch, "Traceback: chromium crashed")
    with pytest.raises(RuntimeError, match="browser runner failed"):
        await ContainerRuntime(company_id="c-1").run_browser({"steps": []}, timeout=5)


def test_the_runner_imports_nothing_from_the_platform() -> None:
    """Inside the container the platform package is not there."""
    source = Path(browser_runner.__file__).read_text(encoding="utf-8")
    assert "from src" not in source and "import src" not in source


# ── the steps, wherever they run ─────────────────────────────────────────

class _Page:
    url = "https://example.com/"

    def __init__(self) -> None:
        self.opened: List[str] = []

    async def goto(self, url, **_kw):
        self.opened.append(url)

    async def title(self):
        return "Example"

    async def inner_text(self, _selector):
        return "body"

    async def screenshot(self, **_kw):
        return b"\x89PNG"

    async def fill(self, *_a, **_kw):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["get_text", "screenshot", "type"])
async def test_a_steps_url_is_opened_first(tmp_path, action) -> None:
    """The step's ``url`` used to go through ``_is_url_blocked``, which no
    longer existed: every such step raised ``NameError``."""
    page = _Page()
    out = await browser_runner.run_step(page, {"action": action, "url": "https://example.com/a",
                                               "selector": "#q" if action == "type" else None},
                                        1000, str(tmp_path))
    assert out["status"] == "success", out
    assert page.opened == ["https://example.com/a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "data:text/html,x"])
async def test_only_http_is_opened(url) -> None:
    page = _Page()
    out = await browser_runner.run_step(page, {"action": "navigate", "url": url}, 1000, None)
    assert out["status"] == "error" and "URL refused" in out["error"]
    assert page.opened == []


@pytest.mark.asyncio
async def test_a_page_the_proxy_refused_is_a_refused_step() -> None:
    """Over plain http the proxy's 403 page loads like any page; its header
    says it is a refusal."""
    page = _Page()

    async def _goto(url, **_kw):
        return SimpleNamespace(headers={browser_runner.REFUSED_HEADER: "169.254.169.254 is not public"})

    page.goto = _goto
    out = await browser_runner.run_step(page, {"action": "navigate", "url": "http://169.254.169.254/"}, 1000, None)
    assert out["status"] == "error" and "not public" in out["error"]


@pytest.mark.asyncio
async def test_a_screenshot_is_kept_as_an_artifact_of_the_run(monkeypatch, workspace) -> None:
    """The runner writes the image to the call's drop box; the tool keeps it."""
    import src.ai.artifact_service as artifact_service
    import src.ai.tools.sandbox.runtime as runtime
    from src.ai.tools.sandbox.browser_tool import HeadlessBrowserTool

    class _Runtime:
        async def run_browser(self, request, *, timeout):
            Path(request["out_dir"], "screenshot_ab.png").write_bytes(b"\x89PNG")
            return {"steps": [{"status": "success", "action": "screenshot", "file": "screenshot_ab.png"}]}

    async def _resolve(_ctx, **_kw):
        return _Runtime()

    async def _no_profile(_ctx):
        return None

    async def _save(context, **kw):
        return SimpleNamespace(id="art-1", file_path="/x")

    monkeypatch.setattr(runtime, "resolve_sandbox_runtime", _resolve)
    monkeypatch.setattr(runtime, "resolve_persistent_browser_dir", _no_profile)
    monkeypatch.setattr(artifact_service, "save_tool_output", _save)
    out = await HeadlessBrowserTool().invoke({"steps": [{"action": "screenshot"}]}, CTX)
    assert out.success, out.error
    [step] = json.loads(out.output)["steps"]
    assert step["artifact_id"] == "art-1" and "file" not in step


# ── the web proxy ────────────────────────────────────────────────────────

def _web_proxy():
    path = Path(__file__).resolve().parents[2] / "docker" / "egress-proxy" / "web_proxy.py"
    spec = importlib.util.spec_from_file_location("web_proxy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["127.0.0.1", "10.1.2.3", "172.18.0.2", "192.168.1.1", "169.254.169.254",
                                  "100.64.0.1", "::1", "fd00::1", "::ffff:127.0.0.1", "localhost"])
async def test_the_web_proxy_refuses_internal_addresses(host) -> None:
    proxy = _web_proxy()
    with pytest.raises(proxy.Refused):
        await proxy.public_address(host, 443)


@pytest.mark.asyncio
async def test_the_web_proxy_connects_to_the_address_it_checked() -> None:
    proxy = _web_proxy()
    assert await proxy.public_address("93.184.215.14", 443) == "93.184.215.14"


@pytest.mark.asyncio
async def test_the_web_proxy_runs_unprivileged(monkeypatch) -> None:
    from src.ai.tools.sandbox.egress_proxy import EgressProxyManager

    mgr = EgressProxyManager(mode="web")
    calls: List[tuple] = []

    async def _docker(*args, **_kw):
        calls.append(args)
        return (1, "", "") if args[:1] == ("inspect",) or args[:2] == ("network", "inspect") else (0, "", "")

    monkeypatch.setattr(mgr, "_docker", _docker)
    assert await mgr.ensure() == "http://hb-egress-web:8888"
    run = next(c for c in calls if c[:2] == ("run", "-d"))
    assert run[run.index("--name") + 1] == "hb-egress-web"
    assert run[run.index("--user") + 1] == "65534:65534"
    assert "--read-only" in run and "MODE=web" in run and "SETUID" not in run

"""ContainerRuntime selection + exec mapping — Phase 12 `02` S4.

Hermetic: no Docker required. Selection logic is pure; exec result-mapping is
covered by faking ``asyncio.create_subprocess_exec`` and the manager so the
``docker exec`` return-code → ``ExecResult`` contract is verified without a
daemon. The Docker-backed end-to-end path lives in
``tests/integration/test_container_runtime_docker.py`` (Docker-gated).
"""
from __future__ import annotations

import asyncio
from typing import Optional

import pytest

from src.ai.tools.sandbox import runtime as runtime_mod
from src.ai.tools.sandbox.container_runtime import ContainerRuntime
from src.ai.tools.sandbox.runtime import (
    SandboxRuntime,
    SubprocessRuntime,
    get_sandbox_runtime,
    resolve_sandbox_runtime,
)
from src.ai.tools.sandbox.tenant_manager import (
    SandboxDockerError,
    TenantSandboxManager,
)


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------

def test_factory_default_is_subprocess(monkeypatch) -> None:
    from src.common import config

    monkeypatch.setattr(config.settings, "SANDBOX_CONTAINER_RUNTIME_ENABLED", False)
    assert isinstance(get_sandbox_runtime({"company_id": "c1"}), SubprocessRuntime)


def test_factory_context_opts_in() -> None:
    rt = get_sandbox_runtime({"company_id": "c1", "container_runtime": True})
    assert isinstance(rt, ContainerRuntime)
    assert rt.company_id == "c1"
    assert isinstance(rt, SandboxRuntime)


def test_factory_context_override_wins_over_settings(monkeypatch) -> None:
    from src.common import config

    monkeypatch.setattr(config.settings, "SANDBOX_CONTAINER_RUNTIME_ENABLED", True)
    rt = get_sandbox_runtime({"company_id": "c1", "container_runtime": False})
    assert isinstance(rt, SubprocessRuntime)


def test_factory_settings_enables_container(monkeypatch) -> None:
    from src.common import config

    monkeypatch.setattr(config.settings, "SANDBOX_CONTAINER_RUNTIME_ENABLED", True)
    assert isinstance(get_sandbox_runtime({"company_id": "c1"}), ContainerRuntime)


def test_container_name() -> None:
    assert TenantSandboxManager.container_name("abc-123") == "hb-sandbox-abc-123"


# --------------------------------------------------------------------------
# async per-company canary resolution
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_explicit_db_flag_overrides_settings(monkeypatch) -> None:
    from src.common import config

    monkeypatch.setattr(config.settings, "SANDBOX_CONTAINER_RUNTIME_ENABLED", False)

    async def _flag(_cid):
        return True  # an explicit company/global row says ON

    monkeypatch.setattr(runtime_mod, "_resolve_company_container_flag", _flag)
    rt = await resolve_sandbox_runtime({"company_id": "c1"})
    assert isinstance(rt, ContainerRuntime)


@pytest.mark.asyncio
async def test_resolve_no_db_flag_falls_through_to_settings(monkeypatch) -> None:
    from src.common import config

    monkeypatch.setattr(config.settings, "SANDBOX_CONTAINER_RUNTIME_ENABLED", True)

    async def _none(_cid):
        return None  # no explicit row → settings master decides

    monkeypatch.setattr(runtime_mod, "_resolve_company_container_flag", _none)
    rt = await resolve_sandbox_runtime({"company_id": "c1"})
    assert isinstance(rt, ContainerRuntime)


@pytest.mark.asyncio
async def test_resolve_db_flag_off_overrides_settings_on(monkeypatch) -> None:
    from src.common import config

    monkeypatch.setattr(config.settings, "SANDBOX_CONTAINER_RUNTIME_ENABLED", True)

    async def _off(_cid):
        return False  # explicit opt-OUT row wins over the settings master

    monkeypatch.setattr(runtime_mod, "_resolve_company_container_flag", _off)
    rt = await resolve_sandbox_runtime({"company_id": "c1"})
    assert isinstance(rt, SubprocessRuntime)


@pytest.mark.asyncio
async def test_resolve_explicit_context_skips_db(monkeypatch) -> None:
    def _boom(_cid):  # must not be called when context is explicit
        raise AssertionError("flag resolution should be skipped")

    monkeypatch.setattr(runtime_mod, "_resolve_company_container_flag", _boom)
    rt = await resolve_sandbox_runtime({"company_id": "c1", "container_runtime": True})
    assert isinstance(rt, ContainerRuntime)


# --------------------------------------------------------------------------
# exec result mapping
# --------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, rc: int, out: bytes = b"", err: bytes = b"") -> None:
        self.returncode = rc
        self._out = out
        self._err = err

    async def communicate(self):  # type: ignore[no-untyped-def]
        return self._out, self._err

    def kill(self) -> None:
        pass

    async def wait(self) -> None:
        pass


def _runtime_with_ensure(monkeypatch, name: Optional[str] = "hb-sandbox-c1"):
    rt = ContainerRuntime(company_id="c1")

    async def _ensure(_company_id: str) -> str:
        if name is None:
            raise SandboxDockerError("daemon down")
        return name

    monkeypatch.setattr(rt.manager, "ensure", _ensure)
    return rt


@pytest.mark.asyncio
async def test_exec_ensure_failure_is_launch_error(monkeypatch) -> None:
    rt = _runtime_with_ensure(monkeypatch, name=None)
    res = await rt.exec(["python3", "-c", "print(1)"])
    assert res.launch_error == "daemon down"
    assert res.ok is False


@pytest.mark.asyncio
async def test_exec_docker_cli_missing(monkeypatch) -> None:
    rt = _runtime_with_ensure(monkeypatch)

    async def _boom(*_a, **_k):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)
    res = await rt.exec(["python3", "-c", "print(1)"])
    assert res.launch_error is not None
    assert "docker" in res.launch_error


@pytest.mark.asyncio
async def test_exec_success(monkeypatch) -> None:
    rt = _runtime_with_ensure(monkeypatch)

    async def _ok(*_a, **_k):
        return _FakeProc(0, out=b"hello\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _ok)
    res = await rt.exec(["python3", "-c", "print('hello')"])
    assert res.ok
    assert res.returncode == 0
    assert "hello" in res.stdout


@pytest.mark.asyncio
async def test_exec_timeout_rc_maps_to_timed_out(monkeypatch) -> None:
    rt = _runtime_with_ensure(monkeypatch)

    async def _timeout(*_a, **_k):
        return _FakeProc(124)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _timeout)
    res = await rt.exec(["sleep", "100"], timeout=1.0)
    assert res.timed_out is True
    assert res.ok is False


@pytest.mark.asyncio
async def test_exec_not_found_rc(monkeypatch) -> None:
    rt = _runtime_with_ensure(monkeypatch)

    async def _nf(*_a, **_k):
        return _FakeProc(127, err=b"not found")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _nf)
    res = await rt.exec(["nope"])
    assert res.not_found is True
    assert res.returncode == 127


@pytest.mark.asyncio
async def test_exec_wraps_argv_in_timeout(monkeypatch) -> None:
    rt = _runtime_with_ensure(monkeypatch)
    captured: dict = {}

    async def _capture(*args, **_k):
        captured["args"] = args
        return _FakeProc(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _capture)
    await rt.exec(["python3", "x.py"], cwd="/tmp/sandbox/c1", timeout=7.0)
    args = captured["args"]
    assert args[0] == "docker"
    assert "exec" in args
    assert "timeout" in args
    assert "python3" in args and "x.py" in args
    # cwd threaded as -w; the timeout duration appears as a positional arg.
    assert "-w" in args and "/tmp/sandbox/c1" in args
    assert "7" in args

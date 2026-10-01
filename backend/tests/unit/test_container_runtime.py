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
# selection — one switch, no silent host fallback (TX-01, TL-01)
# --------------------------------------------------------------------------

def test_factory_default_is_subprocess() -> None:
    assert isinstance(get_sandbox_runtime({"company_id": "c1"}), SubprocessRuntime)


def test_factory_container_when_asked() -> None:
    rt = get_sandbox_runtime({"company_id": "c1"}, container=True)
    assert isinstance(rt, ContainerRuntime)
    assert rt.company_id == "c1"
    assert isinstance(rt, SandboxRuntime)


def test_the_call_context_cannot_choose_the_runtime() -> None:
    """``container_runtime`` in a context used to override every switch; run
    input could set it (TL-53)."""
    assert isinstance(get_sandbox_runtime({"company_id": "c1", "container_runtime": True}),
                      SubprocessRuntime)


def test_a_container_runtime_that_cannot_be_built_is_an_error(monkeypatch) -> None:
    from src.ai.tools.sandbox import container_runtime as cr

    def _broken(self, *a, **k):
        raise RuntimeError("docker support missing")

    monkeypatch.setattr(cr.ContainerRuntime, "__init__", _broken)
    with pytest.raises(RuntimeError, match="docker support missing"):
        get_sandbox_runtime({"company_id": "c1"}, container=True)


def test_container_name() -> None:
    assert TenantSandboxManager.container_name("abc-123") == "hb-sandbox-abc-123"


@pytest.mark.asyncio
@pytest.mark.parametrize("on, expected", [(True, ContainerRuntime), (False, SubprocessRuntime)])
async def test_resolve_follows_the_switch(monkeypatch, on, expected) -> None:
    async def _switch(_cid):
        return on

    monkeypatch.setattr(runtime_mod, "container_runtime_enabled", _switch)
    assert isinstance(await resolve_sandbox_runtime({"company_id": "c1"}), expected)


@pytest.mark.asyncio
async def test_the_switch_is_the_flag_resolved_for_the_company(monkeypatch) -> None:
    from uuid import uuid4

    from src.ai.core.feature_flags import FeatureFlags

    seen = {}

    async def _is_on(self, key, *, company_id=None, **_kw):
        seen.update(key=key, company_id=company_id)
        return True

    monkeypatch.setattr(FeatureFlags, "is_on", _is_on)
    cid = uuid4()
    assert await runtime_mod.container_runtime_enabled(str(cid)) is True
    assert seen == {"key": "sandbox.container_runtime_enabled", "company_id": cid}


def test_the_flags_default_is_the_deployment_setting(monkeypatch) -> None:
    """The flag was declared True while the runtime ran the host sandbox."""
    from src.ai.core import feature_flags as ff
    from src.common import config

    assert ff.DEFAULTS["sandbox.container_runtime_enabled"] == bool(
        config.settings.SANDBOX_CONTAINER_RUNTIME_ENABLED)
    monkeypatch.setattr(config.settings, "SANDBOX_CONTAINER_RUNTIME_ENABLED", True)
    assert ff._sandbox_container_default() is True


@pytest.mark.asyncio
async def test_without_a_database_the_deployment_default_decides(monkeypatch) -> None:
    from src.ai.core import feature_flags as ff
    from src.common import database

    def _no_db():
        raise OSError("database unavailable")

    monkeypatch.setattr(database, "AsyncSessionLocal", _no_db)
    monkeypatch.setitem(ff.DEFAULTS, "sandbox.container_runtime_enabled", True)
    assert await runtime_mod.container_runtime_enabled("c1") is True


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

"""SandboxRuntime / SubprocessRuntime — Phase 12 `02` S1/S2.

Covers the exec substrate the sandbox + terminal tools delegate to. Real (but
trivial + fast) host subprocesses; no network/DB. Browser sessions need
Playwright and are exercised by the e2e suite.
"""
from __future__ import annotations

import pytest

from src.ai.tools.sandbox.runtime import (
    ExecResult,
    SandboxRuntime,
    SubprocessRuntime,
    get_sandbox_runtime,
)


def test_factory_returns_subprocess_runtime() -> None:
    rt = get_sandbox_runtime({"company_id": "abc"})
    assert isinstance(rt, SubprocessRuntime)
    assert rt.company_id == "abc"
    # The factory result satisfies the Protocol (runtime-checkable).
    assert isinstance(rt, SandboxRuntime)


@pytest.mark.asyncio
async def test_exec_echo_ok() -> None:
    rt = SubprocessRuntime()
    res = await rt.exec(["/bin/echo", "hello"])
    assert res.ok
    assert res.returncode == 0
    assert "hello" in res.stdout
    assert res.timed_out is False


@pytest.mark.asyncio
async def test_exec_nonzero_exit() -> None:
    rt = SubprocessRuntime()
    res = await rt.exec(["/bin/sh", "-c", "echo oops 1>&2; exit 3"])
    assert res.returncode == 3
    assert "oops" in res.stderr
    assert res.ok is False


@pytest.mark.asyncio
async def test_exec_timeout() -> None:
    rt = SubprocessRuntime()
    res = await rt.exec(["/bin/sh", "-c", "sleep 5"], timeout=0.3)
    assert res.timed_out is True
    assert res.returncode == -1
    assert res.ok is False


@pytest.mark.asyncio
async def test_exec_not_found() -> None:
    rt = SubprocessRuntime()
    res = await rt.exec(["/nonexistent/interpreter-xyz"])
    assert res.not_found is True
    assert res.returncode == -1
    assert res.launch_error is not None


@pytest.mark.asyncio
async def test_exec_env_and_cwd(tmp_path) -> None:
    rt = SubprocessRuntime()
    res = await rt.exec(
        ["/bin/sh", "-c", "echo $FOO; pwd"],
        cwd=str(tmp_path),
        env={"FOO": "bar", "PATH": "/usr/bin:/bin"},
    )
    assert res.returncode == 0
    assert "bar" in res.stdout
    assert str(tmp_path) in res.stdout


def test_exec_result_ok_property() -> None:
    assert ExecResult(returncode=0).ok is True
    assert ExecResult(returncode=1).ok is False
    assert ExecResult(returncode=0, timed_out=True).ok is False
    assert ExecResult(returncode=0, launch_error="x").ok is False

"""Sandbox cost metering (S6) — hermetic, no DB.

Verifies meter_sandbox_usage maps duration→billed seconds with the ``sandbox``
attribution, skips when there's nothing to bill, and that run_sandbox_exec meters
after every exec.
"""
from __future__ import annotations

import pytest

from src.ai.tools.sandbox import metering as metering_mod
from src.ai.tools.sandbox import runtime as runtime_mod
from src.ai.tools.sandbox.runtime import ExecResult, run_sandbox_exec


class _FakeDB:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


@pytest.fixture
def captured_log(monkeypatch):
    calls = []

    async def _log_usage(self, **kwargs):  # noqa: ANN001
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(
        "src.common.database.AsyncSessionLocal", lambda: _FakeDB(), raising=True
    )
    from src.ai.usage_service import UsageService

    monkeypatch.setattr(UsageService, "log_usage", _log_usage, raising=True)
    return calls


@pytest.mark.asyncio
async def test_meter_records_seconds_and_attribution(captured_log) -> None:
    await metering_mod.meter_sandbox_usage(
        {"company_id": "11111111-1111-1111-1111-111111111111",
         "run_id": "22222222-2222-2222-2222-222222222222"},
        duration_ms=2500,
        runtime_name="ContainerRuntime",
        kind="exec",
    )
    assert len(captured_log) == 1
    kw = captured_log[0]
    assert kw["attribution"] == "sandbox"
    assert kw["service_sku"] == "sandbox-runtime"
    assert kw["raw_quantity"] == pytest.approx(2.5)
    assert kw["metadata"]["sandbox_runtime"] == "ContainerRuntime"


@pytest.mark.asyncio
async def test_meter_skips_without_company(captured_log) -> None:
    await metering_mod.meter_sandbox_usage(
        {"run_id": "x"}, duration_ms=2500, runtime_name="SubprocessRuntime"
    )
    assert captured_log == []


@pytest.mark.asyncio
async def test_meter_skips_zero_duration(captured_log) -> None:
    await metering_mod.meter_sandbox_usage(
        {"company_id": "c1"}, duration_ms=0, runtime_name="SubprocessRuntime"
    )
    assert captured_log == []


@pytest.mark.asyncio
async def test_run_sandbox_exec_meters_after_exec(monkeypatch) -> None:
    class _FakeRuntime:
        async def exec(self, argv, **kw):  # noqa: ANN001
            return ExecResult(returncode=0, stdout="ok", duration_ms=1234)

    async def _resolve(_ctx):
        return _FakeRuntime()

    metered = {}

    async def _meter(context, *, duration_ms, runtime_name, kind="exec"):  # noqa: ANN001
        metered.update(
            duration_ms=duration_ms, runtime_name=runtime_name, kind=kind
        )

    monkeypatch.setattr(runtime_mod, "resolve_sandbox_runtime", _resolve)
    monkeypatch.setattr(metering_mod, "meter_sandbox_usage", _meter)

    res = await run_sandbox_exec({"company_id": "c1"}, ["echo", "hi"])
    assert res.returncode == 0 and res.stdout == "ok"
    assert metered == {
        "duration_ms": 1234,
        "runtime_name": "_FakeRuntime",
        "kind": "exec",
    }

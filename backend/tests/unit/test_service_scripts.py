"""The service scripts: the Linux pair for the VMs, the Windows pair for development.

start_services.ps1 / stop_services.ps1 are the Windows development counterparts
of the .sh scripts the Ubuntu test and production VMs use. They must start and
stop the same services, with the same log and PID files. The .sh stop script
also stops a Unified Gateway an older start script left on :8001.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PS_SCRIPTS = ("start_services.ps1", "stop_services.ps1")


def _read(name: str) -> str:
    return (REPO / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", PS_SCRIPTS)
def test_windows_scripts_are_ascii(name):
    # Windows PowerShell 5.1 reads a UTF-8 file without a BOM as the ANSI code page.
    assert _read(name).isascii()


@pytest.mark.parametrize("name", PS_SCRIPTS)
def test_windows_scripts_say_they_are_for_development_only(name):
    assert "LOCAL DEVELOPMENT ONLY" in _read(name)


@pytest.mark.parametrize("marker", [
    "src.main:app", "src.ai.worker.$($w.Settings)", '"WorkerSettings"', '"ChildWorkerSettings"',
    '"backend_api"', '"arq_worker"', '"arq_child_worker"', '"frontend"', "docker compose up -d db redis",
])
def test_windows_start_matches_the_linux_services(marker):
    assert marker in _read("start_services.ps1")


def test_both_start_scripts_use_the_same_log_and_pid_files():
    sh = _read("start_services.sh")
    for name in ("backend_api", "arq_worker", "arq_child_worker", "frontend"):
        assert f"$LOG_DIR/{name}.log" in sh and f"$LOG_DIR/{name}.pid" in sh, name


@pytest.mark.parametrize("marker", [
    "src\\.main:app", "WorkerSettings", "ChildWorkerSettings", "src\\.gateway\\.",
    '"unified_gateway"', "Stop-Port 8001", "docker compose stop", "SupportsShouldProcess",
])
def test_windows_stop_covers_every_service_and_the_old_gateway(marker):
    assert marker in _read("stop_services.ps1")


def test_linux_stop_stops_the_retired_gateway():
    sh = _read("stop_services.sh")
    assert '"$LOG_DIR/unified_gateway.pid"' in sh
    assert 'pkill -f "uvicorn src.gateway.app:app"' in sh
    assert 'kill_port "Legacy Unified Gateway" 8001' in sh


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"), reason="needs Windows PowerShell")
@pytest.mark.parametrize("name", PS_SCRIPTS)
def test_windows_scripts_parse(name):
    command = (
        "$e = $null; $t = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{REPO / name}', [ref]$t, [ref]$e); "
        "$e.Count"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                         capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "0", out.stdout + out.stderr

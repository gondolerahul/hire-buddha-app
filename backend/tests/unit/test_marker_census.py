"""TS-10, TS-11, TS-14, TS-15: the registered markers are the markers in use,
an unregistered one fails collection, and every test carries its tier."""
from __future__ import annotations

import configparser
import re
import subprocess
import sys
from pathlib import Path

from tests.conftest import TIER_DIRECTORIES

BACKEND = Path(__file__).resolve().parents[2]
BUILTIN = {"asyncio", "parametrize", "skip", "skipif", "xfail", "usefixtures", "filterwarnings"}
_MARK = re.compile(r"pytest\.mark\.([a-z_]+)")


def _ini() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(BACKEND / "pytest.ini", encoding="utf-8")
    return cfg


def _registered() -> set[str]:
    lines = _ini()["pytest"]["markers"].strip().splitlines()
    return {line.split(":", 1)[0].strip() for line in lines if line.strip()}


def _used() -> set[str]:
    used: set[str] = set()
    for root in (BACKEND / "tests", BACKEND / "cortex_memory" / "tests"):
        for path in root.rglob("*.py"):
            if path.name == Path(__file__).name:
                continue
            used |= set(_MARK.findall(path.read_text(encoding="utf-8")))
    return used - BUILTIN


def test_markers_are_strict() -> None:
    assert "--strict-markers" in _ini()["pytest"]["addopts"].split()


def test_every_marker_used_is_registered() -> None:
    assert _used() <= _registered()


def test_every_registered_marker_is_used() -> None:
    """A registered marker nothing carries (``kpi``, ``needs_redis``) selects
    nothing: delete it rather than let a CI lane filter on it."""
    assert _registered() - _used() - set(TIER_DIRECTORIES) == set()


def test_every_tier_directory_exists() -> None:
    for tier in TIER_DIRECTORIES:
        assert (BACKEND / "tests" / tier).is_dir(), tier


def _pytest(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=BACKEND, capture_output=True, text=True, timeout=300,
    )


def test_a_tier_is_selected_by_its_marker() -> None:
    chaos = _pytest("tests/chaos", "--collect-only", "-q", "-m", "chaos")
    assert chaos.returncode == 0, chaos.stdout[-2000:]
    assert re.search(r"\b[1-9]\d* tests? collected", chaos.stdout)
    unit = _pytest("tests/chaos", "--collect-only", "-q", "-m", "not chaos")
    assert "no tests collected" in unit.stdout or unit.returncode == 5


def test_a_typod_marker_fails_collection(tmp_path) -> None:
    test = BACKEND / "tests" / "unit" / f"test_ts14_probe_{tmp_path.name[-8:]}.py"
    test.write_text("import pytest\n\n\n@pytest.mark.needs_dbb\ndef test_x():\n    pass\n", encoding="utf-8")
    try:
        result = _pytest(str(test.relative_to(BACKEND)), "--collect-only", "-q")
    finally:
        test.unlink()
    assert result.returncode != 0
    assert "needs_dbb" in result.stdout + result.stderr

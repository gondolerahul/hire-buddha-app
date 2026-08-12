"""C12 — the per-package mypy --strict gate must pass on HEAD."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TYPECHECK_SCRIPT = REPO_ROOT / "backend" / "scripts" / "typecheck_ai.py"


def test_typecheck_passes() -> None:
    """`python backend/scripts/typecheck_ai.py` exits 0 on HEAD."""
    result = subprocess.run(
        [sys.executable, str(TYPECHECK_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"mypy --strict gate failed.\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

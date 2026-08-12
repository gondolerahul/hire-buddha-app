"""Phase 11 Track 0 — layout lint must pass on HEAD."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LINT_SCRIPT = REPO_ROOT / "backend" / "scripts" / "lint_ai_layout.py"


def test_layout_lint_passes() -> None:
    """`python backend/scripts/lint_ai_layout.py` exits 0 on HEAD."""
    result = subprocess.run(
        [sys.executable, str(LINT_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"Layout lint failed.\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

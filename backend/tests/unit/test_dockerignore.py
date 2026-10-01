"""IN-22: the backend image carries no secrets, host virtualenv or runtime data.

backend/Dockerfile ends with `COPY . .` and there was no .dockerignore, so an
image built from a working copy contained backend/.env and any host .venv —
which landed on /app/.venv over the Linux virtualenv the builder stage made.
"""
from fnmatch import fnmatch
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]


def _rules() -> list[tuple[bool, str]]:
    path = BACKEND / ".dockerignore"
    assert path.exists(), "backend/.dockerignore is missing"
    rules = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rules.append((line.startswith("!"), line.lstrip("!")))
    return rules


def _excluded(relative: str) -> bool:
    """Docker's rule: the last matching pattern wins; a directory match covers its contents."""
    excluded = False
    parts = relative.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    for negated, pattern in _rules():
        bare = pattern[3:] if pattern.startswith("**/") else None
        hit = any(fnmatch(p, pattern) for p in prefixes) or (
            bare is not None and any(fnmatch(part, bare) for part in parts))
        if hit:
            excluded = not negated
    return excluded


@pytest.mark.parametrize("path", [
    ".env", ".env.local", ".venv/Scripts/python.exe", ".venv/bin/python",
    "uploads/avatar.png", "artifact/user-uploads/a.pdf", "arq_worker.pid",
    "src/ai/__pycache__/worker.cpython-312.pyc", ".pytest_cache/v/cache", ".mypy_cache/3.12/x.json",
])
def test_kept_out_of_the_image(path):
    assert _excluded(path)


@pytest.mark.parametrize("path", [
    "src/main.py", "cortex_memory/__init__.py", "scripts/seed_sandbox_sku.py",
    "pyproject.toml", "poetry.lock", "alembic.ini", "migrations/env.py", ".env.example",
])
def test_the_application_still_goes_in(path):
    assert not _excluded(path)

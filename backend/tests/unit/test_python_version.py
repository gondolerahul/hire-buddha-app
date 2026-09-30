"""SA-21: the declared, type-checked, containerised and provisioned Python agree.

setup_production_vm.sh installed 3.12, pyproject.toml declared ^3.11, mypy
checked against 3.11 and the Dockerfile ran python:3.11-slim — so what was
tested locally was not what a container ran.
"""
import re
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
VERSION = "3.12"


def test_pyproject_declares_it():
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["poetry"]["dependencies"]["python"] == f"^{VERSION}"
    assert project["tool"]["mypy"]["python_version"] == VERSION


def test_the_lock_was_resolved_for_it():
    lock = (BACKEND / "poetry.lock").read_text(encoding="utf-8")
    assert re.search(r'^python-versions = "\^' + re.escape(VERSION) + '"$', lock, re.M)


def test_every_docker_stage_runs_it():
    stages = re.findall(r"^FROM\s+python:(\S+)", (BACKEND / "Dockerfile").read_text(encoding="utf-8"), re.M)
    assert stages and all(tag.startswith(f"{VERSION}-") for tag in stages), stages


def test_the_vm_script_installs_it():
    script = (REPO / "setup_production_vm.sh").read_text(encoding="utf-8")
    assert f"apt-get install -y python{VERSION} " in script

"""Doc Factory scripts are files of their agents' versions, not a shared symlink (P5.7, R2 §2.1).

Every tenant workspace had a symlink to the repo's
``SeedDocumentFactory/scripts`` (writable from tenant code in host mode, read
by every tenant), and the action prompts named ``scripts/<family>/...``. Now
each family's scripts are files of its AGENT's version, written per tenant
into ``.skills/...``, and the prompts name them as ``$SKILL_FILES/...``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from src.ai.governance.entity_assets import (
    MAX_ASSETS_PER_VERSION,
    MAX_ASSET_BYTES,
    MAX_VERSION_BYTES,
    valid_asset_path,
)
from src.ai.tools.sandbox.skill_files import SkillFiles, fill_skill_files

BACKEND = Path(__file__).resolve().parents[2]
SEED = BACKEND / "scripts" / "seeds" / "default_entities" / "SeedDocumentFactory"
FAMILIES = ("docx", "pdf", "pptx", "xlsx")


@pytest.fixture(scope="module")
def seed():
    sys.path.insert(0, str(SEED))
    try:
        import config  # the seed's own module
        yield config
    finally:
        sys.path.remove(str(SEED))


@pytest.mark.parametrize("family", FAMILIES)
def test_every_family_file_is_a_valid_asset_within_limits(seed, family):
    files = seed.family_files(family)
    assert files and len(files) <= MAX_ASSETS_PER_VERSION
    sizes = [len(body.encode("utf-8")) for body in files.values()]
    assert max(sizes) <= MAX_ASSET_BYTES and sum(sizes) <= MAX_VERSION_BYTES
    for path in files:
        assert valid_asset_path(path) == path
        assert not path.endswith(".pyc") and "__pycache__" not in path


@pytest.mark.parametrize("family", FAMILIES)
def test_every_script_a_prompt_names_is_a_file_of_its_family(seed, family):
    files = seed.family_files(family)
    prompts = (SEED / f"actions_{family}.py").read_text(encoding="utf-8")
    named = set(re.findall(r"\$SKILL_FILES/([A-Za-z0-9_./-]+[A-Za-z0-9_])", prompts))
    assert named, f"no $SKILL_FILES reference in actions_{family}.py"
    assert named <= set(files), named - set(files)
    assert "scripts/" not in prompts


def test_the_token_becomes_the_nearest_files_folder():
    near, far = SkillFiles("docx agent", 3, ".skills/docx-agent/3"), SkillFiles("process", 1, ".skills/process/1")
    text = "python $SKILL_FILES/office/validate.py out.docx"
    assert fill_skill_files(text, [near, far]) == "python .skills/docx-agent/3/office/validate.py out.docx"
    assert fill_skill_files(text, []) == text


def test_no_tenant_workspace_links_a_shared_directory():
    src = BACKEND / "src"
    assert not (src / "ai" / "tools" / "sandbox" / "sandbox_provision.py").exists()
    offenders = [p for p in src.rglob("*.py") if "sandbox_provision" in p.read_text(encoding="utf-8")]
    assert offenders == []


@pytest.mark.asyncio
async def test_the_terminal_runs_in_the_tenant_workspace(monkeypatch, tmp_path):
    from src.ai.tools.sandbox.terminal_tool import TerminalTool
    from src.common.config import settings

    monkeypatch.setattr(settings, "SANDBOX_WORKSPACE_ROOT", str(tmp_path), raising=False)
    seen = {}

    async def _run(self, command, working_dir, timeout_s, context=None):
        seen["cwd"] = working_dir
        return '{"exit_code": 0, "stdout": "", "stderr": ""}'

    monkeypatch.setattr(TerminalTool, "_run_subprocess", _run)
    await TerminalTool()._execute('{"command": "ls .skills"}', {"company_id": "c-1"})
    assert Path(seen["cwd"]) == tmp_path / "c-1"

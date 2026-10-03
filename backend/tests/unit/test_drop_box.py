"""A file is an artifact because code put it in $ARTIFACTS_DIR (P11.2 — TL-36).

``terminal`` walked all of ``/tmp`` after every command and filed any recent
document under the current run — including another run's or another tenant's;
both it and ``sandbox_code`` diffed their working directory behind an exclusion
list. Now each call gets an empty drop box and only what lands there is kept.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest

from src.ai.tools.sandbox import drop_box as box_mod
from src.ai.tools.sandbox.drop_box import ARTIFACTS_ENV, drop_box, report


@pytest.fixture
def saved(monkeypatch, tmp_path):
    from src.common.config import settings
    import src.ai.artifact_service as artifacts

    monkeypatch.setattr(settings, "SANDBOX_WORKSPACE_ROOT", str(tmp_path))
    calls = []

    async def save(context, **kw):
        calls.append((context, kw))
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(artifacts, "save_tool_output", save)
    return calls


@pytest.mark.asyncio
async def test_only_the_drop_box_is_kept_and_then_removed(saved, tmp_path):
    ctx = {"company_id": str(uuid.uuid4()), "run_id": str(uuid.uuid4())}
    async with drop_box(ctx, generated_by="terminal") as box:
        assert box.env == {ARTIFACTS_ENV: box.path}
        assert box.path.startswith(str(tmp_path)) and f"{os.sep}.artifacts{os.sep}{ctx['run_id']}" in box.path
        with open(os.path.join(box.path, "deck.pptx"), "wb") as fh:
            fh.write(b"P" * 300)
        os.makedirs(os.path.join(box.path, "charts"))
        with open(os.path.join(box.path, "charts", "q3.png"), "wb") as fh:
            fh.write(b"\x89PNG" * 10)
        # A file next to the drop box — in the workspace — is not an artifact.
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(box.path))), "scratch.xlsx"), "wb") as fh:
            fh.write(b"x" * 300)

    assert not os.path.exists(box.path)
    kept = {kw["file_name"]: kw for _, kw in saved}
    assert set(kept) == {"deck.pptx", "q3.png"}
    assert kept["q3.png"]["mime_type"] == "image/png" and kept["q3.png"]["file_category"] == "images"
    assert all(c["run_id"] == ctx["run_id"] for c, _ in saved)
    assert "deck.pptx" in report(box) and "charts/q3.png" in report(box)


@pytest.mark.asyncio
async def test_links_empties_and_overflow_are_not_kept(saved, monkeypatch):
    monkeypatch.setattr(box_mod, "MAX_FILES", 1)
    ctx = {"company_id": str(uuid.uuid4()), "run_id": "r"}
    async with drop_box(ctx, generated_by="sandbox_code") as box:
        for name, data in (("a.txt", b"a"), ("b.txt", b"b"), ("empty.txt", b"")):
            with open(os.path.join(box.path, name), "wb") as fh:
                fh.write(data)
        try:
            os.symlink(__file__, os.path.join(box.path, "link.py"))
        except (OSError, NotImplementedError):
            pass  # Windows without the symlink privilege
    assert [kw["file_name"] for _, kw in saved] == ["a.txt"]
    assert "b.txt" in box.skipped and "empty.txt" in box.skipped


@pytest.mark.asyncio
async def test_without_a_company_there_is_no_drop_box():
    async with drop_box({}, generated_by="terminal") as box:
        assert box is None
    assert report(None) == ""


def test_the_tools_no_longer_scan():
    from src.ai.tools.sandbox.sandbox_executor import SandboxCodeTool
    from src.ai.tools.sandbox.terminal_tool import TerminalTool

    for tool in (SandboxCodeTool, TerminalTool):
        assert not hasattr(tool, "_register_new_artifacts")
        assert "ARTIFACTS_DIR" in tool.description

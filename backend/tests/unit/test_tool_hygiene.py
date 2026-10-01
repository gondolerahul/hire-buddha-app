"""TL-29, TL-63, TX-05 — small tool-layer hygiene fixes."""
from __future__ import annotations

import logging
import os
import tempfile
from uuid import uuid4

import pytest

from src.ai.tools.base import Tool, ToolRegistry
from src.ai.tools.documents.pdf_generator import PDFGeneratorTool
from src.ai.tools.sandbox import runtime, tenant_manager
from src.ai.tools.sandbox.workspace import tenant_workspace, workspace_root


def test_pdf_generator_advertises_the_image_paths_it_reads() -> None:
    """TL-63: a second get_function_schema without image_paths used to win."""
    props = PDFGeneratorTool().get_function_schema()["parameters"]["properties"]
    assert "image_paths" in props


def test_every_sandbox_path_shares_one_workspace_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """TL-29: one definition of the workspace root, configurable."""
    from src.common.config import settings

    monkeypatch.setattr(settings, "SANDBOX_WORKSPACE_ROOT", "/srv/hb-workspaces")
    cid = uuid4()
    assert workspace_root() == "/srv/hb-workspaces"
    assert tenant_workspace(cid) == os.path.join("/srv/hb-workspaces", str(cid))
    assert runtime._sandbox_base_dir() == "/srv/hb-workspaces"
    assert tenant_manager._sandbox_base_dir() == "/srv/hb-workspaces"

    monkeypatch.setattr(settings, "SANDBOX_WORKSPACE_ROOT", "")
    assert workspace_root() == os.path.join(tempfile.gettempdir(), "sandbox")


class _T(Tool):
    name = "tx05_probe"
    description = "probe"

    async def run(self, input_data: str) -> str:
        return ""


def test_tenant_tool_registration_is_not_logged_at_info(caplog: pytest.LogCaptureFixture) -> None:
    """TX-05: it fired on every registration of a tool nothing could reach."""
    caplog.set_level(logging.INFO, logger="src.ai.tools.base")
    cid = uuid4()
    try:
        ToolRegistry.register_tenant_tool(cid, _T())
        assert not [r for r in caplog.records if r.levelno >= logging.INFO]
    finally:
        ToolRegistry._tenant_tools.pop(str(cid), None)

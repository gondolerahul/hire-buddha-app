"""Tenant workspaces are durable and have three roots (P11.1 — TL-16, TL-17).

The workspace defaulted to ``<system temp>/sandbox``, which a reboot or
``systemd-tmpfiles`` empties; and the container mounted only the workspace, so
tenant code could rewrite the skill files a published version ships, and could
not read an artifact the model named.
"""
from __future__ import annotations

import logging
import os
import tempfile

from src.ai.tools.sandbox import workspace
from src.ai.tools.sandbox.tenant_manager import TenantSandboxManager, mounted_roots


def test_the_default_root_is_not_the_temp_directory(monkeypatch):
    from src.common.config import settings

    monkeypatch.setattr(settings, "SANDBOX_WORKSPACE_ROOT", "")
    root = workspace.workspace_root()
    assert not os.path.realpath(root).startswith(os.path.realpath(tempfile.gettempdir()))
    assert root.replace("\\", "/").endswith("backend/var/sandbox")


def test_a_temp_root_is_warned_about_once(monkeypatch, caplog):
    from src.common.config import settings

    monkeypatch.setattr(settings, "SANDBOX_WORKSPACE_ROOT", os.path.join(tempfile.gettempdir(), "sandbox"))
    monkeypatch.setattr(workspace, "_warned_ephemeral", False)
    with caplog.at_level(logging.WARNING):
        workspace.workspace_root()
        workspace.workspace_root()
    assert caplog.text.count("will not survive a reboot") == 1


def test_the_container_mounts_skills_and_artifacts_read_only(monkeypatch, tmp_path):
    from src.common.config import settings

    monkeypatch.setattr(settings, "SANDBOX_WORKSPACE_ROOT", str(tmp_path / "ws"))
    args = TenantSandboxManager()._mounts("acme")
    volumes = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
    ws, skills, system, user = mounted_roots("acme")
    assert skills == os.path.join(ws, ".skills")
    by_host = {v.rsplit(":", 2 if v.endswith(":ro") else 1)[0]: v.endswith(":ro") for v in volumes}
    assert by_host == {os.path.abspath(ws): False, os.path.abspath(skills): True,
                       os.path.abspath(system): True, os.path.abspath(user): True}

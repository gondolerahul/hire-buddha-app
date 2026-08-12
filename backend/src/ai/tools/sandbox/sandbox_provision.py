"""
Sandbox Provisioning — Shared resource symlink management for tenant sandboxes.

When a tenant sandbox directory is created at /tmp/sandbox/<company_id>/,
this module symlinks shared resource directories (e.g. Document Factory
scripts) into it so that relative paths like `python scripts/pptx/...`
resolve correctly from within the sandbox.

Configuration via environment variables:
    SANDBOX_SHARED_DIRS  — Comma-separated list of source:target pairs.
                           Example: "/opt/scripts:scripts,/opt/templates:templates"
                           Each pair maps a host directory to a relative name
                           inside every sandbox.

    If SANDBOX_SHARED_DIRS is not set, auto-detects the project's
    backend/scripts/seeds/default_entities/SeedDocumentFactory/scripts/ directory.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Cache the resolved shared dirs so we only compute once
_shared_dirs: Optional[list[tuple[str, str]]] = None


def _resolve_shared_dirs() -> list[tuple[str, str]]:
    """Resolve the list of (source_path, link_name) pairs to symlink into sandboxes."""
    global _shared_dirs
    if _shared_dirs is not None:
        return _shared_dirs

    result: list[tuple[str, str]] = []

    # 1. Check explicit env var
    env_val = os.environ.get("SANDBOX_SHARED_DIRS", "").strip()
    if env_val:
        for pair in env_val.split(","):
            pair = pair.strip()
            if ":" in pair:
                src, name = pair.rsplit(":", 1)
                if os.path.isdir(src):
                    result.append((src, name))
                else:
                    logger.warning(f"SANDBOX_SHARED_DIRS: source '{src}' does not exist, skipping")
            else:
                logger.warning(f"SANDBOX_SHARED_DIRS: invalid pair '{pair}' (expected source:name)")

    # 2. Auto-detect: look for SeedDocumentFactory/scripts under backend/scripts/seeds/
    if not result:
        # The backend runs from <project>/backend/, so project root is one level up
        project_root = Path(__file__).resolve().parents[4]  # tools → ai → src → backend → project
        scripts_dir = (
            project_root
            / "backend"
            / "scripts"
            / "seeds"
            / "default_entities"
            / "SeedDocumentFactory"
            / "scripts"
        )
        if scripts_dir.is_dir():
            result.append((str(scripts_dir), "scripts"))
            logger.info(f"Auto-detected Document Factory scripts at: {scripts_dir}")
        else:
            logger.debug(f"No Document Factory scripts found at: {scripts_dir}")

    _shared_dirs = result
    return result


def provision_sandbox(sandbox_dir: str) -> None:
    """Symlink shared resource directories into a tenant's sandbox directory.

    Called automatically when SandboxCodeTool or TerminalTool creates a
    new tenant sandbox directory.  Symlinks are idempotent — if the link
    already exists and points to the right target, nothing happens.

    Args:
        sandbox_dir: Absolute path to the tenant sandbox (e.g. /tmp/sandbox/<company_id>/)
    """
    shared_dirs = _resolve_shared_dirs()
    if not shared_dirs:
        return

    for source_path, link_name in shared_dirs:
        link_path = os.path.join(sandbox_dir, link_name)
        try:
            # Already correct?
            if os.path.islink(link_path):
                if os.readlink(link_path) == source_path:
                    continue  # Already provisioned correctly
                os.unlink(link_path)  # Stale link, replace

            # Don't clobber a real directory
            if os.path.isdir(link_path) and not os.path.islink(link_path):
                logger.debug(f"Skipping symlink for '{link_name}': real directory already exists")
                continue

            os.symlink(source_path, link_path)
            logger.info(f"Provisioned sandbox symlink: {link_path} → {source_path}")
        except OSError as e:
            logger.warning(f"Failed to create sandbox symlink {link_path} → {source_path}: {e}")

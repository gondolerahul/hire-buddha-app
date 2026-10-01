"""tools.sandbox.workspace — where tenant workspaces live (TL-29).

Every sandbox path — the subprocess and container runtimes, the tenant
container's bind mount, ``sandbox_code``'s working directory, ``document_save``'s
relative-path resolution and the persistent browser profile — derives from
these two functions. There used to be four copies of
``os.path.join(tempfile.gettempdir(), "sandbox")``.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

__all__ = ["workspace_root", "tenant_workspace"]


def workspace_root() -> str:
    """The directory holding every tenant's workspace.

    ``settings.SANDBOX_WORKSPACE_ROOT`` when set, else ``<system temp>/sandbox``.
    """
    from src.common.config import settings

    configured = (getattr(settings, "SANDBOX_WORKSPACE_ROOT", "") or "").strip()
    return configured or os.path.join(tempfile.gettempdir(), "sandbox")


def tenant_workspace(company_id: Any) -> str:
    """The workspace directory of one company: ``<root>/<company_id>``."""
    return os.path.join(workspace_root(), str(company_id))

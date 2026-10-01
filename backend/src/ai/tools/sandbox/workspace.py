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
from pathlib import Path
from typing import Any

__all__ = [
    "workspace_root", "tenant_workspace", "company_roots",
    "PathOutsideWorkspace", "confine_path", "confine_params", "safe_filename",
]


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


# ---------------------------------------------------------------------------
# Model-supplied paths (TL-54)
# ---------------------------------------------------------------------------
# A tool that reads or writes a path the model gave it confines that path to
# the calling company's files first: its sandbox workspace and its own artifact
# directories. A relative path resolves inside the workspace (the directory
# ``sandbox_code`` runs in). Anything else — ``/etc/passwd``, the backend's
# ``.env``, another company's artifacts, ``../`` — is refused.


class PathOutsideWorkspace(ValueError):
    """A model-supplied path that leaves the company's own files."""


# Where the document, image and video tools write their own copy of an output
# (``backend/src/artifact/system-generated``) before ``save_artifact`` stores the
# registered one under ``backend/artifact``. The path a tool returns to the model
# is this copy, so a follow-up call ("update the document") names it. One write
# path replaces both in P6 (TL-59).
_TOOL_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "artifact" / "system-generated"


def company_roots(company_id: Any) -> list[str]:
    """The directories one company's tools may read and write."""
    from src.ai.artifact_service import ARTIFACT_BASE_DIR, ORIGIN_SYSTEM, ORIGIN_USER

    cid = str(company_id)
    return [
        tenant_workspace(cid),
        str(ARTIFACT_BASE_DIR / ORIGIN_SYSTEM / cid),
        str(ARTIFACT_BASE_DIR / ORIGIN_USER / cid),
        str(_TOOL_OUTPUT_DIR / cid),
    ]


def _inside(path: str, root: str) -> bool:
    root = os.path.realpath(root)
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # different drives on Windows
        return False


def confine_path(company_id: Any, path: Any) -> str:
    """``path`` resolved (symlinks included) inside the company's files, or
    :class:`PathOutsideWorkspace`."""
    if not company_id:
        raise PathOutsideWorkspace("no company: a path cannot be resolved")
    raw = str(path or "").strip()
    if not raw or "\x00" in raw:
        raise PathOutsideWorkspace(f"invalid path: {raw!r}")
    base = tenant_workspace(company_id)
    candidate = raw if os.path.isabs(raw) else os.path.join(base, raw)
    resolved = os.path.realpath(candidate)
    if not any(_inside(resolved, root) for root in company_roots(company_id)):
        raise PathOutsideWorkspace(
            f"path {raw!r} is outside this company's workspace and artifacts")
    return resolved


def confine_params(params: dict[str, Any], company_id: Any, keys: tuple[str, ...]) -> None:
    """Confine each of ``keys`` present in ``params`` (a string, or a list of
    strings) in place; :class:`PathOutsideWorkspace` on the first that escapes."""
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            params[key] = confine_path(company_id, value)
        elif isinstance(value, list):
            params[key] = [confine_path(company_id, v) if isinstance(v, str) and v else v for v in value]


def safe_filename(name: Any, default: str) -> str:
    """An output file name with no directory part (``../x.docx`` → ``x.docx``)."""
    base = os.path.basename(str(name or "").replace("\\", "/")).strip()
    return base if base and base not in (".", "..") else default

"""tools.sandbox.workspace — where tenant workspaces live (TL-29).

Every sandbox path — the subprocess and container runtimes, the tenant
container's bind mount, ``sandbox_code``'s working directory, ``document_save``'s
relative-path resolution and the persistent browser profile — derives from
these two functions. There used to be four copies of
``os.path.join(tempfile.gettempdir(), "sandbox")``.
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

__all__ = [
    "workspace_root", "tenant_workspace", "company_roots", "skills_root", "drop_box_root",
    "PathOutsideWorkspace", "confine_path", "confine_params", "safe_filename",
]

logger = logging.getLogger(__name__)

# ``backend/var/sandbox``: durable, outside the system temp directory (TL-16).
_DEFAULT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "var", "sandbox")
_warned_ephemeral = False


def workspace_root() -> str:
    """The directory holding every tenant's workspace.

    ``settings.SANDBOX_WORKSPACE_ROOT`` when set, else ``backend/var/sandbox``.
    It used to default to ``<system temp>/sandbox``, which a reboot or
    ``systemd-tmpfiles`` empties (TL-16). A deployment with several nodes points
    it at storage every node sees: the tenant container mounts it by path.
    """
    global _warned_ephemeral
    from src.common.config import settings

    configured = (getattr(settings, "SANDBOX_WORKSPACE_ROOT", "") or "").strip()
    root = configured or os.path.normpath(_DEFAULT_ROOT)
    if not _warned_ephemeral and _inside(os.path.realpath(root), tempfile.gettempdir()):
        _warned_ephemeral = True
        logger.warning("SANDBOX_WORKSPACE_ROOT %s is in the system temp directory: tenant "
                       "workspaces will not survive a reboot (TL-16)", root)
    return root


def tenant_workspace(company_id: Any) -> str:
    """The workspace directory of one company: ``<root>/<company_id>``.

    Inside it, two roots a tenant container sees read-only or as a drop box:
    ``.skills/`` (published skill files, :func:`skills_root`) and
    ``.artifacts/`` (:func:`drop_box_root`)."""
    return os.path.join(workspace_root(), str(company_id))


def skills_root(company_id: Any) -> str:
    """Materialised skill files (P5.4). Read-only inside the container."""
    return os.path.join(tenant_workspace(company_id), ".skills")


def drop_box_root(company_id: Any) -> str:
    """Where tool code puts deliverables (TL-36): ``$ARTIFACTS_DIR`` is a
    directory under it per call."""
    return os.path.join(tenant_workspace(company_id), ".artifacts")


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


def company_roots(company_id: Any) -> list[str]:
    """The directories one company's tools may read and write."""
    from src.ai.artifact_service import ARTIFACT_BASE_DIR, ORIGIN_SYSTEM, ORIGIN_USER

    cid = str(company_id)
    return [
        tenant_workspace(cid),
        str(ARTIFACT_BASE_DIR / ORIGIN_SYSTEM / cid),
        str(ARTIFACT_BASE_DIR / ORIGIN_USER / cid),
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

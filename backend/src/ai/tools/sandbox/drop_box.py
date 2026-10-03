"""The artifacts drop box: a file is an artifact because code put it there (TL-36).

``terminal`` and ``sandbox_code`` used to guess at deliverables after every
command: ``terminal`` walked all of ``/tmp`` for recent documents — so a file
another run or another tenant wrote in that window was filed under this run —
and both diffed their working directory against a snapshot, behind a growing
exclusion list (``venv``, ``node_modules``, ``scripts``, ``scratch``…).

Now each call gets an empty directory, ``<workspace>/.artifacts/<run>/<call>/``,
exported to the code as ``$ARTIFACTS_DIR``. When the call ends, every regular
file in it is saved as an artifact of the run (``save_tool_output``) and the
directory is removed. Nothing else is looked at.
"""
from __future__ import annotations

import contextlib
import logging
import mimetypes
import os
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Mapping, Optional

from src.ai.tools.sandbox.workspace import drop_box_root

logger = logging.getLogger(__name__)

__all__ = ["ARTIFACTS_ENV", "DropBox", "drop_box", "report"]

ARTIFACTS_ENV = "ARTIFACTS_DIR"
MAX_FILES = 20
MAX_FILE_BYTES = 25 * 1024 * 1024

_CATEGORIES = {"image": "images", "video": "videos", "audio": "audio", "text": "text"}
_EXTRA_TYPES = {
    ".md": "text/markdown",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass
class DropBox:
    """One call's drop box: ``path`` while the call runs, ``saved`` after."""
    path: str
    saved: List[Dict[str, Any]] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    @property
    def env(self) -> Dict[str, str]:
        return {ARTIFACTS_ENV: self.path}


def _mime(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    return _EXTRA_TYPES.get(ext) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def _category(mime: str) -> str:
    return _CATEGORIES.get(mime.split("/", 1)[0], "documents")


@contextlib.asynccontextmanager
async def drop_box(context: Optional[Mapping[str, Any]], *, generated_by: str) -> AsyncIterator[Optional[DropBox]]:
    """An empty drop box for one call, collected when the block ends; ``None``
    without a company (no context: nothing can be kept)."""
    company_id = (context or {}).get("company_id")
    if not company_id:
        yield None
        return
    run = str((context or {}).get("run_id") or "no-run")
    box = DropBox(os.path.join(drop_box_root(company_id), run, uuid.uuid4().hex[:12]))
    os.makedirs(box.path, exist_ok=True)
    try:
        yield box
    finally:
        try:
            await _collect(box, context, generated_by)
        finally:
            shutil.rmtree(box.path, ignore_errors=True)


async def _collect(box: DropBox, context: Optional[Mapping[str, Any]], generated_by: str) -> None:
    from src.ai.artifact_service import save_tool_output

    files: List[str] = []
    for root, _dirs, names in os.walk(box.path, followlinks=False):
        for name in sorted(names):
            full = os.path.join(root, name)
            if os.path.islink(full) or not os.path.isfile(full):
                box.skipped.append(name)  # a link could point anywhere on the host
                continue
            files.append(full)
    for full in files:
        rel = os.path.relpath(full, box.path).replace(os.sep, "/")
        size = os.path.getsize(full)
        if len(box.saved) >= MAX_FILES or size > MAX_FILE_BYTES or size == 0:
            box.skipped.append(rel)
            continue
        with open(full, "rb") as fh:
            data = fh.read()
        mime = _mime(full)
        try:
            artifact = await save_tool_output(
                dict(context or {}), file_name=os.path.basename(full), file_bytes=data, mime_type=mime,
                file_category=_category(mime), generated_by=generated_by,
                purpose=f"Written to $ARTIFACTS_DIR by {generated_by}",
            )
        except Exception as exc:                                               # noqa: BLE001
            logger.warning("drop box: could not keep %s: %s", rel, exc)
            box.skipped.append(rel)
            continue
        box.saved.append({"file": rel, "size": size, "artifact_id": str(artifact.id),
                          "download_url": f"/api/v1/artifacts/{artifact.id}/download"})


def report(box: Optional[DropBox]) -> str:
    """What the call kept, for the tool's output; empty when nothing."""
    if box is None or not (box.saved or box.skipped):
        return ""
    lines = ["📎 **Generated Artifacts:**"] if box.saved else []
    lines += [f"  • {r['file']} ({r['size']:,} bytes) — [Download]({r['download_url']})" for r in box.saved]
    if box.skipped:
        lines.append(f"  (not kept: {', '.join(box.skipped[:10])} — links, empty, over "
                     f"{MAX_FILE_BYTES // (1024 * 1024)} MB, or past {MAX_FILES} files)")
    return "\n".join(lines)

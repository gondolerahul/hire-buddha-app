"""Shared support for the video tools (Phase 12 `03`).

Output-path conventions, artifact registration, and segment math — the
non-ffmpeg plumbing common to ``video_generate`` / ``video_edit`` /
``video_add_sound``. Kept host-side (DB artifact rows, path layout); the ffmpeg
compute lives in :mod:`._ffmpeg`.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Veo 3.1 native single-segment limit (supports 4, 5, 6, or 8 seconds).
MAX_SEGMENT_SECONDS = 8


def company_video_dir(company_id: Optional[str]) -> str:
    """The company's video working directory, in its workspace (where ffmpeg
    runs in either sandbox runtime). A finished video is then kept as an
    artifact (``register_video_artifact``) and the working file removed."""
    from src.ai.tools.sandbox.workspace import tenant_workspace
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    out_dir = os.path.join(tenant_workspace(company_id), "videos", date_str)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def new_output_path(company_id: Optional[str], *, prefix: str = "video", ext: str = "mp4") -> str:
    """Allocate a fresh unique output path under the company video dir."""
    return os.path.join(company_video_dir(company_id), f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}")


def calculate_segments(total_seconds: int) -> List[int]:
    """Break ``total_seconds`` into valid Veo segment durations (≤8s each).

    Uses the largest valid segments first (8, 6, 5, 4). Lifted from the legacy
    tool; now used by ``video_edit`` for *on-request* re-segmentation hints, not
    silent auto-splitting.
    """
    if total_seconds <= MAX_SEGMENT_SECONDS:
        for cap in (4, 5, 6):
            if total_seconds <= cap:
                return [cap]
        return [8]

    segments: List[int] = []
    remaining = total_seconds
    while remaining > 0:
        for size in (8, 6, 5, 4):
            if remaining >= size:
                segments.append(size)
                remaining -= size
                break
        else:
            segments.append(4)
            remaining = 0
    return segments


async def register_video_artifact(
    context: Optional[Dict[str, Any]],
    video_path: str,
    *,
    purpose: str,
    generated_by: str,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Keep a finished video as an artifact of the call's run and return it.

    The one write path (TL-59): the working file is removed, and the tool
    returns the artifact's path. Before, the video was registered as a second
    copy with no run (TL-46) and the tool returned the first.
    """
    from src.ai.artifact_service import save_tool_output

    video_file = Path(video_path)
    artifact = await save_tool_output(
        context, file_name=video_file.name, file_bytes=video_file.read_bytes(), mime_type="video/mp4",
        file_category="videos", generated_by=generated_by, purpose=purpose[:200],
        extra_metadata=extra_metadata or {},
    )
    # Only the working copy goes: a path the model chose stays where it was.
    from src.ai.tools.sandbox.workspace import tenant_workspace
    work = os.path.realpath(os.path.join(tenant_workspace((context or {}).get("company_id")), "videos"))
    try:
        if os.path.commonpath([os.path.realpath(video_file), work]) == work:
            video_file.unlink()
    except (OSError, ValueError):
        pass
    return artifact

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

# artifact/system-generated/ — the same root the legacy video_generation tool
# used, so existing consumers keep finding outputs.
_BASE_ARTIFACT_DIR = Path(__file__).resolve().parents[4] / "artifact" / "system-generated"

# Veo 3.1 native single-segment limit (supports 4, 5, 6, or 8 seconds).
MAX_SEGMENT_SECONDS = 8


def company_video_dir(company_id: Optional[str]) -> str:
    """Return (and create) the per-company, per-day video output directory."""
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    out_dir = str(_BASE_ARTIFACT_DIR / str(company_id) / date_str / "videos")
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
    company_id: Optional[str],
    video_path: str,
    *,
    purpose: str,
    generated_by: str,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Register a produced video in the artifacts DB table (best-effort)."""
    if not company_id:
        return
    try:
        from uuid import UUID

        from src.ai.artifact_service import ORIGIN_SYSTEM, ArtifactService
        from src.common.database import AsyncSessionLocal

        video_file = Path(video_path)
        if not video_file.exists():
            return
        with open(video_file, "rb") as fh:
            video_bytes = fh.read()

        async with AsyncSessionLocal() as db:
            art_svc = ArtifactService(db)
            await art_svc.save_artifact(
                file_bytes=video_bytes,
                file_name=video_file.name,
                mime_type="video/mp4",
                file_category="videos",
                origin=ORIGIN_SYSTEM,
                company_id=UUID(str(company_id)),
                purpose=purpose[:200],
                generated_by=generated_by,
                extra_metadata=extra_metadata or {},
            )
    except Exception as err:  # noqa: BLE001 - artifact registration is non-fatal
        logger.warning("[video] artifact DB registration failed (non-fatal): %s", err)

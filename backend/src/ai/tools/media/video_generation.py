"""Deprecated ``video_generation`` shim (Phase 12 `03`, V5).

The mega-tool was split into three composable tools — ``video_generate``,
``video_edit``, ``video_add_sound`` (``tools/media/video/``). This thin shim
keeps the old ``video_generation`` name working for one release so existing seed
entities don't break: it delegates single-segment requests to ``video_generate``
and, for length > the model's single-segment limit, generates each segment and
concatenates them via ``video_edit``.

**Removal:** delete this file + its registration once seed entities are migrated
off ``video_generation`` (track `03` V6). Marked ``status=DEPRECATED`` so the
tool-visibility layer hides it from new agents.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from src.ai.tools.base import Tool, ToolStatus
from src.ai.tools.media.video._support import MAX_SEGMENT_SECONDS, calculate_segments
from src.ai.tools.media.video.video_edit import VideoEditTool
from src.ai.tools.media.video.video_generate import VideoGenerateTool

logger = logging.getLogger(__name__)


class VideoGenerationTool(Tool):
    """Deprecated: composes the split video tools. Prefer video_generate/edit/add_sound."""

    name = "video_generation"
    status = ToolStatus.DEPRECATED
    description = (
        "DEPRECATED — use 'video_generate' (single clip) + 'video_edit' (compose) "
        "+ 'video_add_sound' (audio) instead. Kept for backward compatibility: "
        "generates a video from a text prompt, auto-splitting + merging for "
        "durations longer than the model's single-segment limit. Same JSON input "
        "as before: 'model_name', 'prompt', 'length_seconds', optional "
        "'is_audio_required' / 'start_frame_path' / 'end_frame_path'."
    )

    def __init__(self) -> None:
        self._generate = VideoGenerateTool()
        self._edit = VideoEditTool()

    def get_function_schema(self) -> Dict[str, Any]:
        schema = self._generate.get_function_schema()
        schema["name"] = self.name
        schema["description"] = self.description
        return schema

    def supports_context(self) -> bool:
        return True

    async def run(self, input_data: str) -> str:
        return await self.run_with_context(input_data, context=None)

    async def run_with_context(
        self, input_data: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        try:
            params = json.loads(input_data)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON input"})

        length_seconds = int(params.get("length_seconds", 8))

        # Single segment: pure delegation to video_generate.
        if length_seconds <= MAX_SEGMENT_SECONDS:
            return await self._generate.run_with_context(input_data, context)

        # Multi-segment: generate each segment, then concat via video_edit.
        segments = calculate_segments(length_seconds)
        clip_paths: List[str] = []
        for idx, seg in enumerate(segments):
            seg_params = dict(params)
            seg_params["length_seconds"] = seg
            # Only the first segment honors reference frames.
            if idx > 0:
                seg_params.pop("start_frame_path", None)
                seg_params.pop("end_frame_path", None)
            raw = await self._generate.run_with_context(json.dumps(seg_params), context)
            result = json.loads(raw)
            if "error" in result:
                return raw
            clip_paths.append(result["video_path"])

        concat_raw = await self._edit.run_with_context(
            json.dumps({"operation": "concat", "inputs": clip_paths}), context
        )
        concat = json.loads(concat_raw)
        if "error" in concat:
            return concat_raw

        # Clean up the intermediate segment clips.
        for path in clip_paths:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

        return json.dumps(
            {
                "model": params.get("model_name", "veo-3.1-generate-preview"),
                "prompt": params.get("prompt"),
                "video_path": concat["video_path"],
                "duration_seconds": sum(segments),
                "segments": len(segments),
                "segment_durations": segments,
                "has_audio": params.get("is_audio_required", True),
                "deprecated": "Use video_generate + video_edit instead.",
            }
        )

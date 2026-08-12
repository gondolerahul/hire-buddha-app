"""``video_edit`` — clip composition / editing / merging (Phase 12 `03`).

Operates on clips the agent already has (generated or uploaded) using ffmpeg
only — **no model cost**, just compute, metered through the sandbox runtime.
Supported operations: ``concat`` (merge in order), ``trim`` (cut a span),
``resize`` (rescale), ``transition`` (crossfade two clips), ``overlay``
(picture-in-picture), and ``extend`` (return a re-segmentation plan hint).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from src.ai.tools.base import Tool, ToolStatus
from src.ai.tools.media.video import _ffmpeg
from src.ai.tools.media.video._ffmpeg import FFmpegError
from src.ai.tools.media.video._support import (
    calculate_segments,
    new_output_path,
    register_video_artifact,
)

logger = logging.getLogger(__name__)

_OPERATIONS = ("concat", "trim", "resize", "transition", "overlay", "extend")


class VideoEditTool(Tool):
    """ffmpeg-backed composition over existing clips (no model cost)."""

    name = "video_edit"
    status = ToolStatus.EXPERIMENTAL
    description = (
        "Compose or edit existing video clips with ffmpeg (no AI model cost). "
        "Input is a JSON string with 'operation' (one of: concat, trim, resize, "
        "transition, overlay, extend) and operation-specific params. "
        "concat: {'inputs': [paths...]} merges in order. "
        "trim: {'inputs': [path], 'start': sec, 'duration'|'end': sec}. "
        "resize: {'inputs': [path], 'width': px, 'height': px} (-1 keeps aspect). "
        "transition: {'inputs': [a, b], 'duration': sec, 'transition': 'fade'}. "
        "overlay: {'inputs': [base, top], 'x': px, 'y': px}. "
        "extend: {'length_seconds': N} returns a segment plan for video_generate. "
        "Optional 'output_path' for any op."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": list(_OPERATIONS)},
                    "inputs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Input clip path(s) for the operation",
                    },
                    "output_path": {"type": "string", "description": "Optional output path"},
                    "start": {"type": "number", "description": "trim: start second"},
                    "duration": {"type": "number", "description": "trim/transition: seconds"},
                    "end": {"type": "number", "description": "trim: end second"},
                    "width": {"type": "integer", "description": "resize: target width (-1 = auto)"},
                    "height": {"type": "integer", "description": "resize: target height (-1 = auto)"},
                    "x": {"type": "integer", "description": "overlay: x offset"},
                    "y": {"type": "integer", "description": "overlay: y offset"},
                    "length_seconds": {"type": "integer", "description": "extend: total target length"},
                },
                "required": ["operation"],
            },
        }

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

        operation = params.get("operation")
        if operation not in _OPERATIONS:
            return json.dumps(
                {"error": f"Unknown operation '{operation}'. Expected one of {list(_OPERATIONS)}."}
            )
        company_id = context.get("company_id") if context else params.get("company_id")
        inputs: List[str] = params.get("inputs") or []

        # extend is pure planning math — no ffmpeg, no inputs required.
        if operation == "extend":
            length = int(params.get("length_seconds", 0))
            if length <= 0:
                return json.dumps({"error": "extend requires a positive 'length_seconds'"})
            segments = calculate_segments(length)
            return json.dumps(
                {
                    "operation": "extend",
                    "length_seconds": length,
                    "segment_plan": segments,
                    "message": (
                        "Generate each segment with video_generate, then compose "
                        "with video_edit concat."
                    ),
                }
            )

        for clip in inputs:
            if not os.path.exists(clip):
                return json.dumps({"error": f"Input clip not found: {clip}"})

        output_path = params.get("output_path") or new_output_path(company_id, prefix=operation)
        try:
            if operation == "concat":
                if not inputs:
                    return json.dumps({"error": "concat requires 'inputs'"})
                await _ffmpeg.concat_clips(context, inputs, output_path)
            elif operation == "trim":
                if len(inputs) != 1:
                    return json.dumps({"error": "trim requires exactly one input clip"})
                await _ffmpeg.trim_clip(
                    context,
                    inputs[0],
                    output_path,
                    start=float(params.get("start", 0.0)),
                    duration=(float(params["duration"]) if "duration" in params else None),
                    end=(float(params["end"]) if "end" in params else None),
                )
            elif operation == "resize":
                if len(inputs) != 1:
                    return json.dumps({"error": "resize requires exactly one input clip"})
                await _ffmpeg.resize_clip(
                    context,
                    inputs[0],
                    output_path,
                    width=int(params.get("width", -1)),
                    height=int(params.get("height", -1)),
                )
            elif operation == "transition":
                if len(inputs) != 2:
                    return json.dumps({"error": "transition requires exactly two input clips"})
                await self._transition(context, inputs, output_path, params)
            elif operation == "overlay":
                if len(inputs) != 2:
                    return json.dumps({"error": "overlay requires exactly two input clips (base, top)"})
                await self._overlay(context, inputs, output_path, params)
        except FFmpegError as exc:
            return json.dumps({"error": f"video_edit {operation} failed: {exc}"})
        except Exception as exc:  # noqa: BLE001
            logger.error("video_edit %s error: %s", operation, exc, exc_info=True)
            return json.dumps({"error": f"video_edit {operation} failed: {exc}"})

        await register_video_artifact(
            company_id,
            output_path,
            purpose=f"video_edit {operation}",
            generated_by=f"video_edit:{operation}",
            extra_metadata={"operation": operation, "inputs": inputs},
        )
        return json.dumps(
            {"operation": operation, "video_path": output_path, "inputs": inputs}
        )

    async def _transition(
        self,
        context: Optional[Dict[str, Any]],
        inputs: List[str],
        output_path: str,
        params: Dict[str, Any],
    ) -> None:
        """Crossfade ``inputs[0]`` into ``inputs[1]`` over ``duration`` seconds."""
        duration = float(params.get("duration", 1.0))
        kind = str(params.get("transition", "fade"))
        first_dur = await _ffmpeg.probe_duration(context, inputs[0])
        # xfade offset = (first clip length - transition duration); fall back to 0.
        offset = max(0.0, (first_dur or duration) - duration)
        filtergraph = (
            f"[0][1]xfade=transition={kind}:duration={duration:g}:offset={offset:g}[v];"
            f"[0:a][1:a]acrossfade=d={duration:g}[a]"
        )
        try:
            await _ffmpeg.run_ffmpeg(
                context,
                [
                    "-i", inputs[0], "-i", inputs[1],
                    "-filter_complex", filtergraph,
                    "-map", "[v]", "-map", "[a]", output_path,
                ],
            )
        except FFmpegError:
            # Clips may have no audio stream — retry video-only.
            await _ffmpeg.run_ffmpeg(
                context,
                [
                    "-i", inputs[0], "-i", inputs[1],
                    "-filter_complex",
                    f"[0][1]xfade=transition={kind}:duration={duration:g}:offset={offset:g}",
                    output_path,
                ],
            )

    async def _overlay(
        self,
        context: Optional[Dict[str, Any]],
        inputs: List[str],
        output_path: str,
        params: Dict[str, Any],
    ) -> None:
        """Overlay ``inputs[1]`` onto ``inputs[0]`` at ``(x, y)`` (picture-in-picture)."""
        x = int(params.get("x", 0))
        y = int(params.get("y", 0))
        await _ffmpeg.run_ffmpeg(
            context,
            [
                "-i", inputs[0], "-i", inputs[1],
                "-filter_complex", f"[0][1]overlay={x}:{y}",
                output_path,
            ],
        )

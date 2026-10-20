"""``music_generation`` — compose music with the configured Lyria model.

The model is the company's (else the platform's) ``MUSIC_GENERATION``
integration (``audio_models``): Lyria 3 makes a 30-second clip
(``lyria-3-clip-preview``) or a full song (``lyria-3-pro-preview``), Lyria 2 a
30-second instrumental. The audio is kept as an artifact of the run. Billed
per piece.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from pydantic import Field

from src.ai.tools.base import NO_CONTEXT_ERROR, Tool, ToolOutput, ToolParams, context_company_id
from src.ai.tools.media import audio_models

logger = logging.getLogger(__name__)


class MusicGenerationParams(ToolParams):
    prompt: str = Field(..., min_length=1, max_length=2000,
                        description="The music: genre, mood, instruments, tempo, and lyrics if any")
    negative_prompt: Optional[str] = Field(None, max_length=500, description="What to leave out")
    model_name: Optional[str] = Field(None, description="Music model; omit for the configured one")


class MusicGenerationTool(Tool):
    name = "music_generation"
    description = (
        "Compose original music from a description (genre, mood, instruments, tempo, optional "
        "lyrics) with the configured music model. Returns the audio file's path; use it as a "
        "music bed with video_add_sound (source 'file')."
    )
    Params = MusicGenerationParams
    timeout_seconds = 300

    async def execute(self, params: MusicGenerationParams, ctx: Dict[str, Any]) -> ToolOutput:
        company_id = context_company_id(ctx)
        if not company_id:
            return ToolOutput.failed(NO_CONTEXT_ERROR, code="no_context")
        try:
            audio = await audio_models.generate_music(
                company_id, params.prompt, negative_prompt=params.negative_prompt, model=params.model_name)
        except audio_models.MediaModelUnavailable as exc:
            return ToolOutput.failed(str(exc), code="model_unavailable")
        except Exception as exc:  # noqa: BLE001 - surface a clean tool error
            logger.warning("music_generation failed: %s", exc)
            return ToolOutput.failed(f"music_generation failed: {exc}", code="provider_error")

        from src.ai.artifact_service import save_tool_output

        artifact = await save_tool_output(
            ctx, file_name=f"music_{uuid.uuid4().hex[:8]}.{audio.extension}", file_bytes=audio.data,
            mime_type=audio.mime_type, file_category="audio", generated_by=f"music_generation:{audio.model}",
            purpose=f"Music: {params.prompt[:180]}",
            extra_metadata={"model": audio.model, "seconds": audio.seconds, "caption": (audio.caption or "")[:1000]},
        )
        output: Dict[str, Optional[Any]] = {
            "audio_path": artifact.file_path, "artifact_id": str(artifact.id), "model": audio.model,
            "duration_seconds": round(audio.seconds, 1) if audio.seconds else None,
        }
        if audio.caption:
            output["caption"] = audio.caption[:1000]
        return ToolOutput(output=output, metadata={"billable_units": 1})

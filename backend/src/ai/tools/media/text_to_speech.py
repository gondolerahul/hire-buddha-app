"""``text_to_speech`` — speak text with the configured Gemini TTS model.

The model is the company's (else the platform's) ``SPEECH_GENERATION``
integration (``audio_models``); the WAV is kept as an artifact of the run.
Billed per second of speech (``billable_units``).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from pydantic import Field

from src.ai.tools.base import NO_CONTEXT_ERROR, Tool, ToolOutput, ToolParams, context_company_id
from src.ai.tools.media import audio_models

logger = logging.getLogger(__name__)


class TextToSpeechParams(ToolParams):
    text: str = Field(..., min_length=1, max_length=5000, description="What to say")
    voice: Optional[str] = Field(
        None, description="A Gemini prebuilt voice (e.g. Kore, Puck, Charon, Aoede); omit for the configured one")
    style: Optional[str] = Field(
        None, max_length=300, description="How to say it, e.g. 'Say warmly and slowly'")
    model_name: Optional[str] = Field(None, description="Speech model; omit for the configured one")


class TextToSpeechTool(Tool):
    name = "text_to_speech"
    description = (
        "Turn text into natural speech (a WAV audio file) with the configured text-to-speech "
        "model. Choose a voice and describe the delivery in 'style'. Returns the audio file's "
        "path and its length; use it as narration with video_add_sound (source 'file')."
    )
    Params = TextToSpeechParams
    timeout_seconds = 180

    async def execute(self, params: TextToSpeechParams, ctx: Dict[str, Any]) -> ToolOutput:
        company_id = context_company_id(ctx)
        if not company_id:
            return ToolOutput.failed(NO_CONTEXT_ERROR, code="no_context")
        try:
            audio = await audio_models.synthesize_speech(
                company_id, params.text, voice=params.voice, style=params.style, model=params.model_name)
        except audio_models.MediaModelUnavailable as exc:
            return ToolOutput.failed(str(exc), code="model_unavailable")
        except Exception as exc:  # noqa: BLE001 - surface a clean tool error
            logger.warning("text_to_speech failed: %s", exc)
            return ToolOutput.failed(f"text_to_speech failed: {exc}", code="provider_error")

        from src.ai.artifact_service import save_tool_output

        artifact = await save_tool_output(
            ctx, file_name=f"speech_{uuid.uuid4().hex[:8]}.{audio.extension}", file_bytes=audio.data,
            mime_type=audio.mime_type, file_category="audio", generated_by=f"text_to_speech:{audio.model}",
            purpose=f"Speech: {params.text[:180]}",
            extra_metadata={"model": audio.model, "voice": params.voice, "seconds": audio.seconds},
        )
        seconds = round(audio.seconds or 0.0, 2)
        return ToolOutput(
            output={"audio_path": artifact.file_path, "artifact_id": str(artifact.id), "model": audio.model,
                    "duration_seconds": seconds},
            metadata={"billable_units": seconds or 1},
        )

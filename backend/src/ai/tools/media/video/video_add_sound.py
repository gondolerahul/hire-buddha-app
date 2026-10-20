"""``video_add_sound`` — attach / mix an audio track onto a clip (Phase 12 `03`).

Veo's native audio flag stays on ``video_generate``; this tool is for a
*separate* voiceover / music bed / SFX track the agent supplies or synthesizes.
ffmpeg muxing/mixing runs in the per-tenant container (metered as compute).

Sources:
* ``file``     — mux/mix a supplied ``audio_path`` (fully supported, no model cost).
* ``tts``      — narrate ``text`` with the configured speech model (Gemini TTS),
  billed as ``text_to_speech`` seconds.
* ``generated``— a music bed from ``music_prompt`` with the configured music
  model (Lyria), billed as one ``music_generation`` piece.

``tts`` and ``generated`` need a configured model (``audio_models``); without one
they return a structured, non-fatal error rather than a silent no-op so the
planner can fall back to a supplied ``file``.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from src.ai.tools.base import NO_CONTEXT_ERROR, Tool, ToolStatus, context_company_id
from src.ai.tools.sandbox.workspace import PathOutsideWorkspace, confine_params_async
from src.ai.tools.media.video import _ffmpeg
from src.ai.tools.media.video._ffmpeg import FFmpegError
from src.ai.tools.media.video._support import new_output_path, register_video_artifact

logger = logging.getLogger(__name__)

_SOURCES = ("file", "tts", "generated")


class VideoAddSoundTool(Tool):
    """Attach or mix an audio track onto an existing video clip."""
    timeout_seconds = 300  # per call (EP-08)

    name = "video_add_sound"
    status = ToolStatus.EXPERIMENTAL
    description = (
        "Attach or mix an audio track (voiceover, music bed, SFX) onto an "
        "existing video clip with ffmpeg. Input is a JSON string with: "
        "'video_path' (required), 'source' (one of: file, tts, generated), "
        "'mode' ('replace' to swap the audio or 'overlay' to mix with existing), "
        "and source params: file -> 'audio_path'; tts -> 'text' (+ optional "
        "'voice'); generated -> 'music_prompt'. Optional mix params: 'gain' (dB "
        "for the new track), 'loop' (bool, loop audio to video length), "
        "'fade' (seconds of in/out fade), and 'output_path'."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "video_path": {"type": "string", "description": "Input video clip path"},
                    "source": {"type": "string", "enum": list(_SOURCES)},
                    "mode": {
                        "type": "string",
                        "enum": ["replace", "overlay"],
                        "description": "Replace the audio track or mix with existing audio",
                    },
                    "audio_path": {"type": "string", "description": "file source: audio path"},
                    "text": {"type": "string", "description": "tts source: narration text"},
                    "voice": {"type": "string", "description": "tts source: voice name"},
                    "music_prompt": {"type": "string", "description": "generated source: music description"},
                    "gain": {"type": "number", "description": "Gain (dB) applied to the new track"},
                    "loop": {"type": "boolean", "description": "Loop the audio to the video length"},
                    "fade": {"type": "number", "description": "Fade in/out duration in seconds"},
                    "output_path": {"type": "string", "description": "Optional output path"},
                },
                "required": ["video_path", "source"],
            },
        }

    async def run(self, input_data: str) -> str:
        return await self.run_with_context(input_data, context=None)

    async def run_with_context(
        self, input_data: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        try:
            params = json.loads(input_data)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON input"})

        video_path = params.get("video_path")
        source = params.get("source")
        mode = params.get("mode", "replace")
        company_id = context_company_id(context)
        if not company_id:
            return json.dumps({"error": NO_CONTEXT_ERROR})
        # Paths the model gives resolve inside this company's files (TL-54).
        try:
            await confine_params_async(params, company_id, ('video_path', 'audio_path', 'output_path'))
        except PathOutsideWorkspace as exc:
            return json.dumps({"error": str(exc)})
        video_path = params.get('video_path')

        if not video_path:
            return json.dumps({"error": "Missing required parameter: 'video_path'"})
        if not os.path.exists(video_path):
            return json.dumps({"error": f"Video not found: {video_path}"})
        if source not in _SOURCES:
            return json.dumps({"error": f"Unknown source '{source}'. Expected one of {list(_SOURCES)}."})
        if mode not in ("replace", "overlay"):
            return json.dumps({"error": "mode must be 'replace' or 'overlay'"})

        # Resolve the audio track for this call; generated audio is billed as
        # the tool that makes it (also_bill).
        also_bill: Dict[str, float] = {}
        if source == "file":
            audio_path = params.get("audio_path")
            if not audio_path or not os.path.exists(audio_path):
                return json.dumps({"error": "file source requires an existing 'audio_path'"})
        elif source == "tts":
            resolved = await self._synthesize_tts(
                context, params.get("text"), params.get("voice"), company_id
            )
            if isinstance(resolved, dict):  # structured error
                return json.dumps(resolved)
            audio_path, seconds = resolved
            also_bill["text_to_speech"] = round(seconds or 1.0, 2)
        else:  # generated
            resolved = await self._generate_music(context, params.get("music_prompt"), company_id)
            if isinstance(resolved, dict):
                return json.dumps(resolved)
            audio_path, _ = resolved
            also_bill["music_generation"] = 1

        output_path = params.get("output_path") or new_output_path(company_id, prefix="sound")
        try:
            await self._mux(context, video_path, audio_path, output_path, mode, params)
        except FFmpegError as exc:
            return json.dumps({"error": f"video_add_sound failed: {exc}"})
        except Exception as exc:  # noqa: BLE001
            logger.error("video_add_sound error: %s", exc, exc_info=True)
            return json.dumps({"error": f"video_add_sound failed: {exc}"})

        artifact = await register_video_artifact(
            context,
            output_path,
            purpose=f"video_add_sound ({source}/{mode})",
            generated_by=f"video_add_sound:{source}",
            extra_metadata={"source": source, "mode": mode},
        )
        result: Dict[str, Any] = {"source": source, "mode": mode, "video_path": artifact.file_path,
                                  "artifact_id": str(artifact.id), "audio_path": audio_path}
        if also_bill:
            result["also_bill"] = also_bill
        return json.dumps(result)

    async def _mux(
        self,
        context: Optional[Dict[str, Any]],
        video_path: str,
        audio_path: str,
        output_path: str,
        mode: str,
        params: Dict[str, Any],
    ) -> None:
        """Build the ffmpeg argv for replace/overlay + optional gain/loop/fade."""
        gain = params.get("gain")
        fade = params.get("fade")
        loop = bool(params.get("loop", False))

        pre: List[str] = ["-i", video_path]
        if loop:
            pre += ["-stream_loop", "-1"]
        pre += ["-i", audio_path]

        # Build an audio filter chain applied to the new track ([1:a]).
        new_chain: List[str] = []
        if gain is not None:
            new_chain.append(f"volume={float(gain)}dB")
        if fade is not None:
            dur = await _ffmpeg.probe_duration(context, video_path)
            new_chain.append(f"afade=t=in:st=0:d={float(fade):g}")
            if dur:
                out_start = max(0.0, dur - float(fade))
                new_chain.append(f"afade=t=out:st={out_start:g}:d={float(fade):g}")

        if mode == "overlay":
            # Mix the (filtered) new track with the video's existing audio.
            filtergraph = f"[1:a]{','.join(new_chain) or 'anull'}[na];[0:a][na]amix=inputs=2:duration=first[a]"
            args = [
                *pre,
                "-filter_complex", filtergraph,
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-shortest", output_path,
            ]
            try:
                await _ffmpeg.run_ffmpeg(context, args)
                return
            except FFmpegError:
                # The base clip has no audio stream — degrade to replace.
                mode = "replace"

        # replace: drop any existing audio, use the (filtered) new track.
        if new_chain:
            filtergraph = f"[1:a]{','.join(new_chain)}[a]"
            args = [
                *pre,
                "-filter_complex", filtergraph,
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-shortest", output_path,
            ]
        else:
            args = [
                *pre,
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-shortest", output_path,
            ]
        await _ffmpeg.run_ffmpeg(context, args)

    async def _synthesize_tts(
        self,
        context: Optional[Dict[str, Any]],
        text: Optional[str],
        voice: Optional[str],
        company_id: Optional[str],
    ) -> Any:
        """Narration as ``(audio file, seconds)``, or a structured error dict."""
        if not text:
            return {"error": "tts source requires 'text'"}
        from src.ai.tools.media import audio_models

        try:
            audio = await audio_models.synthesize_speech(company_id, text, voice=voice)
        except audio_models.MediaModelUnavailable as exc:
            return {
                "error": "tts_provider_unavailable",
                "message": (f"{exc}. Supply a pre-rendered narration via source='file' and "
                            "'audio_path', or configure a speech model."),
            }
        return _keep_working_audio(company_id, audio, "narration"), audio.seconds

    async def _generate_music(
        self,
        context: Optional[Dict[str, Any]],
        music_prompt: Optional[str],
        company_id: Optional[str],
    ) -> Any:
        """A music bed as ``(audio file, seconds)``, or a structured error dict."""
        if not music_prompt:
            return {"error": "generated source requires 'music_prompt'"}
        from src.ai.tools.media import audio_models

        try:
            audio = await audio_models.generate_music(company_id, music_prompt)
        except audio_models.MediaModelUnavailable as exc:
            return {
                "error": "music_provider_unavailable",
                "message": f"{exc}. Supply a music file via source='file' and 'audio_path'.",
            }
        return _keep_working_audio(company_id, audio, "music"), audio.seconds


def _keep_working_audio(company_id: Optional[str], audio: Any, prefix: str) -> str:
    """Generated audio as a file beside the company's working videos, for ffmpeg."""
    path = new_output_path(company_id, prefix=prefix, ext=audio.extension)
    with open(path, "wb") as fh:
        fh.write(audio.data)
    return path

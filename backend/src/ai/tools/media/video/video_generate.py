"""``video_generate`` — AI generation of a single video segment (Phase 12 `03`).

Text-(or image-)to-video for one segment within the model's native limit (≤8s
for Veo 3.1): one model call → one clip. Segment math and ffmpeg merging moved
to ``video_edit``; audio muxing to ``video_add_sound``. For longer videos the
agent plans ``video_generate`` per segment + one ``video_edit`` concat — an
explicit, inspectable plan rather than hidden auto-splitting.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, Optional, cast

from src.ai.tools.base import Tool, ToolStatus
from src.ai.tools.media.video._support import (
    MAX_SEGMENT_SECONDS,
    company_video_dir,
    register_video_artifact,
)

logger = logging.getLogger(__name__)

try:
    from google import genai  # noqa: F401
    from google.genai import types

    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logger.warning("google.genai SDK not available for video generation")

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class VideoGenerateTool(Tool):
    """Generate a single AI video segment from a text prompt (+ optional frames)."""

    name = "video_generate"
    status = ToolStatus.EXPERIMENTAL
    description = (
        "Generate a single video segment from a text prompt using an AI model "
        "(Veo 3.1). One model call produces one clip up to the model's native "
        "limit (8s for Veo 3.1). For longer videos, generate multiple segments "
        "and compose them with the 'video_edit' tool. Input is a JSON string "
        "with: 'model_name' (e.g. 'veo-3.1-generate-preview'), 'prompt' (text), "
        "'length_seconds' (<= model max), optional 'is_audio_required' (bool, "
        "default true), and optional 'start_frame_path' / 'end_frame_path' "
        "(reference image paths)."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "model_name": {
                        "type": "string",
                        "description": "Video model (e.g. 'veo-3.1-generate-preview')",
                    },
                    "prompt": {"type": "string", "description": "Text description of the clip"},
                    "length_seconds": {
                        "type": "integer",
                        "description": "Clip length in seconds (<= model max, 8 for Veo 3.1)",
                    },
                    "is_audio_required": {
                        "type": "boolean",
                        "description": "Whether the model should include audio (default true)",
                    },
                    "start_frame_path": {
                        "type": "string",
                        "description": "Optional image path for the starting frame",
                    },
                    "end_frame_path": {
                        "type": "string",
                        "description": "Optional image path for the ending frame",
                    },
                },
                "required": ["model_name", "prompt", "length_seconds"],
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

        model_name = params.get("model_name", "veo-3.1-generate-preview")
        prompt = params.get("prompt")
        length_seconds = int(params.get("length_seconds", 8))
        is_audio_required = params.get("is_audio_required", True)
        start_frame_path = params.get("start_frame_path")
        end_frame_path = params.get("end_frame_path")
        company_id = context.get("company_id") if context else params.get("company_id")

        if not prompt:
            return json.dumps({"error": "Missing required parameter: 'prompt'"})
        if not GENAI_AVAILABLE:
            return json.dumps(
                {"error": "Google GenAI SDK not installed. Run: pip install google-genai"}
            )

        # Single-segment tool: refuse (with a structured hint) rather than
        # silently auto-splitting. The agent composes segments via video_edit.
        if length_seconds > MAX_SEGMENT_SECONDS:
            return json.dumps(
                {
                    "error": "length_exceeds_single_segment",
                    "message": (
                        f"{length_seconds}s exceeds the single-segment limit "
                        f"({MAX_SEGMENT_SECONDS}s). Generate segments with "
                        "video_generate and compose them with video_edit (concat)."
                    ),
                    "max_segment_seconds": MAX_SEGMENT_SECONDS,
                }
            )

        duration = length_seconds if length_seconds in (4, 5, 6, 8) else min(length_seconds, 8)

        try:
            service_metadata = await self._resolve_vertex_metadata(company_id)
            if not service_metadata or not service_metadata.get("project_id"):
                return json.dumps(
                    {
                        "error": (
                            "No Vertex AI configuration found for video generation. "
                            "Configure a 'google' integration with project_id in "
                            "service_metadata for this company."
                        )
                    }
                )

            from src.common.genai_factory import build_vertex_genai_client_sync

            client = build_vertex_genai_client_sync(service_metadata)
            output_path = os.path.join(
                company_video_dir(company_id), f"clip_{uuid.uuid4().hex[:8]}.mp4"
            )
            saved_path = await self._generate_single_video(
                client=client,
                model_name=model_name,
                prompt=prompt,
                duration=duration,
                start_frame_path=start_frame_path,
                end_frame_path=end_frame_path,
                output_path=output_path,
            )

            await register_video_artifact(
                company_id,
                saved_path,
                purpose=f"AI-generated video: {prompt}",
                generated_by=f"video_generate:{model_name}",
                extra_metadata={"model": model_name, "prompt": prompt, "duration": duration},
            )
            return json.dumps(
                {
                    "model": model_name,
                    "prompt": prompt,
                    "video_path": saved_path,
                    "duration_seconds": duration,
                    "has_audio": is_audio_required,
                }
            )
        except TimeoutError as exc:
            logger.error("Video generation timeout: %s", exc)
            return json.dumps({"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - surface a clean tool error
            logger.error("Video generation error: %s", exc, exc_info=True)
            return json.dumps({"error": f"Video generation failed: {exc}"})

    async def _generate_single_video(
        self,
        *,
        client: Any,
        model_name: str,
        prompt: str,
        duration: int,
        start_frame_path: Optional[str] = None,
        end_frame_path: Optional[str] = None,
        output_path: str,
    ) -> str:
        """Generate one clip and save it to ``output_path`` (returns the path)."""
        config = types.GenerateVideosConfig(
            number_of_videos=1,
            duration_seconds=str(duration),  # type: ignore[arg-type]  # Veo API accepts str
            person_generation="allow_all",
        )
        gen_kwargs: Dict[str, Any] = {"model": model_name, "prompt": prompt, "config": config}

        if start_frame_path and os.path.exists(start_frame_path):
            gen_kwargs["image"] = self._load_image(start_frame_path)
        if end_frame_path and os.path.exists(end_frame_path):
            config.last_frame = self._load_image(end_frame_path)

        logger.info("video_generate: model=%s duration=%ss", model_name, duration)
        operation = client.models.generate_videos(**gen_kwargs)

        max_wait, elapsed, poll = 360, 0, 10
        while not operation.done:
            if elapsed >= max_wait:
                raise TimeoutError(f"Video generation timed out after {max_wait}s")
            await asyncio.sleep(poll)
            elapsed += poll
            operation = client.operations.get(operation)

        if not operation.response or not operation.response.generated_videos:
            raise ValueError("No video was generated - possibly filtered by safety")

        generated = operation.response.generated_videos[0]
        client.files.download(file=generated.video)
        generated.video.save(output_path)
        logger.info("video_generate: saved %s (%ss)", output_path, duration)
        return output_path

    @staticmethod
    def _load_image(path: str) -> Any:
        with open(path, "rb") as fh:
            image_bytes = fh.read()
        ext = os.path.splitext(path)[1].lower()
        return types.Image(image_bytes=image_bytes, mime_type=_MIME_BY_EXT.get(ext, "image/png"))

    async def _resolve_vertex_metadata(
        self, company_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Resolve the Vertex AI service_metadata from the integration registry."""
        if not company_id:
            return None
        try:
            from uuid import UUID

            from sqlalchemy import select

            from src.common.database import AsyncSessionLocal
            from src.config.models import IntegrationRegistry
            from src.config.service import ConfigService

            async with AsyncSessionLocal() as db:
                config_service = ConfigService(db)
                company_uuid = UUID(str(company_id))
                result = await db.execute(
                    select(IntegrationRegistry).where(
                        IntegrationRegistry.company_id == company_uuid,
                        IntegrationRegistry.service_category == "VIDEO_GENERATION",
                        IntegrationRegistry.status == "active",
                    )
                )
                entry = result.scalars().first()
                if entry and entry.service_metadata:
                    return cast(Dict[str, Any], entry.service_metadata)

                integration = await config_service.get_integration_by_provider(
                    company_uuid, "google"
                ) or await config_service.get_integration_by_provider(company_uuid, "gemini")
                if integration and integration.service_metadata:
                    return cast(Dict[str, Any], integration.service_metadata)
        except Exception as exc:  # noqa: BLE001 - DB lookup is best-effort
            logger.warning("[video_generate] integration lookup failed (company=%s): %s", company_id, exc)
        return None

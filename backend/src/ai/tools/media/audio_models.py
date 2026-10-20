"""Speech and music from the configured Vertex models (Gemini TTS, Lyria).

One place resolves which model serves a company — its own active
``SPEECH_GENERATION`` / ``MUSIC_GENERATION`` integration, else the platform's —
and makes the call, for the ``text_to_speech`` and ``music_generation`` tools
and for ``video_add_sound``'s ``tts`` and ``generated`` sources.

Every Vertex call takes its credentials from ``genai_factory`` (on Azure:
Google workload identity federation, no key file).

* Gemini TTS (``gemini-*-tts``): ``generateContent`` with audio output; the
  model returns WAV, or raw 16-bit PCM (``audio/l16``) that is wrapped as WAV.
* Lyria 3 (``lyria-3-*``): ``generateContent`` with audio *and* text output
  (audio alone is refused); MP3 plus a caption.
* Lyria 2 (``lyria-002``): the ``predict`` endpoint; a 30-second WAV.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import urllib.request
import wave
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "Kore"


class MediaModelUnavailable(RuntimeError):
    """No active integration of the category, for the company or the platform."""


@dataclass(frozen=True)
class MediaModel:
    model: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Audio:
    data: bytes
    mime_type: str
    extension: str
    model: str
    seconds: Optional[float] = None
    caption: Optional[str] = None


async def media_model(company_id: Any, category: str, requested: Optional[str] = None) -> MediaModel:
    """The model serving ``category`` for the company: its own active
    integration, else the platform's. ``requested`` picks among them by
    ``model_name`` and otherwise keeps the configured project and region."""
    from sqlalchemy import select

    from src.ai.usage_service import app_company_id
    from src.common.tenancy.session import control_session
    from src.config.models import IntegrationRegistry

    try:
        owners = [UUID(str(company_id))] if company_id else []
    except ValueError:
        owners = []
    try:
        async with control_session() as db:
            platform = await app_company_id(db)
            if platform and platform not in owners:
                owners.append(platform)
            for owner in owners:
                rows = (await db.execute(
                    select(IntegrationRegistry).where(
                        IntegrationRegistry.company_id == owner,
                        IntegrationRegistry.service_category == category,
                        IntegrationRegistry.status == "active",
                    ).order_by(IntegrationRegistry.created_at)
                )).scalars().all()
                if not rows:
                    continue
                chosen = next((r for r in rows if requested and r.model_name == requested), rows[0])
                return MediaModel(model=requested or chosen.model_name or "",
                                  metadata=dict(chosen.service_metadata or {}))
    except Exception as exc:  # noqa: BLE001 - the lookup failing is "no model" to the caller
        logger.warning("%s model lookup failed (company=%s): %s", category, company_id, exc)
        raise MediaModelUnavailable(f"the {category} model could not be looked up") from exc
    raise MediaModelUnavailable(f"no {category} model is configured (AI Model Configuration page)")


def _client(metadata: Dict[str, Any]) -> Any:
    from src.common.genai_factory import build_vertex_genai_client_sync
    return build_vertex_genai_client_sync(metadata)


def _as_wav(data: bytes, mime_type: str) -> bytes:
    """WAV bytes: as given, or 16-bit mono PCM (``audio/l16; rate=…``) wrapped."""
    if data[:4] == b"RIFF":
        return data
    rate = int((re.search(r"rate=(\d+)", mime_type or "") or [0, 24000])[1])
    channels = int((re.search(r"channels=(\d+)", mime_type or "") or [0, 1])[1])
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data)
    return out.getvalue()


def wav_seconds(data: bytes) -> Optional[float]:
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, ZeroDivisionError):
        return None


async def synthesize_speech(company_id: Any, text: str, *, voice: Optional[str] = None,
                            style: Optional[str] = None, model: Optional[str] = None) -> Audio:
    """``text`` spoken by the configured Gemini TTS model, as WAV."""
    from google.genai import types

    chosen = await media_model(company_id, "SPEECH_GENERATION", model)
    voice = voice or chosen.metadata.get("voice") or DEFAULT_VOICE
    prompt = f"{style.strip()}: {text}" if style and style.strip() else text
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
    )
    response = await _client(chosen.metadata).aio.models.generate_content(
        model=chosen.model, contents=prompt, config=config)
    blob = next((p.inline_data for p in _parts(response) if p.inline_data and p.inline_data.data), None)
    if blob is None:
        raise RuntimeError(f"{chosen.model} returned no audio")
    data = _as_wav(blob.data, blob.mime_type or "")
    return Audio(data=data, mime_type="audio/wav", extension="wav", model=chosen.model,
                 seconds=wav_seconds(data))


async def generate_music(company_id: Any, prompt: str, *, negative_prompt: Optional[str] = None,
                         model: Optional[str] = None) -> Audio:
    """A piece of music from the configured Lyria model."""
    chosen = await media_model(company_id, "MUSIC_GENERATION", model)
    if chosen.model.startswith("lyria-3"):
        return await _lyria_generate_content(chosen, prompt, negative_prompt)
    return await asyncio.to_thread(_lyria_predict, chosen, prompt, negative_prompt)


async def _lyria_generate_content(chosen: MediaModel, prompt: str, negative_prompt: Optional[str]) -> Audio:
    from google.genai import types

    if negative_prompt:
        prompt = f"{prompt}\nAvoid: {negative_prompt}"
    response = await _client(chosen.metadata).aio.models.generate_content(
        model=chosen.model, contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["AUDIO", "TEXT"]))
    audio, texts = None, []
    for part in _parts(response):
        if part.inline_data and part.inline_data.data:
            audio = part.inline_data
        elif part.text:
            texts.append(part.text)
    if audio is None:
        raise RuntimeError(f"{chosen.model} returned no audio")
    caption = "\n".join(texts).strip() or None
    seconds = None
    match = re.search(r"duration_secs:\s*([\d.]+)", caption or "")
    if match:
        seconds = float(match.group(1))
    mime = (audio.mime_type or "audio/mpeg").split(";")[0]
    extension = "wav" if mime == "audio/wav" else "mp3"
    return Audio(data=audio.data, mime_type=mime, extension=extension, model=chosen.model,
                 seconds=seconds, caption=caption)


def _lyria_predict(chosen: MediaModel, prompt: str, negative_prompt: Optional[str]) -> Audio:
    import google.auth.transport.requests

    from src.common.genai_factory import google_credentials

    project = chosen.metadata.get("project_id")
    region = chosen.metadata.get("region") or "us-central1"
    if not project:
        raise MediaModelUnavailable(f"{chosen.model}: the integration has no project_id")
    credentials = google_credentials()
    if credentials is None:
        import google.auth
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(google.auth.transport.requests.Request())
    instance: Dict[str, Any] = {"prompt": prompt}
    if negative_prompt:
        instance["negative_prompt"] = negative_prompt
    host = "aiplatform.googleapis.com" if region == "global" else f"{region}-aiplatform.googleapis.com"
    request = urllib.request.Request(
        f"https://{host}/v1/projects/{project}/locations/{region}/publishers/google/models/{chosen.model}:predict",
        data=json.dumps({"instances": [instance], "parameters": {"sample_count": 1}}).encode(),
        headers={"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        body = json.load(response)
    predictions = body.get("predictions") or []
    if not predictions or not predictions[0].get("bytesBase64Encoded"):
        raise RuntimeError(f"{chosen.model} returned no audio")
    data = base64.b64decode(predictions[0]["bytesBase64Encoded"])
    return Audio(data=data, mime_type="audio/wav", extension="wav", model=chosen.model,
                 seconds=wav_seconds(data))


def _parts(response: Any) -> list:
    candidates = getattr(response, "candidates", None) or []
    content = getattr(candidates[0], "content", None) if candidates else None
    return list(getattr(content, "parts", None) or [])

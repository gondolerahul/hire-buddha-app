"""Speech and music as configurable models and tools (Gemini TTS, Lyria).

``audio_models`` resolves the configured SPEECH_GENERATION / MUSIC_GENERATION
model and calls it; ``text_to_speech`` and ``music_generation`` keep the audio
as run artifacts and report their billed units; ``video_add_sound`` narrates
and scores with the same models and bills them as those tools.
"""
from __future__ import annotations

import base64
import io
import json
import wave
from types import SimpleNamespace
from typing import Any, List

import pytest

import src.ai.tools  # noqa: F401  (registers every tool)
from src.ai.tool_executor import ToolResult
from src.ai.tools.base import ToolOutput, ToolRegistry, _legacy_output
from src.ai.tools.media import audio_models
from src.ai.tools.media.audio_models import Audio, MediaModel, MediaModelUnavailable
from src.ai.tools.media.music_generation import MusicGenerationTool
from src.ai.tools.media.text_to_speech import TextToSpeechTool

CTX = {"company_id": "00000000-0000-0000-0000-0000000000c1", "run_id": "r1"}


def _pcm(seconds: float, rate: int = 24000) -> bytes:
    return b"\x00\x00" * int(seconds * rate)


def _wav(seconds: float, rate: int = 24000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(_pcm(seconds, rate))
    return out.getvalue()


def _response(*parts: Any) -> Any:
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=list(parts)))])


def _audio_part(data: bytes, mime: str) -> Any:
    return SimpleNamespace(inline_data=SimpleNamespace(data=data, mime_type=mime), text=None)


def _text_part(text: str) -> Any:
    return SimpleNamespace(inline_data=None, text=text)


class _FakeClient:
    def __init__(self, response: Any, calls: List[dict]):
        async def generate_content(**kwargs):
            calls.append(kwargs)
            return response
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


def _configure(monkeypatch, model: str, response: Any, metadata=None) -> List[dict]:
    calls: List[dict] = []

    async def fake_media_model(company_id, category, requested=None):
        return MediaModel(model=requested or model, metadata=metadata or {"project_id": "p", "region": "global"})

    monkeypatch.setattr(audio_models, "media_model", fake_media_model)
    monkeypatch.setattr(audio_models, "_client", lambda metadata: _FakeClient(response, calls))
    return calls


@pytest.fixture
def kept(monkeypatch) -> List[dict]:
    """Artifacts the tools keep, without storage or a database."""
    saved: List[dict] = []

    async def fake_save(context, **kwargs):
        saved.append(kwargs)
        return SimpleNamespace(id="a1", file_path=f"/artifacts/{kwargs['file_name']}")

    import src.ai.artifact_service as artifact_service
    monkeypatch.setattr(artifact_service, "save_tool_output", fake_save)
    return saved


# ── audio_models ─────────────────────────────────────────────────────────────


def test_raw_pcm_is_wrapped_as_wav_and_wav_is_kept():
    wrapped = audio_models._as_wav(_pcm(2.0), "audio/l16; rate=24000; channels=1")
    assert wrapped[:4] == b"RIFF" and audio_models.wav_seconds(wrapped) == pytest.approx(2.0)
    already = _wav(1.5)
    assert audio_models._as_wav(already, "audio/wav") is already


@pytest.mark.asyncio
async def test_speech_uses_the_configured_model_voice_and_style(monkeypatch):
    calls = _configure(monkeypatch, "gemini-3.8-flash-tts",
                       _response(_audio_part(_pcm(3.0), "audio/l16; rate=24000; channels=1")),
                       metadata={"project_id": "p", "region": "global", "voice": "Puck"})
    audio = await audio_models.synthesize_speech(CTX["company_id"], "Hello there", style="Say warmly")
    assert (audio.model, audio.mime_type, audio.extension) == ("gemini-3.8-flash-tts", "audio/wav", "wav")
    assert audio.seconds == pytest.approx(3.0)
    call = calls[0]
    assert call["model"] == "gemini-3.8-flash-tts"
    assert call["contents"] == "Say warmly: Hello there"
    assert call["config"].response_modalities == ["AUDIO"]
    assert call["config"].speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"


@pytest.mark.asyncio
async def test_lyria_3_asks_for_audio_and_text_and_keeps_the_caption(monkeypatch):
    calls = _configure(monkeypatch, "lyria-3-pro-preview", _response(
        _text_part("bpm: 90.0\nduration_secs: 106.8"), _audio_part(b"ID3mp3bytes", "audio/mpeg")))
    audio = await audio_models.generate_music(CTX["company_id"], "warm folk", negative_prompt="drums")
    assert calls[0]["config"].response_modalities == ["AUDIO", "TEXT"]
    assert calls[0]["contents"] == "warm folk\nAvoid: drums"
    assert (audio.extension, audio.mime_type, audio.seconds) == ("mp3", "audio/mpeg", 106.8)
    assert "bpm" in audio.caption


@pytest.mark.asyncio
async def test_lyria_2_uses_the_predict_endpoint(monkeypatch):
    async def fake_media_model(company_id, category, requested=None):
        return MediaModel(model="lyria-002", metadata={"project_id": "proj", "region": "us-central1"})

    seen = {}

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        seen["url"], seen["body"] = request.full_url, json.loads(request.data)
        body = {"predictions": [{"bytesBase64Encoded": base64.b64encode(_wav(30.0, 48000)).decode()}]}
        return _Response(json.dumps(body).encode())

    credentials = SimpleNamespace(token="t", refresh=lambda request: None)
    monkeypatch.setattr(audio_models, "media_model", fake_media_model)
    monkeypatch.setattr(audio_models.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("src.common.genai_factory.google_credentials", lambda: credentials)

    audio = await audio_models.generate_music(CTX["company_id"], "calm guitar", negative_prompt="vocals")
    assert seen["url"] == ("https://us-central1-aiplatform.googleapis.com/v1/projects/proj/locations/"
                           "us-central1/publishers/google/models/lyria-002:predict")
    assert seen["body"]["instances"] == [{"prompt": "calm guitar", "negative_prompt": "vocals"}]
    assert audio.seconds == pytest.approx(30.0) and audio.extension == "wav"


@pytest.mark.asyncio
async def test_no_configured_model_is_unavailable_not_a_crash():
    # No database in the unit tier: the lookup failing is "no model" to the caller.
    with pytest.raises(MediaModelUnavailable):
        await audio_models.media_model("not-a-uuid", "SPEECH_GENERATION")


# ── the tools ────────────────────────────────────────────────────────────────


def test_both_tools_are_registered_and_typed():
    for name, cls in (("text_to_speech", TextToSpeechTool), ("music_generation", MusicGenerationTool)):
        tool = ToolRegistry.get_tool(name)
        assert isinstance(tool, cls) and tool.Params is not None


@pytest.mark.asyncio
async def test_text_to_speech_keeps_the_audio_and_bills_its_seconds(monkeypatch, kept):
    async def fake_speech(company_id, text, **kwargs):
        return Audio(data=_wav(4.25), mime_type="audio/wav", extension="wav", model="gemini-3.8-flash-tts",
                     seconds=4.25)

    monkeypatch.setattr(audio_models, "synthesize_speech", fake_speech)
    out = await TextToSpeechTool().invoke({"text": "Welcome", "voice": "Kore"}, CTX)
    assert out.success
    assert out.output["duration_seconds"] == 4.25 and out.output["model"] == "gemini-3.8-flash-tts"
    assert out.metadata["billable_units"] == 4.25
    assert kept[0]["file_category"] == "audio" and kept[0]["file_name"].endswith(".wav")


@pytest.mark.asyncio
async def test_text_to_speech_without_a_model_fails_cleanly(monkeypatch, kept):
    async def unavailable(*args, **kwargs):
        raise MediaModelUnavailable("no SPEECH_GENERATION model is configured")

    monkeypatch.setattr(audio_models, "synthesize_speech", unavailable)
    out = await TextToSpeechTool().invoke({"text": "Welcome"}, CTX)
    assert not out.success and out.error_code == "model_unavailable"
    assert kept == []


@pytest.mark.asyncio
async def test_a_tool_refuses_without_a_company():
    out = await TextToSpeechTool().invoke({"text": "Welcome"}, {})
    assert not out.success and out.error_code == "no_context"


@pytest.mark.asyncio
async def test_music_generation_keeps_the_piece_and_bills_one(monkeypatch, kept):
    async def fake_music(company_id, prompt, **kwargs):
        return Audio(data=b"mp3", mime_type="audio/mpeg", extension="mp3", model="lyria-3-clip-preview",
                     seconds=30.0, caption="An indie folk loop")

    monkeypatch.setattr(audio_models, "generate_music", fake_music)
    out = await MusicGenerationTool().invoke({"prompt": "indie folk loop"}, CTX)
    assert out.success and out.metadata["billable_units"] == 1
    assert out.output["caption"] == "An indie folk loop" and out.output["audio_path"].endswith(".mp3")
    assert kept[0]["mime_type"] == "audio/mpeg"


@pytest.mark.asyncio
async def test_unknown_arguments_are_refused():
    out = await MusicGenerationTool().invoke({"prompt": "x", "company_id": "other"}, CTX)
    assert not out.success and out.error_code == "invalid_arguments"


# ── billing plumbing ─────────────────────────────────────────────────────────


def test_a_legacy_tools_billing_keys_are_lifted_out_of_what_the_model_reads():
    out = _legacy_output(json.dumps({"video_path": "v.mp4", "billable_units": 8,
                                     "also_bill": {"text_to_speech": 3.5}}))
    assert out.metadata == {"billable_units": 8, "also_bill": {"text_to_speech": 3.5}}
    assert json.loads(out.output) == {"video_path": "v.mp4"}
    plain = _legacy_output('{"error": "x"}')
    assert plain.metadata == {} and plain.output == '{"error": "x"}'
    assert _legacy_output("not json").output == "not json"


def test_a_result_is_billed_as_itself_then_its_also_bill():
    result = ToolResult(tool="video_add_sound", args={}, output="", success=True, units=1.0,
                        also_bill={"text_to_speech": 3.5})
    assert result.charges() == [("video_add_sound", 1.0), ("text_to_speech", 3.5)]
    assert ToolResult(tool="calculator", args={}, output="", success=True).charges() == [("calculator", 1.0)]


@pytest.mark.asyncio
async def test_the_executor_carries_units_and_also_bill(monkeypatch):
    from src.ai.tool_executor import _run

    class _Tool:
        timeout_seconds = 5

        async def invoke(self, args, context):
            return ToolOutput(output="ok", metadata={"billable_units": 2.5, "also_bill": {"music_generation": 1}})

    result = await _run(_Tool(), "video_add_sound", {}, {}, None)
    assert result.units == 2.5 and result.also_bill == {"music_generation": 1.0}

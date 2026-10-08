"""One Gemini Live config builder; no prosody it cannot send (VT-11, VT-12, HD13).

There were two builders returning the same dict, so the model registry changed
nothing and the agent's language reached no model; ``speaking_rate`` and
``pitch`` were stored, parsed and dropped — Gemini Live's ``SpeechConfig``
has neither. Each config is checked against the SDK's own ``LiveConnectConfig``.
"""
from __future__ import annotations

import pytest
from google.genai import types

from src.ai.schemas.persona import VoiceConfig
from src.voice.call_guards import END_CALL_TOOL


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("src.common.genai_factory.build_vertex_genai_client_sync", lambda meta: object())
    from src.voice.gemini_live import GeminiLiveClient
    return GeminiLiveClient(system_instruction="You are Asha.", service_metadata={},
                            voice_config=VoiceConfig(voice_name="Kore", language_code="hi-IN"))


def test_a_native_audio_model_chooses_its_language(client):
    config = client.create_session_config(model="gemini-3.1-flash-live-preview", tools=[END_CALL_TOOL])
    assert config["speech_config"] == {"voice_config": {"prebuilt_voice_config": {"voice_name": "Kore"}}}
    assert config["tools"] == [{"function_declarations": [END_CALL_TOOL]}]
    types.LiveConnectConfig(**config)                       # the SDK accepts every key


def test_a_half_cascade_model_speaks_the_agents_language(client):
    config = client.create_session_config(model="gemini-2.0-flash-exp")
    assert config["speech_config"]["language_code"] == "hi-IN"
    assert types.LiveConnectConfig(**config).speech_config.language_code == "hi-IN"


def test_a_model_the_registry_does_not_know_is_sent_no_language(client):
    config = client.create_session_config(model="gemini-live-2.5-flash-preview")
    assert "language_code" not in config["speech_config"]


def test_the_two_models_differ_only_in_the_language(client):
    native = client.create_session_config(model="gemini-2.5-flash-live-001")
    cascade = client.create_session_config(model="gemini-2.0-flash-exp")
    cascade["speech_config"].pop("language_code")
    assert native == cascade


def test_a_voice_has_no_speaking_rate_or_pitch():
    assert set(types.SpeechConfig.model_fields) >= {"voice_config", "language_code"}
    assert not {"speaking_rate", "pitch"} & set(types.SpeechConfig.model_fields)
    assert not {"speaking_rate", "pitch"} & set(VoiceConfig.model_fields)
    saved = VoiceConfig(**{"voice_name": "Puck", "speaking_rate": 1.5, "pitch": 2.0})   # an agent saved before
    assert saved.voice_name == "Puck"

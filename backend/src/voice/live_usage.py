"""live_usage.py — what a speech-to-speech call used, as the provider reports it (VT-05).

A call's model cost was estimated at a flat 167 tokens per second, and both
the audio-in and the audio-out rows were billed for the whole call — a call
where the customer did all the talking cost the same as one where the agent
did, and nothing could be reconciled with the provider's bill.

Gemini Live sends ``usage_metadata`` on its server messages. Each one
describes that turn (the turn's whole context is processed again), so the
call's usage is their **sum** — summing matched Google's bill in developers'
reconciliations, while taking only the last message under-counted many times
over. The modality breakdown (audio, text, …) is kept for the usage row.

When the provider reports nothing, each direction falls back to the audio it
actually carried (VT-I1): seconds sent to the model (PCM16 at 16 kHz) and
seconds received from it (PCM16 at 24 kHz), not the whole call twice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

IN_BYTES_PER_SECOND = 32_000   # PCM16 mono at 16 kHz, what the socket sends
OUT_BYTES_PER_SECOND = 48_000  # PCM16 mono at 24 kHz, what the model returns


def _modality(detail: Any) -> str:
    modality = getattr(detail, "modality", None)
    return str(getattr(modality, "value", modality) or "UNKNOWN").upper()


@dataclass
class LiveUsage:
    prompt_tokens: int = 0
    response_tokens: int = 0
    prompt_by_modality: dict[str, int] = field(default_factory=dict)
    response_by_modality: dict[str, int] = field(default_factory=dict)
    messages: int = 0
    audio_in_bytes: int = 0
    audio_out_bytes: int = 0

    def add(self, usage: Any) -> None:
        """Fold in one server message's ``usage_metadata``."""
        if usage is None:
            return
        self.messages += 1
        self.prompt_tokens += int(getattr(usage, "prompt_token_count", 0) or 0)
        self.prompt_tokens += int(getattr(usage, "tool_use_prompt_token_count", 0) or 0)
        self.response_tokens += int(getattr(usage, "response_token_count", 0) or 0)
        self.response_tokens += int(getattr(usage, "thoughts_token_count", 0) or 0)
        for detail in getattr(usage, "prompt_tokens_details", None) or []:
            key = _modality(detail)
            self.prompt_by_modality[key] = self.prompt_by_modality.get(key, 0) + int(
                getattr(detail, "token_count", 0) or 0)
        for detail in getattr(usage, "response_tokens_details", None) or []:
            key = _modality(detail)
            self.response_by_modality[key] = self.response_by_modality.get(key, 0) + int(
                getattr(detail, "token_count", 0) or 0)

    def sent(self, pcm16_bytes: int) -> None:
        self.audio_in_bytes += max(int(pcm16_bytes), 0)

    def received(self, pcm_bytes: int) -> None:
        self.audio_out_bytes += max(int(pcm_bytes), 0)

    @property
    def reported(self) -> bool:
        """The provider sent usage for this call."""
        return self.messages > 0 and (self.prompt_tokens + self.response_tokens) > 0

    @property
    def seconds_in(self) -> int:
        return round(self.audio_in_bytes / IN_BYTES_PER_SECOND)

    @property
    def seconds_out(self) -> int:
        return round(self.audio_out_bytes / OUT_BYTES_PER_SECOND)

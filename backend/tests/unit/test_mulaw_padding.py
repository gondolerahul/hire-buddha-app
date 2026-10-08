"""A short last mu-law chunk is padded with silence, not a click (VT-17).

``ensure_chunk_size`` padded with ``0x00`` — in mu-law the loudest negative
sample, a burst of full-scale noise. ``0xFF`` is silence.
"""
from __future__ import annotations

import audioop

from src.voice.audio_processor import AudioProcessor


def _peak(mulaw: bytes) -> int:
    return max(abs(s) for s in memoryview(audioop.ulaw2lin(mulaw, 2)).cast("h"))


def test_a_short_last_chunk_is_padded_with_silence():
    chunks = AudioProcessor.ensure_chunk_size(b"\x7e" * 170, target_size=160)
    assert [len(c) for c in chunks] == [160, 160]
    padding = chunks[1][10:]
    assert padding == b"\xff" * 150
    assert _peak(padding) == 0                    # decodes to zero amplitude
    assert _peak(b"\x00") > 30000                 # what it padded with before


def test_whole_chunks_are_untouched():
    audio = bytes(range(256)) * 5                 # 1280 bytes, eight chunks
    assert b"".join(AudioProcessor.ensure_chunk_size(audio)) == audio

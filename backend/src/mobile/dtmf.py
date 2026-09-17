"""
DTMF sequence collection for mobile-dialer AI legs.

The app sends keypad sequences on the AI leg (docs 03 ADR-001 §4):
  ``*NNNN#``   — call-attempt token (identifies the lead)
  ``*NNNNNN#`` — device verification code (captures the rep's caller ID)
  ``#``        — lone hash after ai_ready: "merged" fallback when data is poor

Pure logic, no I/O — the stream handler feeds digits from provider ``dtmf``
events and acts on the emitted sequences.
"""
from dataclasses import dataclass
from typing import Optional

ATTEMPT_TOKEN_LENGTH = 4
VERIFICATION_CODE_LENGTH = 6
# A partial "*12" older than this is abandoned (a new '*' also restarts).
SEQUENCE_TIMEOUT_SECONDS = 3.0

KIND_ATTEMPT_TOKEN = "attempt_token"
KIND_VERIFICATION_CODE = "verification_code"
KIND_MERGE_SIGNAL = "merge_signal"
KIND_INVALID = "invalid"


@dataclass(frozen=True)
class DtmfSequence:
    kind: str
    value: str = ""


class DtmfCollector:
    """Accumulates digits between ``*`` and ``#``."""

    def __init__(self, timeout_seconds: float = SEQUENCE_TIMEOUT_SECONDS):
        self.timeout_seconds = timeout_seconds
        self._buffer: Optional[str] = None  # None = not inside a *...# sequence
        self._last_digit_at: Optional[float] = None

    @property
    def in_sequence(self) -> bool:
        return self._buffer is not None

    def feed(self, digit: str, now: float) -> Optional[DtmfSequence]:
        """Feed one key press; returns a sequence when one completes."""
        if not digit:
            return None
        digit = str(digit).strip()[:1]

        if (
            self._buffer is not None
            and self._last_digit_at is not None
            and now - self._last_digit_at > self.timeout_seconds
        ):
            self._buffer = None
        self._last_digit_at = now

        if digit == "*":
            self._buffer = ""
            return None

        if digit == "#":
            if self._buffer is None:
                return DtmfSequence(KIND_MERGE_SIGNAL)
            value, self._buffer = self._buffer, None
            if len(value) == ATTEMPT_TOKEN_LENGTH:
                return DtmfSequence(KIND_ATTEMPT_TOKEN, value)
            if len(value) == VERIFICATION_CODE_LENGTH:
                return DtmfSequence(KIND_VERIFICATION_CODE, value)
            return DtmfSequence(KIND_INVALID, value)

        if digit.isdigit() and self._buffer is not None:
            self._buffer += digit
            if len(self._buffer) > VERIFICATION_CODE_LENGTH:
                self._buffer = None  # garbage; wait for the next '*'
        return None

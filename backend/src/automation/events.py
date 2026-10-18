"""Events (tech spec §7.2, Appendix B): ids, types, dedupe keys, chain depth.

An event is stored once per tenant, under a time-ordered id (UUIDv7) and a
``dedupe_key`` unique per tenant: a second event with the same key is
acknowledged and dropped (a provider retrying a webhook, a scheduler tick
twice). ``chain_depth`` counts how many agent runs caused it; the router
stops a chain past the limit (§7.8).
"""
from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

SCHEMA_VERSION = 2
TRUST_LEVELS = ("verified", "unverified", "internal")
MAX_INLINE_DATA_BYTES = 256 * 1024  # larger payloads go to storage (data_ref)

# Who may produce which event types (Appendix B). Agents and apps emit only custom.*.
PLATFORM_PREFIXES = (
    "schedule.", "timer.", "record.", "run.", "approval.", "social.", "whatsapp.", "email.",
    "github.", "sheet.", "crm.", "connection.", "schema.", "app.", "automation.",
)
_TYPE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+){1,5}$")
_CUSTOM = re.compile(r"^custom\.[a-z][a-z0-9_]{0,63}(\.[a-z0-9_]{1,64}){0,3}$")


class EventError(ValueError):
    pass


def uuid7(now_ms: Optional[int] = None) -> uuid.UUID:
    """A UUIDv7 (RFC 9562): 48-bit Unix milliseconds, then random bits — ids sort by time."""
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76                              # version 7
    value |= ((rand >> 62) & 0xFFF) << 64           # rand_a, 12 bits
    value |= 0b10 << 62                             # RFC 4122 variant
    value |= rand & ((1 << 62) - 1)                 # rand_b, 62 bits
    return uuid.UUID(int=value)


def uuid7_time(value: uuid.UUID) -> datetime:
    """When a UUIDv7 was made (naive UTC)."""
    return datetime.fromtimestamp((value.int >> 80) / 1000, tz=timezone.utc).replace(tzinfo=None)


def validate_type(event_type: Any) -> str:
    if not isinstance(event_type, str) or not _TYPE.match(event_type) or len(event_type) > 128:
        raise EventError(f"{event_type!r} is not an event type like social.comment.created")
    return event_type


def validate_custom_type(event_type: Any) -> str:
    """What an agent's ``emit_event`` may use: ``custom.<name>`` only (tech spec §7.10)."""
    if not isinstance(event_type, str) or not _CUSTOM.match(event_type):
        raise EventError(f"{event_type!r}: agents emit only custom.<name> events "
                         "(lower-case letters, digits, underscores)")
    return event_type


def type_matches(pattern: str, event_type: str) -> bool:
    """A trigger's ``event_type`` against an event's: exact, or ``prefix.*``."""
    if pattern.endswith(".*"):
        return event_type.startswith(pattern[:-1])
    return pattern == event_type


def schedule_dedupe_key(trigger_id: Any, scheduled_for: datetime) -> str:
    """One ``schedule.fired`` per trigger per scheduled time, whatever ticks twice (§7.6)."""
    return f"schedule:{trigger_id}:{scheduled_for.replace(microsecond=0).isoformat()}"


def run_dedupe_key(run_id: Any, outcome: str) -> str:
    return f"run:{run_id}:{outcome}"


@dataclass
class Envelope:
    """Envelope v2 (§7.2): what is stored in ``platform.events`` and routed."""

    type: str
    source: str
    dedupe_key: str
    data: Dict[str, Any] = field(default_factory=dict)
    subject: Optional[str] = None
    trust: str = "verified"
    id: uuid.UUID = field(default_factory=uuid7)
    time: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    causation_id: Optional[uuid.UUID] = None
    correlation_id: Optional[uuid.UUID] = None
    chain_depth: int = 0
    data_ref: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_type(self.type)
        if self.trust not in TRUST_LEVELS:
            raise EventError(f"trust must be one of {', '.join(TRUST_LEVELS)}")
        if not self.dedupe_key or len(self.dedupe_key) > 512:
            raise EventError("dedupe_key is required (at most 512 characters)")
        if self.chain_depth < 0:
            raise EventError("chain_depth cannot be negative")
        if self.correlation_id is None:
            self.correlation_id = self.id

    def caused(self, event_type: str, *, data: Dict[str, Any], source: str, dedupe_key: str,
               subject: Optional[str] = None) -> "Envelope":
        """An event this one led to through a run: one step deeper in the chain."""
        return Envelope(type=event_type, source=source, dedupe_key=dedupe_key, data=data, subject=subject,
                        trust="internal", causation_id=self.id, correlation_id=self.correlation_id,
                        chain_depth=self.chain_depth + 1)

    def as_dict(self) -> Dict[str, Any]:
        """The JSON form (filters and templates read this)."""
        out = asdict(self)
        for key in ("id", "causation_id", "correlation_id"):
            out[key] = str(out[key]) if out[key] else None
        out["time"] = self.time.isoformat() + "Z"
        return out

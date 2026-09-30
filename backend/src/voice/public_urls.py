"""The URLs telephony providers are handed to reach this API (SA-01).

Twilio and Tata open the media-stream WebSocket (``/stream/twilio/{id}``,
``/stream/tata/{id}``); Twilio also fetches TwiML and posts status callbacks.
All of them are built here from ``STREAMING_HOST`` and ``STREAMING_PROTOCOL``.
The seven copies this replaces each fell back to the retired voice service on
:8002, and the campaign executor ignored ``STREAMING_PROTOCOL`` altogether.
"""
from src.common.config import settings


def stream_url(path: str) -> str:
    """A media-stream WebSocket URL, e.g. ``stream_url(f"/stream/twilio/{sid}")``."""
    return f"{settings.STREAMING_PROTOCOL}://{settings.STREAMING_HOST}{path}"


def callback_url(path: str) -> str:
    """An HTTP URL a provider calls back on — https whenever streams are wss."""
    scheme = "https" if settings.STREAMING_PROTOCOL == "wss" else "http"
    return f"{scheme}://{settings.STREAMING_HOST}{path}"

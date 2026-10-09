"""A scripted WebRTC peer through /stream/video (GW-10, HD11).

A real aiortc client offers an audio and a video track over the endpoint's
signalling; the server answers, the tracks connect over loopback, the audio
reaches the (fake) live model as 16 kHz PCM16 and a frame is described. Needs
``aiortc`` installed (``backend/pyproject.toml`` declares it); the model, the
vision call and the bill are fakes.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal

import pytest

aiortc = pytest.importorskip("aiortc")

from aiortc import RTCPeerConnection, RTCSessionDescription  # noqa: E402
from aiortc.mediastreams import AudioStreamTrack, VideoStreamTrack  # noqa: E402

from src.common.config import settings  # noqa: E402
from src.gateway import video_gateway  # noqa: E402


class _PeerSocket:
    """The server's end of the signalling socket, fed by the test."""

    def __init__(self):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.client = None
        self.url = None
        self.closed = None

    async def accept(self):
        pass

    async def receive_text(self):
        return await self.inbox.get()

    async def send_text(self, text):
        await self.outbox.put(json.loads(text))

    async def send_bytes(self, data):
        await self.outbox.put(data)

    async def close(self, code=1000, reason=""):
        self.closed = self.closed or (code, reason)


class _Live:
    def __init__(self):
        self.chunks: list = []
        self.context: list = []

    async def send_realtime_input(self, *, audio=None, text=None):
        self.chunks.append(audio)

    async def send_client_content(self, *, turns=None, turn_complete=True):
        self.context.append(turns)

    async def receive(self):
        await asyncio.sleep(3600)
        yield None


async def _next_event(ws: _PeerSocket, name: str, timeout: float = 10.0) -> dict:
    while True:
        msg = await asyncio.wait_for(ws.outbox.get(), timeout)
        if isinstance(msg, dict) and msg.get("event") == name:
            return msg


async def _until(predicate, seconds=10.0):
    for _ in range(int(seconds / 0.05)):
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


@pytest.mark.asyncio
async def test_a_peer_connects_and_its_audio_reaches_the_model(monkeypatch):
    company, live, described = str(uuid.uuid4()), _Live(), []

    async def _company(ws, hs):
        return company

    class _Dispatcher:
        async def resolve_agent_for_client(self, *_a, **_k):
            return {"company_id": company, "agent_id": str(uuid.uuid4())}

    class _Slot:
        released = False

        def release(self):
            _Slot.released = True

    async def _admit(ws, company_id):
        return _Slot()

    async def _connect(self):
        self.live_session = live
        return live

    async def _describe(self, jpeg):
        described.append(len(jpeg))
        self.vision_context = "A test pattern."
        await self.share_vision_context()

    async def _no_bill(self, db, *a, **k):
        return Decimal("0")

    monkeypatch.setattr(video_gateway, "stream_company", _company)
    monkeypatch.setattr(video_gateway, "get_dispatcher", lambda: _Dispatcher())
    monkeypatch.setattr(video_gateway, "handshake_allowed", lambda ws: True)
    monkeypatch.setattr(video_gateway, "_admit", _admit)
    monkeypatch.setattr(video_gateway.VideoSession, "_connect_live", _connect)
    monkeypatch.setattr(video_gateway.VideoSession, "_analyze_video_frame", _describe)
    monkeypatch.setattr("src.gateway.call_spend.CallSpend.record_live_audio", _no_bill)
    monkeypatch.setattr("src.gateway.call_spend.CallSpend.finish", _no_bill)
    monkeypatch.setattr(settings, "VIDEO_STREAMING_ENABLED", True)

    ws = _PeerSocket()
    server = asyncio.create_task(video_gateway.unified_video_streaming(ws))
    client = RTCPeerConnection()
    try:
        await ws.inbox.put(json.dumps({"event": "connect", "provider": "web", "token": "t"}))
        connected = await _next_event(ws, "connected")
        assert connected["webrtc_enabled"] is True and connected["ice_servers"]

        client.addTrack(AudioStreamTrack())
        client.addTrack(VideoStreamTrack())
        await client.setLocalDescription(await client.createOffer())
        await ws.inbox.put(json.dumps({"event": "offer", "sdp": client.localDescription.sdp,
                                       "type": client.localDescription.type}))
        answer = await _next_event(ws, "answer")
        await client.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))

        assert await _until(lambda: len(live.chunks) >= 10), "no audio reached the model"
        assert {c["mime_type"] for c in live.chunks} == {"audio/pcm;rate=16000"}
        # 20 ms of 16 kHz mono PCM16 per frame (the resampler may split one).
        assert sum(len(c["data"]) for c in live.chunks) >= 10 * 640 * 0.9
        assert await _until(lambda: described and live.context), "no frame was described and shared"
    finally:
        await ws.inbox.put(json.dumps({"event": "stop"}))
        await asyncio.wait_for(server, 15)
        await client.close()
    assert _Slot.released

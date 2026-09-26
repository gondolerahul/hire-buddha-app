"""
WS /mobile/ws — server push to the Android app (docs 06 §5), served by the gateway.

Protocol:
  client -> {"type": "auth", "access_token": "...", "device_id": "uuid"}   (within 5 s)
  server -> {"type": "auth.ok"} then pushes; {"type": "ping"} every 20 s
  client -> {"type": "pong"}; silence for 60 s closes the socket
  client -> {"type": "signal", "signal": "lead_answered" | "merged", "attempt_id": "uuid"}
            relayed straight to the live AI leg. The same facts also arrive as call
            events over HTTP, but a POST after a few idle seconds pays for a new
            connection (1-2 s on mobile data) — dead air the lead hears.
Tokens never travel in the URL (Apache logs query strings).
"""
import asyncio
import json
import logging
import time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.mobile import realtime

logger = logging.getLogger(__name__)

router = APIRouter()

AUTH_TIMEOUT_SECONDS = 5
#: Client signals relayed to the call's control channel (stream_controller._on_control).
RELAYED_SIGNALS = ("lead_answered", "merged")
PING_INTERVAL_SECONDS = 20
IDLE_TIMEOUT_SECONDS = 60


async def _authenticate(token: str):
    from src.auth.dependencies import _authenticate_user
    from src.common.database import AsyncSessionLocal
    from src.mobile.service import MOBILE_ROLES

    async with AsyncSessionLocal() as db:
        user = await _authenticate_user(token, db)
    if user.role not in MOBILE_ROLES:
        raise PermissionError("role_not_supported")
    return user


async def _relay_signal(user, msg: dict) -> None:
    """Forward an app signal to the AI leg of one of this user's own attempts."""
    from sqlalchemy import select

    from src.common.database import AsyncSessionLocal
    from src.mobile.models import MobileCallAttempt

    signal = msg.get("signal")
    if signal not in RELAYED_SIGNALS:
        return
    try:
        attempt_id = UUID(str(msg.get("attempt_id")))
    except ValueError:
        return
    async with AsyncSessionLocal() as db:
        session_id = (await db.execute(
            select(MobileCallAttempt.voice_session_id).where(
                MobileCallAttempt.id == attempt_id,
                MobileCallAttempt.user_id == user.id,
                MobileCallAttempt.company_id == user.company_id,
            )
        )).scalar_one_or_none()
    if session_id is None:
        return
    await realtime.publish_session_control(session_id, signal, attempt_id=attempt_id, via="ws")


@router.websocket("/mobile/ws")
async def mobile_push_socket(websocket: WebSocket):
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        hello = json.loads(first)
        if hello.get("type") != "auth":
            raise ValueError("expected auth")
        user = await _authenticate(hello.get("access_token") or "")
    except Exception as e:
        logger.info(f"[MobileWS] auth failed: {type(e).__name__}")
        await websocket.close(code=4001, reason="unauthorized")
        return

    device_id: Optional[str] = hello.get("device_id")
    await websocket.send_text(json.dumps({"type": "auth.ok", "user_id": str(user.id)}))
    logger.info(f"[MobileWS] connected user={user.id} device={device_id}")

    last_client_msg = time.time()

    async def forward_pushes():
        async for msg in realtime.subscribe(realtime.user_push_channel(user.id)):
            target = msg.get("device_id")
            if target and device_id and str(target) != device_id and msg.get("type") != "device.verified":
                continue
            await websocket.send_text(json.dumps(msg))

    async def read_client():
        nonlocal last_client_msg
        while True:
            raw = await websocket.receive_text()
            last_client_msg = time.time()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif msg.get("type") == "signal":
                try:
                    await _relay_signal(user, msg)
                except Exception as e:  # a bad signal must not drop the push socket
                    logger.warning(f"[MobileWS] signal relay failed: {e}")

    async def heartbeat():
        while True:
            await asyncio.sleep(PING_INTERVAL_SECONDS)
            if time.time() - last_client_msg > IDLE_TIMEOUT_SECONDS:
                await websocket.close(code=4008, reason="idle")
                return
            await websocket.send_text(json.dumps({"type": "ping"}))

    tasks = [asyncio.create_task(t()) for t in (forward_pushes, read_client, heartbeat)]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"[MobileWS] disconnected user={user.id}")

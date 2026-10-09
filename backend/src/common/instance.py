"""Which API process answered — for the one-instance decision (GW-21, HD12).

The API keeps a call's state in its own process: the live model socket, the
audio buffers, a video call's peer connection, the company's live-session
count (GW-02). Decision HD12 (2026-10-08) is one API instance; a second needs
sticky sessions by ``session_id`` at the proxy and the live-session count in
Redis. ``GET /api/v1/health`` reports this block, so two answers from two
instances are told apart.
"""
from __future__ import annotations

import os
import socket
from datetime import datetime

__all__ = ["INSTANCE_ID", "STARTED_AT", "instance_info"]

# ``INSTANCE_ID`` from the environment names a deployed instance; otherwise
# the host and process, unique among processes alive at the same time.
INSTANCE_ID = os.environ.get("INSTANCE_ID") or f"{socket.gethostname()}:{os.getpid()}"
STARTED_AT = datetime.utcnow()


def instance_info() -> dict:
    from src.voice import live_sessions

    return {
        "id": INSTANCE_ID,
        "started_at": STARTED_AT.isoformat() + "Z",
        # Held in this process only (HD12): the count another instance holds is not here.
        "live_sessions": live_sessions.total_open(),
    }

"""An in-memory stand-in for the Redis calls a run's stream makes (GW-18).

``XADD`` / ``EXPIRE`` from the publishers, ``XREAD`` from the SSE endpoint,
with ids that increase like Redis's. ``on_block`` runs whenever a read would
wait, so a test can publish a frame "while the client waits".
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional


def _key(id_: str) -> tuple[int, int]:
    ms, seq = id_.split("-")
    return int(ms), int(seq)


class FakeStreamRedis:
    def __init__(self) -> None:
        self.entries: dict[str, list[tuple[str, str]]] = {}
        self.ttl: dict[str, int] = {}
        self.maxlen: dict[str, Any] = {}
        self.blocks: list[Optional[int]] = []
        self.on_block: Optional[Callable[[], None]] = None
        self._seq = 0

    def add(self, key: str, frame: dict) -> str:
        """Append a frame as a publisher would (synchronously, for set-up)."""
        self._seq += 1
        entry_id = f"{1700000000000 + self._seq}-0"
        self.entries.setdefault(key, []).append((entry_id, json.dumps(frame)))
        return entry_id

    async def xadd(self, key: str, fields: dict, maxlen: Any = None, approximate: bool = True) -> bytes:
        self.maxlen[key] = (maxlen, approximate)
        self._seq += 1
        entry_id = f"{1700000000000 + self._seq}-0"
        self.entries.setdefault(key, []).append((entry_id, fields["data"]))
        return entry_id.encode()

    async def expire(self, key: str, seconds: int) -> None:
        self.ttl[key] = seconds

    async def xread(self, streams: dict, count: Optional[int] = None, block: Optional[int] = None):
        self.blocks.append(block)
        ((key, after),) = streams.items()
        found = [(i, d) for i, d in self.entries.get(key, []) if _key(i) > _key(after)]
        if not found and block is not None and self.on_block is not None:
            self.on_block()
            found = [(i, d) for i, d in self.entries.get(key, []) if _key(i) > _key(after)]
        if count is not None:
            found = found[:count]
        if not found:
            return []
        return [[key.encode(), [(i.encode(), {b"data": d.encode()}) for i, d in found]]]

    async def close(self) -> None:
        pass

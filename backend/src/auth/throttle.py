"""Per-account counters that slow down password guessing and email bombing (AU-07).

The API-wide limit is 200 requests a minute **per client IP**, which does
nothing against a guesser spread over many addresses and nothing to protect one
account. These counters are keyed by the account's email (hashed), so they hold
however many addresses the attempts come from.

A fixed window in Redis: the first hit sets the key's expiry, and at ``limit``
hits the subject is refused until the key expires. If Redis cannot be reached
the check is skipped — an outage must not lock every user out — and a warning
is logged.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable

import redis.asyncio as redis

from src.common.config import settings

logger = logging.getLogger(__name__)


def _default_client() -> Any:
    return redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)


# Tests replace this with a fake; production opens one short-lived client per
# call, as the worker health check does, so no connection outlives its loop.
client_factory: Callable[[], Any] = _default_client


class Throttle:
    def __init__(self, name: str, limit: int, window_seconds: int) -> None:
        self.name, self.limit, self.window_seconds = name, limit, window_seconds

    def _key(self, subject: str) -> str:
        digest = hashlib.sha256(subject.strip().lower().encode()).hexdigest()
        return f"hb:throttle:{self.name}:{digest}"

    async def retry_after(self, subject: str) -> int:
        """Seconds until ``subject`` may try again; 0 when it may try now."""
        client = client_factory()
        try:
            count = await client.get(self._key(subject))
            if count is None or int(count) < self.limit:
                return 0
            return max(int(await client.ttl(self._key(subject))), 1)
        except Exception as exc:  # noqa: BLE001 — fail open, see module docstring
            logger.warning("throttle %s unavailable, not enforced: %s", self.name, exc)
            return 0
        finally:
            await _close(client)

    async def hit(self, subject: str) -> None:
        client = client_factory()
        try:
            key = self._key(subject)
            if await client.incr(key) == 1:
                await client.expire(key, self.window_seconds)
        except Exception as exc:  # noqa: BLE001
            logger.warning("throttle %s unavailable, not counted: %s", self.name, exc)
        finally:
            await _close(client)

    async def clear(self, subject: str) -> None:
        client = client_factory()
        try:
            await client.delete(self._key(subject))
        except Exception as exc:  # noqa: BLE001
            logger.warning("throttle %s unavailable, not cleared: %s", self.name, exc)
        finally:
            await _close(client)


async def _close(client: Any) -> None:
    close = getattr(client, "aclose", None)
    if close is not None:
        try:
            await close()
        except Exception:  # noqa: BLE001
            pass


# Ten wrong passwords for one account in 15 minutes locks that account's sign-in
# for the rest of the window; a correct password clears the count.
LOGIN_FAILURES = Throttle("login-failures", limit=10, window_seconds=15 * 60)
# Password-reset and verification emails to one address: five an hour.
ACCOUNT_EMAILS = Throttle("account-emails", limit=5, window_seconds=60 * 60)

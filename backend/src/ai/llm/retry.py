"""ai.llm.retry — one bounded retry and timeout around every provider call (LP-03).

Every adapter wraps each network call to its provider — one per ``generate``,
one per ReAct *turn* — in :func:`call_provider`. Retrying per call, not per
ReAct loop, matters: re-running a whole loop would re-run the tools its earlier
turns called, writes included.

Policy (settings ``LLM_CALL_*``):

- an explicit timeout on each attempt (``LLM_CALL_TIMEOUT_SECONDS``);
- up to ``LLM_CALL_MAX_ATTEMPTS`` attempts on a retryable failure — a timeout,
  a connection error, or HTTP 408/409/425/429/5xx/529 — with exponential
  backoff and full jitter from ``LLM_RETRY_BASE_SECONDS``, capped at
  ``LLM_RETRY_MAX_DELAY_SECONDS``, and never shorter than a ``Retry-After``;
- anything else (400, 401, 403, 404, a validation error) is raised at once.

The SDKs' own retries are turned off where they have them (``max_retries=0``)
so the two policies do not multiply.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Awaitable, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})
_RETRYABLE_NAMES = ("timeout", "ratelimit", "connection", "connecterror", "serviceunavailable",
                    "internalserver", "overloaded", "resourceexhausted", "deadlineexceeded")


class LLMTimeoutError(TimeoutError):
    """A provider call did not answer within ``LLM_CALL_TIMEOUT_SECONDS``."""


def _status(exc: BaseException) -> Optional[int]:
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True
    status = _status(exc)
    if status is not None:
        return status in RETRYABLE_STATUS
    name = type(exc).__name__.lower()
    return any(part in name for part in _RETRYABLE_NAMES)


def retry_after_seconds(exc: BaseException) -> Optional[float]:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    try:
        value = headers.get("retry-after")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _settings() -> tuple[int, float, float, float]:
    from src.common.config import settings
    return (max(1, int(settings.LLM_CALL_MAX_ATTEMPTS)),
            float(settings.LLM_CALL_TIMEOUT_SECONDS),
            float(settings.LLM_RETRY_BASE_SECONDS),
            float(settings.LLM_RETRY_MAX_DELAY_SECONDS))


async def call_provider(
    call: Callable[[], Awaitable[T]],
    *,
    what: str,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> T:
    """Run ``call()`` with the timeout and retry policy above."""
    attempts, timeout_s, base_s, max_delay_s = _settings()
    for attempt in range(1, attempts + 1):
        try:
            return await asyncio.wait_for(call(), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            error: BaseException = LLMTimeoutError(f"{what}: no answer within {timeout_s:g}s")
            error.__cause__ = exc
        except Exception as exc:                                           # noqa: BLE001
            error = exc
        if attempt == attempts or not is_retryable(error):
            raise error
        delay = random.uniform(0, min(max_delay_s, base_s * 2 ** (attempt - 1)))
        delay = max(delay, min(max_delay_s, retry_after_seconds(error) or 0.0))
        logger.warning("%s failed (attempt %d/%d): %s: %s; retrying in %.1fs",
                       what, attempt, attempts, type(error).__name__, error, delay)
        await sleep(delay)
    raise AssertionError("unreachable")                                    # pragma: no cover

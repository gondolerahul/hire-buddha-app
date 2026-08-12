"""
rate_limiter.py — Redis sliding-window rate limiter.

Phase 6: Provides global rate limiting for API calls, tool executions,
and LLM invocations. Uses Redis sorted sets for an efficient
sliding window implementation.
"""
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class RedisRateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets.

    Usage::

        limiter = RedisRateLimiter(redis)
        allowed = await limiter.check_and_consume(
            key="tool:search:company_123",
            limit=10,
            window_seconds=60,
        )
        if not allowed:
            raise RateLimitExceeded(...)
    """

    def __init__(self, redis: Any) -> None:
        """
        Args:
            redis: An async Redis connection (e.g. aioredis / redis-py asyncio).
        """
        self.redis = redis

    async def check_and_consume(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> bool:
        """Check rate limit and consume one token if allowed.

        Uses a Redis sorted set where each member is a timestamp.
        Old entries outside the window are pruned atomically.

        Returns True if the request is allowed (count <= limit).
        """
        if not self.redis:
            return True  # No Redis = no limiting

        now = time.time()
        window_start = now - window_seconds

        try:
            pipe = self.redis.pipeline()
            # Remove entries older than the window
            pipe.zremrangebyscore(key, 0, window_start)
            # Add current request
            pipe.zadd(key, {str(now): now})
            # Count entries in window
            pipe.zcard(key)
            # Auto-expire the key to avoid stale sets
            pipe.expire(key, window_seconds + 1)
            results = await pipe.execute()

            count: int = results[2]
            allowed = count <= limit

            if not allowed:
                logger.warning(
                    f"Rate limit exceeded for '{key}': "
                    f"{count}/{limit} in {window_seconds}s window"
                )

            return allowed
        except Exception as e:
            logger.warning(f"Rate limiter error for '{key}': {e}")
            return True  # Fail open — don't block on Redis errors

    async def get_remaining(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> int:
        """Get the number of remaining requests in the current window."""
        if not self.redis:
            return limit

        now = time.time()
        window_start = now - window_seconds

        try:
            pipe = self.redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zcard(key)
            results = await pipe.execute()
            count: int = results[1]
            return max(0, limit - count)
        except Exception:
            return limit

    async def reset(self, key: str) -> None:
        """Reset the rate limit for a key."""
        if self.redis:
            try:
                await self.redis.delete(key)
            except Exception:
                pass

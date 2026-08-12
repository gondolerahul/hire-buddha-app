"""
Unit tests for src.ai.rate_limiter
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.ai.governance.rate_limiter import RedisRateLimiter


def _make_pipe_mock(execute_return):
    """Create a properly mocked Redis pipeline."""
    pipe = MagicMock()
    pipe.zremrangebyscore = MagicMock(return_value=pipe)
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zcard = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=execute_return)
    return pipe


@pytest.fixture
def mock_redis():
    r = MagicMock()
    r.delete = AsyncMock(return_value=1)
    return r


@pytest.fixture
def limiter(mock_redis):
    return RedisRateLimiter(mock_redis)


class TestRedisRateLimiter:

    @pytest.mark.asyncio
    async def test_allow_within_limit(self, limiter, mock_redis):
        pipe = _make_pipe_mock([None, None, 2, None])
        mock_redis.pipeline.return_value = pipe

        allowed = await limiter.check_and_consume("test_key", limit=10, window_seconds=60)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_deny_over_limit(self, limiter, mock_redis):
        pipe = _make_pipe_mock([None, None, 11, None])
        mock_redis.pipeline.return_value = pipe

        allowed = await limiter.check_and_consume("test_key", limit=10, window_seconds=60)
        assert allowed is False

    @pytest.mark.asyncio
    async def test_get_remaining(self, limiter, mock_redis):
        pipe = _make_pipe_mock([None, 3])
        mock_redis.pipeline.return_value = pipe

        remaining = await limiter.get_remaining("test_key", limit=10, window_seconds=60)
        assert remaining == 7

    @pytest.mark.asyncio
    async def test_reset(self, limiter, mock_redis):
        await limiter.reset("test_key")
        mock_redis.delete.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_allow_when_no_redis(self):
        limiter = RedisRateLimiter(None)
        allowed = await limiter.check_and_consume("test", limit=1, window_seconds=60)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_fail_open_on_exception(self, limiter, mock_redis):
        mock_redis.pipeline.side_effect = RuntimeError("Redis down")
        allowed = await limiter.check_and_consume("test_key", limit=10, window_seconds=60)
        assert allowed is True  # Fail open

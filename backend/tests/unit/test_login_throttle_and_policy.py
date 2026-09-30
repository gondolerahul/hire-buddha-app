"""Server-side password policy and per-account sign-in throttling (AU-07).

``UserCreate.password`` was a bare ``str`` — a one-character password was
accepted — and nothing limited guesses at one account beyond the API-wide
200 requests a minute per client IP.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.auth import service, throttle


class FakeRedis:
    """The five commands the throttle uses, over a shared dict."""

    store: dict = {}
    ttls: dict = {}

    async def get(self, key):
        return self.store.get(key)

    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key, seconds):
        self.ttls[key] = seconds

    async def ttl(self, key):
        return self.ttls.get(key, -1)

    async def delete(self, key):
        self.store.pop(key, None)

    async def aclose(self):
        pass


class DownRedis(FakeRedis):
    async def get(self, key):
        raise ConnectionError("redis down")

    incr = get


@pytest.fixture
def fake_redis(monkeypatch):
    FakeRedis.store, FakeRedis.ttls = {}, {}
    monkeypatch.setattr(throttle, "client_factory", FakeRedis)
    return FakeRedis


@pytest.mark.parametrize("password,ok", [
    ("short", False),
    ("elevenchars", False),
    ("twelve-chars", True),
    ("x" * 128, True),
    ("x" * 129, False),
])
def test_password_length(password, ok):
    if ok:
        service.check_password_policy(password)
    else:
        with pytest.raises(HTTPException) as exc:
            service.check_password_policy(password)
        assert exc.value.status_code == 422 and isinstance(exc.value.detail, str)


def test_password_is_not_the_email():
    with pytest.raises(HTTPException):
        service.check_password_policy("Someone@Example.com", "someone@example.com")


@pytest.mark.asyncio
async def test_ten_failures_lock_the_account_for_the_window(fake_redis):
    lock = throttle.LOGIN_FAILURES
    for _ in range(9):
        await lock.hit("Rep@Example.com")
    assert await lock.retry_after("rep@example.com") == 0
    await lock.hit("rep@example.com")  # the tenth, any case
    assert await lock.retry_after("REP@example.com") == 15 * 60
    await lock.clear("rep@example.com")
    assert await lock.retry_after("rep@example.com") == 0


@pytest.mark.asyncio
async def test_the_key_does_not_hold_the_email(fake_redis):
    await throttle.LOGIN_FAILURES.hit("rep@example.com")
    assert not any("rep@example.com" in key for key in fake_redis.store)


@pytest.mark.asyncio
async def test_redis_down_does_not_lock_anyone_out(monkeypatch):
    monkeypatch.setattr(throttle, "client_factory", DownRedis)
    await throttle.LOGIN_FAILURES.hit("rep@example.com")
    assert await throttle.LOGIN_FAILURES.retry_after("rep@example.com") == 0

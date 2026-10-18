"""Phase 14 (tech spec §5.3): with DB_AUTH=entra_token every new database
connection signs in with a current token from the workload's identity — the
URL carries no password.

Against the local Postgres: the "token" a fake identity hands out is that
server's password, so the connection succeeds only if the hook supplied it.
(The Azure identity's own token cache is tested in test_platform_adapters.)
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from src.common.config import settings
from src.common.platform import AdapterNotAvailable, dbauth, identity

pytestmark = pytest.mark.needs_db


class _Tokens:
    name = "fake"

    def __init__(self, password):
        self.password, self.calls = password, []

    async def token(self, scope):
        return self.sync_token(scope)

    def sync_token(self, scope):
        self.calls.append(scope)
        return self.password


@pytest.fixture
def url_without_password():
    url = make_url(settings.DATABASE_URL)
    if not url.password:
        pytest.skip("the local DATABASE_URL has no password to stand in for a token")
    return url, url.set(password=None)


async def test_each_connection_signs_in_with_a_token(url_without_password):
    url, bare = url_without_password
    tokens = _Tokens(url.password)
    identity.set_token_source(tokens)
    engine = create_async_engine(bare, poolclass=NullPool)
    try:
        assert dbauth.install(engine, "entra_token") == "entra_token"
        for _ in range(2):
            async with engine.connect() as conn:
                assert (await conn.execute(text("select 1"))).scalar() == 1
    finally:
        await engine.dispose()
        identity.set_token_source(None)
    assert tokens.calls == [dbauth.POSTGRES_ENTRA_SCOPE] * 2


async def test_without_a_workload_identity_the_connection_says_why(url_without_password, monkeypatch):
    _url, bare = url_without_password
    monkeypatch.setattr(settings, "WORKLOAD_IDENTITY_BACKEND", "none")
    identity.set_token_source(None)
    engine = create_async_engine(bare, poolclass=NullPool)
    dbauth.install(engine, "entra_token")
    try:
        with pytest.raises(AdapterNotAvailable, match="workload identity"):
            async with engine.connect():
                pass
    finally:
        await engine.dispose()
        identity.set_token_source(None)


def test_an_unknown_method_is_refused():
    engine = create_async_engine("postgresql+asyncpg://u@localhost/db")
    with pytest.raises(AdapterNotAvailable, match="DB_AUTH"):
        dbauth.install(engine, "kerberos")
    assert dbauth.install(engine, "password") == "password"

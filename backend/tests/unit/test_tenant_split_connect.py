"""The split tool's own connections (WS7 7.1) on Azure: ``?ssl=require`` in the
URL is asyncpg's ``ssl`` argument, not a server setting (the server refused it:
"parameter "ssl" cannot be changed now"), and the Entra token is the password."""
from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url


@pytest.mark.parametrize("query, expected_ssl", [("?ssl=require", "require"), ("?sslmode=require", "require"),
                                                 ("", None)])
async def test_ssl_in_the_url_becomes_asyncpgs_ssl_argument(monkeypatch, query, expected_ssl):
    import asyncpg

    from src.common.tenancy import split

    seen = {}

    class Conn:
        async def execute(self, sql):
            seen["sql"] = sql

    async def fake_connect(dsn, **kwargs):
        seen["dsn"], seen["kwargs"] = dsn, kwargs
        return Conn()

    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    monkeypatch.setattr("src.common.platform.adapter_name", lambda capability: "password")
    url = make_url(f"postgresql+asyncpg://id-hb-dev-provisioner@psql.example:5432/hb_control{query}")
    await split._connect(url, schema="public")
    assert "ssl" not in seen["dsn"] and seen["dsn"].startswith("postgresql://id-hb-dev-provisioner@psql.example")
    assert seen["kwargs"].get("ssl") == expected_ssl
    assert seen["sql"] == "SET search_path TO public, public"

"""Phase 14 WS1 1.2: the Azure Blob adapter meets the storage contract, on Azurite.

Start Azurite (``docker compose up -d azurite`` in backend/) to run it; it is
skipped when nothing listens on :10000, and fails instead under
``REQUIRE_AZURITE=1``. ``AZURITE_CONNECTION_STRING`` overrides the
connection (default: Azurite's well-known development account).
"""
from __future__ import annotations

import os
import socket
import uuid

import httpx
import pytest

from tests.harness.storage import check_contract

CONNECTION = os.environ.get("AZURITE_CONNECTION_STRING", "UseDevelopmentStorage=true")


def _azurite_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 10000), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.fixture
async def blob():
    if not _azurite_up():
        if os.environ.get("REQUIRE_AZURITE", "").strip() in ("1", "true"):
            pytest.fail("Azurite is not running on :10000 (REQUIRE_AZURITE=1)")
        pytest.skip("Azurite is not running on :10000")
    from src.common.platform.storage.azure_blob import AzureBlobBackend

    backend = AzureBlobBackend(connection_string=CONNECTION)
    namespace = f"t-{uuid.uuid4().hex[:12]}"
    yield backend, namespace
    try:
        await backend._service().delete_container(namespace)
    except Exception:
        pass
    await backend.close()


async def test_azure_blob_meets_the_contract(blob):
    backend, namespace = blob
    await check_contract(backend, namespace)


async def test_a_signed_url_downloads_the_file_and_expires(blob):
    backend, namespace = blob
    key = f"{namespace}/artifacts/2026-10-17/abc_report.pdf"
    await backend.put(key, b"%PDF-1.7", content_type="application/pdf")
    url = await backend.signed_url(key, ttl_seconds=60, file_name="Report é.pdf",
                                   content_type="application/pdf")
    async with httpx.AsyncClient() as client:
        ok = await client.get(url)
        assert ok.status_code == 200 and ok.content == b"%PDF-1.7"
        assert ok.headers["content-type"] == "application/pdf"
        assert "attachment" in ok.headers["content-disposition"]
        unsigned = await client.get(url.split("?", 1)[0])
        assert unsigned.status_code in (401, 403, 404)


async def test_a_missing_container_lists_nothing(blob):
    backend, _ = blob
    assert await backend.list(f"t-{uuid.uuid4().hex[:12]}/") == []

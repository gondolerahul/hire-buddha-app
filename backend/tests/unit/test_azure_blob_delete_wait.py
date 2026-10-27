"""Deleting a business's container on Azure waits until a listing no longer sees its blobs.

Azure deletes a container in the background. On prod, its properties already answered "not found"
while a listing still returned a blob, so the offboarding's verify step failed: the wait is on the list.
"""
from __future__ import annotations

import pytest

pytest.importorskip("azure.storage.blob")


class _Blob:
    name = "files/report.txt"


class _Container:
    def __init__(self):
        self.lists = 0
        self.deleted = False

    async def list_blobs(self, include=None):
        from azure.core.exceptions import ResourceNotFoundError

        self.lists += 1
        if self.lists > 3:                     # gone at last
            raise ResourceNotFoundError("ContainerNotFound")
        yield _Blob()                          # the count before deleting, then two stale listings

    async def delete_container(self):
        self.deleted = True

    async def get_container_properties(self):
        from azure.core.exceptions import ResourceNotFoundError
        raise ResourceNotFoundError("ContainerNotFound")


class _Service:
    def __init__(self, container):
        self.container = container

    def get_container_client(self, name):
        return self.container


@pytest.mark.asyncio
async def test_the_delete_waits_until_a_listing_is_empty(monkeypatch):
    from src.common.platform.storage import azure_blob

    async def no_wait(seconds):
        return None

    monkeypatch.setattr(azure_blob.asyncio, "sleep", no_wait)
    container = _Container()
    backend = azure_blob.AzureBlobBackend(connection_string="UseDevelopmentStorage=true")
    monkeypatch.setattr(backend, "_service", lambda: _Service(container))
    assert await backend.delete_namespace("t-abc123") == 1
    assert container.deleted and container.lists == 4

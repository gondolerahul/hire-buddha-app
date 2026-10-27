"""``azure_blob`` storage: a key's namespace is a container, the rest its blob name.

Authentication is the pod's workload identity (``DefaultAzureCredential``);
the storage account allows no shared keys (Azure setup guide §8), so download
links are **user-delegation SAS** URLs. ``AZURE_STORAGE_CONNECTION_STRING``
(Azurite, tests) signs with the account key instead.

A container is created the first time something is written to it; in
production the Provisioner creates each tenant's ``t-<key>`` container (WS2).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from src.common.platform import missing_sdk
from src.common.platform.storage import (
    STREAM_CHUNK_BYTES,
    StorageObjectNotFound,
    split_key,
    validate_key,
)

try:
    from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError
    from azure.storage.blob import BlobSasPermissions, ContentSettings, generate_blob_sas
    from azure.storage.blob.aio import BlobServiceClient
except ImportError:  # pragma: no cover - exercised only where the SDK is absent
    BlobServiceClient = None  # type: ignore[assignment,misc]

# A user-delegation key is fetched for this long and replaced when a link
# would outlive it.
_DELEGATION_KEY_HOURS = 6


class AzureBlobBackend:
    name = "azure_blob"

    def __init__(self, *, account_url: str = "", connection_string: str = ""):
        if BlobServiceClient is None:
            raise missing_sdk("azure_blob", "azure-storage-blob", "STORAGE_BACKEND")
        if not (account_url or connection_string):
            raise ValueError("azure_blob storage needs AZURE_STORAGE_ACCOUNT_URL "
                             "(or AZURE_STORAGE_CONNECTION_STRING for Azurite)")
        self._account_url = account_url
        self._connection_string = connection_string
        # aio clients are bound to the loop they first ran on (as in common/redis_client.py).
        self._clients: Dict[int, Any] = {}
        self._credentials: Dict[int, Any] = {}
        self._delegation: Dict[int, Tuple[Any, datetime]] = {}

    # ── clients ──────────────────────────────────────────────────────────
    def _service(self) -> Any:
        loop_id = id(asyncio.get_running_loop())
        client = self._clients.get(loop_id)
        if client is None:
            if self._connection_string:
                client = BlobServiceClient.from_connection_string(self._connection_string)
            else:
                from azure.identity.aio import DefaultAzureCredential

                credential = self._credentials[loop_id] = DefaultAzureCredential()
                client = BlobServiceClient(self._account_url, credential=credential)
            self._clients[loop_id] = client
        return client

    def _blob(self, key: str) -> Any:
        container, blob = split_key(key)
        return self._service().get_blob_client(container, blob)

    async def close(self) -> None:
        """Close the HTTP sessions (a script that ends; tests)."""
        clients, self._clients = self._clients, {}
        credentials, self._credentials = self._credentials, {}
        for client in clients.values():
            await client.close()
        for credential in credentials.values():
            await credential.close()

    # ── StorageBackend ───────────────────────────────────────────────────
    def local_path(self, key: str) -> Optional[Path]:
        return None

    async def put(self, key: str, data: bytes, *, content_type: Optional[str] = None) -> None:
        await self._upload(key, lambda: data, content_type)

    async def put_file(self, key: str, path: Path, *, content_type: Optional[str] = None) -> None:
        handles = []

        def reopen() -> Any:  # a retry after creating the container reads from the start
            for handle in handles:
                handle.close()
            handles.append(open(path, "rb"))
            return handles[-1]

        try:
            await self._upload(key, reopen, content_type, max_concurrency=4)
        finally:
            for handle in handles:
                handle.close()

    async def _upload(self, key: str, body: Any, content_type: Optional[str], **options: Any) -> None:
        blob = self._blob(key)
        settings = ContentSettings(content_type=content_type) if content_type else None
        try:
            await blob.upload_blob(body(), overwrite=True, content_settings=settings, **options)
        except ResourceNotFoundError as error:
            if getattr(error, "error_code", None) != "ContainerNotFound":
                raise
            try:
                await self._service().create_container(split_key(key)[0])
            except ResourceExistsError:
                pass
            await blob.upload_blob(body(), overwrite=True, content_settings=settings, **options)

    async def get(self, key: str) -> bytes:
        try:
            downloader = await self._blob(key).download_blob()
            return await downloader.readall()
        except ResourceNotFoundError:
            raise StorageObjectNotFound(key) from None

    async def open_stream(self, key: str, chunk_size: int = STREAM_CHUNK_BYTES) -> AsyncIterator[bytes]:
        try:
            downloader = await self._blob(key).download_blob(max_concurrency=1)
        except ResourceNotFoundError:
            raise StorageObjectNotFound(key) from None
        async for chunk in downloader.chunks():
            yield chunk

    async def delete(self, key: str) -> None:
        try:
            await self._blob(key).delete_blob(delete_snapshots="include")
        except ResourceNotFoundError:
            pass

    async def delete_namespace(self, namespace: str) -> int:
        validate_key(f"{namespace}/x")
        container = self._service().get_container_client(namespace)
        count = 0
        try:
            async for _ in container.list_blobs(include=["versions"]):
                count += 1
            await container.delete_container()
        except ResourceNotFoundError:
            return 0
        # Azure deletes a container in the background: until it is gone a list may still see blobs.
        for _ in range(60):
            try:
                await container.get_container_properties()
            except ResourceNotFoundError:
                break
            except HttpResponseError as error:
                if getattr(error, "error_code", None) != "ContainerBeingDeleted":
                    raise
            await asyncio.sleep(2)
        return count

    async def exists(self, key: str) -> bool:
        try:
            return await self._blob(key).exists()
        except ResourceNotFoundError:
            return False

    async def size(self, key: str) -> Optional[int]:
        try:
            return (await self._blob(key).get_blob_properties()).size
        except ResourceNotFoundError:
            return None

    async def list(self, prefix: str) -> List[str]:
        container, _, path_prefix = prefix.partition("/")
        validate_key(f"{container}/x")
        names: List[str] = []
        try:
            async for item in self._service().get_container_client(container).list_blobs(
                    name_starts_with=path_prefix or None):
                names.append(f"{container}/{item.name}")
        except ResourceNotFoundError:
            return []
        return sorted(names)

    async def signed_url(
        self, key: str, *, ttl_seconds: int, file_name: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        container, blob_name = split_key(key)
        now = datetime.now(tz=timezone.utc)
        # A little slack before now: the browser's and Azure's clocks differ.
        start, expiry = now - timedelta(minutes=5), now + timedelta(seconds=ttl_seconds)
        disposition = _attachment(file_name) if file_name else None
        signing: Dict[str, Any] = {}
        credential = self._service().credential
        account_key = getattr(credential, "account_key", None)
        if account_key:
            signing["account_key"] = account_key
        else:
            signing["user_delegation_key"] = await self._delegation_key(expiry)
        token = generate_blob_sas(
            account_name=self._service().account_name, container_name=container, blob_name=blob_name,
            permission=BlobSasPermissions(read=True), start=start, expiry=expiry,
            content_disposition=disposition, content_type=content_type, **signing,
        )
        return f"{self._blob(key).url}?{token}"

    async def _delegation_key(self, needed_until: datetime) -> Any:
        loop_id = id(asyncio.get_running_loop())
        cached = self._delegation.get(loop_id)
        if cached and cached[1] > needed_until + timedelta(minutes=5):
            return cached[0]
        now = datetime.now(tz=timezone.utc)
        valid_until = max(now + timedelta(hours=_DELEGATION_KEY_HOURS), needed_until + timedelta(minutes=10))
        key = await self._service().get_user_delegation_key(now - timedelta(minutes=5), valid_until)
        self._delegation[loop_id] = (key, valid_until)
        return key


def _attachment(file_name: str) -> str:
    """``Content-Disposition`` for a download, safe for any file name (RFC 6266)."""
    from urllib.parse import quote

    ascii_name = file_name.encode("ascii", "ignore").decode().replace('"', "").replace("\\", "") or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file_name)}"

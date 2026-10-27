"""Object storage behind one interface (Phase 14 WS1 1.2, tech spec §12.1).

Files are stored and recorded by a **neutral key** — ``<namespace>/<path>``,
e.g. ``c-<company>/artifacts/system-generated/2026-10-17/<uuid>_report.pdf`` —
never by a disk path or a Blob URL (P-05). The first segment is the
namespace: a Blob container on Azure, a top-level directory on local disk.
Signed download URLs are made at request time by the adapter.

Adapters (``STORAGE_BACKEND``, default from ``PLATFORM_PROFILE``):

* ``local_disk`` — a directory tree (``STORAGE_LOCAL_ROOT``); development and tests.
* ``azure_blob`` — Azure Blob Storage with the pod's workload identity.
"""
from __future__ import annotations

import os
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, List, Optional, Protocol, runtime_checkable

from src.common.platform import AdapterNotAvailable, adapter_name

# A namespace is a valid Blob container name on every target: 3–63 lowercase
# letters, digits and single hyphens, starting and ending alphanumeric.
_NAMESPACE = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){2,62}$")
_MAX_KEY_LENGTH = 1024
STREAM_CHUNK_BYTES = 1024 * 1024


class InvalidStorageKey(ValueError):
    """A key that is not ``<namespace>/<relative path>`` with safe segments."""


class StorageObjectNotFound(FileNotFoundError):
    """No object is stored under the key."""


def validate_key(key: str) -> str:
    """The key itself, or :class:`InvalidStorageKey`.

    Forward slashes only; no empty, ``.`` or ``..`` segment; no absolute path
    or drive; a namespace that is a valid container name; at least one segment
    after it.
    """
    if not isinstance(key, str) or not key or len(key) > _MAX_KEY_LENGTH:
        raise InvalidStorageKey(f"invalid storage key: {key!r}")
    if "\\" in key or "\x00" in key or key.startswith("/") or ":" in key.split("/", 1)[0]:
        raise InvalidStorageKey(f"invalid storage key: {key!r}")
    parts = key.split("/")
    if len(parts) < 2 or any(part in ("", ".", "..") for part in parts):
        raise InvalidStorageKey(f"invalid storage key: {key!r}")
    if not _NAMESPACE.match(parts[0]):
        raise InvalidStorageKey(f"invalid storage namespace {parts[0]!r} in key {key!r}")
    return key


def split_key(key: str) -> tuple[str, str]:
    """``(namespace, path)`` of a valid key."""
    namespace, _, path = validate_key(key).partition("/")
    return namespace, path


def legacy_namespace(company_id: object) -> str:
    """``c-<company uuid hex>``: where a company's files went before it had a tenant."""
    import uuid

    return f"c-{uuid.UUID(str(company_id)).hex}"


def company_namespaces(company_id: object) -> list[str]:
    """Every namespace that holds the company's files, the one new files go to first:
    ``t-<tenant key>`` once this process knows the company's tenant (WS2's
    directory, loaded by any split-mode request for it), then ``c-<company hex>``,
    where its earlier files stay until the file mover (WS7 7.4) moves them."""
    from src.common.tenancy.directory import directory

    names = [legacy_namespace(company_id)]
    location = directory.cached(company_id)
    if location is not None and location.key:
        names.insert(0, f"t-{location.key}")
    return names


def company_namespace(company_id: object) -> str:
    """The namespace a company's new files go to (see ``company_namespaces``)."""
    return company_namespaces(company_id)[0]


@runtime_checkable
class StorageBackend(Protocol):
    """What every storage adapter implements. Keys are validated by each call."""

    name: str

    async def put(self, key: str, data: bytes, *, content_type: Optional[str] = None) -> None:
        """Store ``data`` under ``key``, replacing what was there."""

    async def put_file(self, key: str, path: Path, *, content_type: Optional[str] = None) -> None:
        """Store the file at ``path`` under ``key`` without reading it into memory
        (database exports, large media)."""

    async def get(self, key: str) -> bytes:
        """The object's bytes, or :class:`StorageObjectNotFound`."""

    def open_stream(self, key: str, chunk_size: int = STREAM_CHUNK_BYTES) -> AsyncIterator[bytes]:
        """The object's bytes in chunks, or :class:`StorageObjectNotFound` on first read."""

    async def delete(self, key: str) -> None:
        """Remove the object; a missing one is not an error."""

    async def exists(self, key: str) -> bool:
        ...

    async def size(self, key: str) -> Optional[int]:
        """Bytes stored, or ``None`` when there is no object."""

    async def list(self, prefix: str) -> List[str]:
        """Keys under ``prefix`` (``<namespace>/`` or deeper), sorted."""

    async def delete_namespace(self, namespace: str) -> int:
        """Remove a whole namespace — every object and every version (a Blob container) —
        when its business is erased (docs/phase15/13 §6 step 7); the objects counted first."""

    async def signed_url(
        self, key: str, *, ttl_seconds: int, file_name: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        """A time-limited URL the browser can fetch directly, or ``None`` when the
        adapter has none (local disk) and the API streams the file itself."""

    def local_path(self, key: str) -> Optional[Path]:
        """The object's path on this machine when the adapter is a filesystem, else ``None``."""


_backend: Optional[StorageBackend] = None


def get_storage() -> StorageBackend:
    """The process's storage adapter, chosen by settings on first use."""
    global _backend
    if _backend is None:
        _backend = build_storage(adapter_name("storage"))
    return _backend


def set_storage(backend: Optional[StorageBackend]) -> None:
    """Replace the process's adapter (tests); ``None`` re-selects from settings."""
    global _backend
    _backend = backend


def build_storage(name: str) -> StorageBackend:
    from src.common.config import settings

    if name == "local_disk":
        from src.common.platform.storage.local_disk import LocalDiskBackend

        return LocalDiskBackend(settings.STORAGE_LOCAL_ROOT or default_local_root())
    if name == "azure_blob":
        from src.common.platform.storage.azure_blob import AzureBlobBackend

        return AzureBlobBackend(
            account_url=settings.AZURE_STORAGE_ACCOUNT_URL,
            connection_string=settings.AZURE_STORAGE_CONNECTION_STRING,
        )
    raise AdapterNotAvailable(f"STORAGE_BACKEND={name!r} has no adapter (local_disk, azure_blob)")


def default_local_root() -> Path:
    """``backend/artifact``: where every platform file lived before storage keys,
    so a key from then (``system-generated/<company>/…``) still finds its file.
    Ignored by git and the image."""
    backend_dir = Path(__file__).resolve().parents[4]  # …/backend/src/common/platform/storage -> …/backend
    return backend_dir / "artifact"


@asynccontextmanager
async def materialized(key: str, *, suffix: str = "") -> AsyncIterator[Path]:
    """A local file holding the object, for code that needs a path (ffmpeg,
    text extraction, an e-mail attachment).

    On local disk it is the stored file itself — read it, never change it;
    otherwise a temporary copy, removed on exit.
    """
    storage = get_storage()
    path = storage.local_path(key)
    if path is not None:
        if not path.is_file():
            raise StorageObjectNotFound(key)
        yield path
        return
    data = await storage.get(key)
    handle, name = tempfile.mkstemp(suffix=suffix or Path(key).suffix)
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        yield Path(name)
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass

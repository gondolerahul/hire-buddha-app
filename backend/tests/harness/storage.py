"""tests.harness.storage — the storage contract every adapter meets, and a
remote-like in-memory adapter for code paths that must not assume a local disk.
"""
from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from src.common.platform.storage import StorageObjectNotFound, validate_key


class MemoryStorage:
    """Behaves like Blob storage: no local paths, and signed URLs."""

    name = "memory"

    def __init__(self) -> None:
        self.objects: Dict[str, bytes] = {}
        self.content_types: Dict[str, Optional[str]] = {}

    def local_path(self, key: str) -> Optional[Path]:
        validate_key(key)
        return None

    async def put(self, key: str, data: bytes, *, content_type: Optional[str] = None) -> None:
        self.objects[validate_key(key)] = bytes(data)
        self.content_types[key] = content_type

    async def put_file(self, key: str, path: Path, *, content_type: Optional[str] = None) -> None:
        await self.put(key, Path(path).read_bytes(), content_type=content_type)

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[validate_key(key)]
        except KeyError:
            raise StorageObjectNotFound(key) from None

    async def open_stream(self, key: str, chunk_size: int = 4) -> AsyncIterator[bytes]:
        data = await self.get(key)
        for start in range(0, len(data), chunk_size):
            yield data[start:start + chunk_size]

    async def delete(self, key: str) -> None:
        self.objects.pop(validate_key(key), None)

    async def delete_namespace(self, namespace: str) -> int:
        validate_key(f"{namespace}/x")
        gone = [k for k in self.objects if k.startswith(f"{namespace}/")]
        for key in gone:
            del self.objects[key]
        return len(gone)

    async def exists(self, key: str) -> bool:
        return validate_key(key) in self.objects

    async def size(self, key: str) -> Optional[int]:
        data = self.objects.get(validate_key(key))
        return None if data is None else len(data)

    async def list(self, prefix: str) -> List[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    async def signed_url(self, key: str, *, ttl_seconds: int, file_name: Optional[str] = None,
                         content_type: Optional[str] = None) -> Optional[str]:
        validate_key(key)
        return f"https://storage.example/{key}?sig=test&ttl={ttl_seconds}"


async def check_contract(storage, namespace: str) -> None:
    """What every adapter must do; ``namespace`` is unused by anything else."""
    key = f"{namespace}/artifacts/2026-10-17/abc_report.pdf"
    other = f"{namespace}/uploads/2026-10-17/def_photo.png"

    assert await storage.exists(key) is False
    assert await storage.size(key) is None
    try:
        await storage.get(key)
        raise AssertionError("get of a missing key must raise")
    except StorageObjectNotFound:
        pass
    await storage.delete(key)  # a missing object is not an error

    await storage.put(key, b"%PDF-1.7 first", content_type="application/pdf")
    await storage.put(key, b"%PDF-1.7 second", content_type="application/pdf")  # replaces
    await storage.put(other, b"\x89PNG", content_type="image/png")

    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "export.dump"
        source.write_bytes(b"PGDMP" * 1000)
        big = f"{namespace}/backups/2026-W42/hb.dump"
        await storage.put_file(big, source, content_type="application/octet-stream")
        await storage.put_file(big, source)  # replaces
        assert await storage.get(big) == b"PGDMP" * 1000
        await storage.delete(big)

    assert await storage.get(key) == b"%PDF-1.7 second"
    assert await storage.exists(key) is True
    assert await storage.size(key) == len(b"%PDF-1.7 second")
    assert b"".join([chunk async for chunk in storage.open_stream(key, chunk_size=4)]) == b"%PDF-1.7 second"
    assert await storage.list(f"{namespace}/") == sorted([key, other])
    assert await storage.list(f"{namespace}/uploads/") == [other]

    await storage.delete(key)
    assert await storage.exists(key) is False
    assert await storage.list(f"{namespace}/") == [other]
    await storage.delete(other)
    assert await storage.list(f"{namespace}/") == []

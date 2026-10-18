"""``local_disk`` storage: one directory tree, a key's namespace as its top folder."""
from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path
from typing import AsyncIterator, List, Optional

from src.common.platform.storage import (
    STREAM_CHUNK_BYTES,
    StorageObjectNotFound,
    split_key,
    validate_key,
)


class LocalDiskBackend:
    name = "local_disk"

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        namespace, path = split_key(key)
        resolved = (self.root / namespace / path).resolve()
        # validate_key already refuses '..'; this also catches a symlinked escape.
        if self.root not in resolved.parents:
            raise StorageObjectNotFound(key)
        return resolved

    def local_path(self, key: str) -> Optional[Path]:
        return self._path(key)

    async def put(self, key: str, data: bytes, *, content_type: Optional[str] = None) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write beside, then rename: a reader never sees half a file.
            partial = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
            partial.write_bytes(data)
            os.replace(partial, path)

        await asyncio.to_thread(write)

    async def put_file(self, key: str, path: Path, *, content_type: Optional[str] = None) -> None:
        target = self._path(key)

        def copy() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
            shutil.copyfile(path, partial)
            os.replace(partial, target)

        await asyncio.to_thread(copy)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            raise StorageObjectNotFound(key) from None

    async def open_stream(self, key: str, chunk_size: int = STREAM_CHUNK_BYTES) -> AsyncIterator[bytes]:
        path = self._path(key)
        try:
            file = await asyncio.to_thread(open, path, "rb")
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            raise StorageObjectNotFound(key) from None
        try:
            while chunk := await asyncio.to_thread(file.read, chunk_size):
                yield chunk
        finally:
            file.close()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def size(self, key: str) -> Optional[int]:
        path = self._path(key)
        try:
            return (await asyncio.to_thread(path.stat)).st_size if path.is_file() else None
        except FileNotFoundError:
            return None

    async def list(self, prefix: str) -> List[str]:
        # A prefix is a key or a key's leading part; '<namespace>/' lists it all.
        namespace = prefix.partition("/")[0]
        validate_key(f"{namespace}/x")
        base = self.root / namespace

        def walk() -> List[str]:
            if not base.is_dir():
                return []
            keys = []
            for path in base.rglob("*"):
                if path.is_file() and not path.name.endswith(".part"):
                    key = f"{namespace}/{path.relative_to(base).as_posix()}"
                    if key.startswith(prefix):
                        keys.append(key)
            return sorted(keys)

        return await asyncio.to_thread(walk)

    async def signed_url(
        self, key: str, *, ttl_seconds: int, file_name: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        return None

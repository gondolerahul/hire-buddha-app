"""``local`` key-encryption keys: one random key file per tenant, AES key wrap (RFC 3394)."""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap, aes_key_wrap

from src.common.platform.kek import KeyDestroyed, validate_key_name


def default_key_dir() -> Path:
    """``backend/.local-keys`` (ignored by git and the image)."""
    return Path(__file__).resolve().parents[4] / ".local-keys"


class LocalKeyEncryption:
    name = "local"

    def __init__(self, directory: Optional[str | Path] = None):
        self.directory = Path(directory) if directory else default_key_dir()

    def _path(self, key_name: str) -> Path:
        return self.directory / f"{validate_key_name(key_name)}.key"

    async def ensure_key(self, key_name: str) -> str:
        path = self._path(key_name)
        if not path.exists():
            self.directory.mkdir(parents=True, exist_ok=True)
            # Created exclusively: two processes making the same key keep one.
            try:
                with open(path, "xb") as handle:
                    handle.write(secrets.token_bytes(32))
                os.chmod(path, 0o600)
            except FileExistsError:
                pass
        return f"local:{key_name}"

    def _material(self, key_id: str) -> bytes:
        if not key_id.startswith("local:"):
            raise KeyDestroyed(f"{key_id!r} is not a local key")
        path = self._path(key_id.split(":", 1)[1])
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise KeyDestroyed(f"key {key_id} no longer exists") from None

    async def wrap(self, key_name: str, plaintext_key: bytes) -> Tuple[bytes, str]:
        key_id = await self.ensure_key(key_name)
        return aes_key_wrap(self._material(key_id), plaintext_key), key_id

    async def unwrap(self, key_id: str, wrapped: bytes) -> bytes:
        try:
            return aes_key_unwrap(self._material(key_id), wrapped)
        except InvalidUnwrap:
            raise KeyDestroyed(f"key {key_id} does not open this key (it was replaced)") from None

    async def destroy(self, key_name: str) -> None:
        self._path(key_name).unlink(missing_ok=True)

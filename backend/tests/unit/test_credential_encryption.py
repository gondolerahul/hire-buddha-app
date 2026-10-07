"""AU-24: stored credentials are encrypted under a real, derived key.

``ENCRYPTION_MASTER_KEY`` defaulted to a string in this repository, and the AES
key was that string truncated or NUL-padded to 32 bytes. A deployment that
forgot the variable encrypted every credential with a public key.
"""
from __future__ import annotations

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import ValidationError

from src.common.config import Settings
from src.common.security import decrypt_api_key, encrypt_api_key

KEY = "k" * 16 + "0123456789abcdef"          # 32 characters
OTHER = "z" * 40


def _legacy_encrypt(plain: str, master: str) -> str:
    """How a credential was encrypted before AU-24."""
    key = master.encode()
    key = key[:32] if len(key) > 32 else key.ljust(32, b"\0")
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plain.encode(), None)).decode()


def test_a_new_ciphertext_is_versioned_and_round_trips() -> None:
    sealed = encrypt_api_key("sk-live-123", master=KEY)
    assert sealed.startswith("v2:")
    assert decrypt_api_key(sealed, master=KEY) == "sk-live-123"


def test_the_key_is_derived_not_padded() -> None:
    sealed = encrypt_api_key("sk-live-123", master=KEY)
    body = base64.b64decode(sealed[3:])
    with pytest.raises(InvalidTag):        # the raw (padded) key does not open it
        AESGCM(KEY.encode()).decrypt(body[:12], body[12:], None)


def test_a_credential_stored_before_au24_still_decrypts() -> None:
    assert decrypt_api_key(_legacy_encrypt("smtp-pass", KEY), master=KEY) == "smtp-pass"


def test_another_key_does_not_decrypt() -> None:
    with pytest.raises(InvalidTag):
        decrypt_api_key(encrypt_api_key("x", master=KEY), master=OTHER)


def _settings(key: str | None) -> Settings:
    fields = dict(DATABASE_URL="postgresql+asyncpg://u:p@h/db", REDIS_URL="redis://h:6379/0",
                  SECRET_KEY="s" * 40)
    if key is not None:
        fields["ENCRYPTION_MASTER_KEY"] = key
    return Settings(_env_file=None, **fields)


@pytest.mark.parametrize("key", [None, "your-default-dev-key-must-be-32-bytes", "change-me-in-production",
                                 "short-key"])
def test_a_missing_placeholder_or_short_key_refuses_to_load(key, monkeypatch) -> None:
    monkeypatch.delenv("ENCRYPTION_MASTER_KEY", raising=False)
    with pytest.raises(ValidationError):
        _settings(key)


def test_a_real_key_loads(monkeypatch) -> None:
    monkeypatch.delenv("ENCRYPTION_MASTER_KEY", raising=False)
    assert _settings(OTHER).ENCRYPTION_MASTER_KEY == OTHER

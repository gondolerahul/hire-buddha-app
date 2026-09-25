"""The single Tata credential resolver: storage, reads, and what the console sees."""
from types import SimpleNamespace
from uuid import uuid4

from src.common.security import decrypt_api_key, encrypt_api_key
from src.voice.tata_credentials import (
    ENCRYPTED_KEY, SECRETS_SET_KEY, credentials_from_entry, normalize_tata_metadata, redact_secrets,
)


def _entry(meta, api_key="ctc-key"):
    return SimpleNamespace(id=uuid4(), company_id=uuid4(), service_metadata=meta,
                           encrypted_api_key=encrypt_api_key(api_key) if api_key else None)


def test_secrets_typed_into_metadata_are_encrypted_and_removed():
    meta, api_key = normalize_tata_metadata(
        {"api_key": "ctc", "auth_token": "jwt", "login_password": "pw", "business_id": "TACN1", "api_url": "u"}
    )
    assert api_key == "ctc"                                   # goes to encrypted_api_key
    assert "auth_token" not in meta and "login_password" not in meta and "api_key" not in meta
    assert decrypt_api_key(meta[ENCRYPTED_KEY]["auth_token"]) == "jwt"
    assert decrypt_api_key(meta[ENCRYPTED_KEY]["login_password"]) == "pw"
    assert meta["business_id"] == "TACN1"                     # settings stay readable


def test_console_round_trip_keeps_stored_secrets():
    stored, _ = normalize_tata_metadata({"auth_token": "jwt", "business_id": "B"})
    shown = redact_secrets(stored)
    # The console gets names, not values, and sends back what it got.
    assert ENCRYPTED_KEY not in shown and shown[SECRETS_SET_KEY] == ["auth_token"]
    again, api_key = normalize_tata_metadata({**shown, "business_id": "B2"}, stored)
    assert api_key is None
    assert again[ENCRYPTED_KEY] == stored[ENCRYPTED_KEY]
    assert again["business_id"] == "B2" and SECRETS_SET_KEY not in again


def test_a_new_token_replaces_only_itself():
    stored, _ = normalize_tata_metadata({"auth_token": "old", "login_password": "pw"})
    updated, _ = normalize_tata_metadata({"auth_token": "new"}, stored)
    assert decrypt_api_key(updated[ENCRYPTED_KEY]["auth_token"]) == "new"
    assert decrypt_api_key(updated[ENCRYPTED_KEY]["login_password"]) == "pw"


def test_credentials_come_only_from_encrypted_fields():
    meta, _ = normalize_tata_metadata({"auth_token": "jwt", "login_email": "a@b", "api_url": "https://x/"})
    meta["api_key"] = "plain-leftover"                          # an unmigrated plain-text copy
    creds = credentials_from_entry(_entry(meta, api_key="ctc-key"))
    assert creds.api_key == "ctc-key"                           # the column, not the plain copy
    assert creds.auth_token == "jwt" and creds.login_email == "a@b"
    assert creds.api_url == "https://x"


def test_metadata_without_secrets_is_returned_unchanged():
    assert redact_secrets({"project_id": "p"}) == {"project_id": "p"}
    assert redact_secrets(None) is None

"""AU-25: a social connection's client secrets are stored encrypted.

``oauth_metadata`` kept the platform app's ``client_secret`` (and Google Ads'
``developer_token``) as plain JSON, beside access tokens that were encrypted.
"""
from __future__ import annotations

import json

from src.ai.social_connection_service import (OAUTH_SECRETS_KEY, is_oauth_secret, open_oauth_metadata,
                                              seal_oauth_metadata)

META = {"client_id": "app-123", "client_secret": "s3cr3t", "developer_token": "dev-tok",
        "customer_id": "111-222", "user_agent": "HireBuddha:v1.0"}


def test_sealing_leaves_no_secret_in_the_clear() -> None:
    sealed = seal_oauth_metadata(META)
    stored = json.dumps(sealed)
    assert "s3cr3t" not in stored and "dev-tok" not in stored
    assert sealed["client_id"] == "app-123" and sealed["customer_id"] == "111-222"
    assert set(sealed[OAUTH_SECRETS_KEY]) == {"client_secret", "developer_token"}
    assert all(v.startswith("v2:") for v in sealed[OAUTH_SECRETS_KEY].values())


def test_opening_gives_back_what_was_sealed() -> None:
    assert open_oauth_metadata(seal_oauth_metadata(META)) == META


def test_sealing_twice_changes_nothing_readable() -> None:
    twice = seal_oauth_metadata(seal_oauth_metadata(META))
    assert open_oauth_metadata(twice) == META


def test_metadata_written_before_au25_still_opens() -> None:
    assert open_oauth_metadata({"client_id": "a", "client_secret": "plain"}) == {
        "client_id": "a", "client_secret": "plain"}
    assert seal_oauth_metadata(None) is None
    assert open_oauth_metadata(None) == {}


def test_which_keys_are_secrets() -> None:
    assert all(is_oauth_secret(k) for k in ("client_secret", "developer_token", "app_password", "api_key"))
    assert not any(is_oauth_secret(k) for k in ("client_id", "customer_id", "user_agent", "ad_account_id"))

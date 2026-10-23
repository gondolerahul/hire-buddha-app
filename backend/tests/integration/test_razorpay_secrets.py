"""Phase 15 T0-2: Razorpay's secrets are in the vault, not in the database in plain text (B-8).

The ``razorpay_keys`` row kept ``key_secret`` and ``webhook_secret`` in
``service_metadata`` as plain JSON. Now the key secret is the row's own secret
(``secret_ref`` or the encrypted API key) and the webhook secret is named by
``webhook_secret_ref``; the registry API refuses the old fields, and
``move_secrets`` moves an old row's. Real Postgres (rolled back); the vault is
the environment adapter.
"""
from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException

import src.main  # noqa: F401  (every model mapped)
from src.billing.razorpay_gateway import RAZORPAY_SKU, get_razorpay_creds
from src.common.platform.secrets import set_secrets
from src.common.platform.secrets.env import EnvSecrets, env_name
from src.common.security import encrypt_api_key
from src.config.models import IntegrationRegistry

pytestmark = pytest.mark.needs_db


@pytest.fixture
def vault(monkeypatch):
    """The env adapter as the vault; ``vault.set`` writes a secret into it."""
    class Vault:
        async def set(self, name, value):
            monkeypatch.setenv(env_name(name), value)

    set_secrets(EnvSecrets())
    try:
        yield Vault()
    finally:
        set_secrets(None)


async def _row(db, **fields) -> IntegrationRegistry:
    from src.auth.platform import platform_company_id

    row = IntegrationRegistry(company_id=await platform_company_id(db), provider_name="razorpay",
                              service_sku=RAZORPAY_SKU, service_category="OTHER", component_type="payment_gateway",
                              internal_cost=0, cost_unit="per 1", status="active", **fields)
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_secrets_come_from_the_vault(db, vault):
    await vault.set("rzp-key-secret", "s3cret")
    await vault.set("rzp-webhook", "hook")
    await _row(db, secret_ref="rzp-key-secret",
               service_metadata={"key_id": "rzp_test_1", "webhook_secret_ref": "rzp-webhook"})
    assert await get_razorpay_creds(db) == {"key_id": "rzp_test_1", "key_secret": "s3cret", "webhook_secret": "hook"}


@pytest.mark.asyncio
async def test_the_console_api_key_field_is_the_key_secret(db, vault):
    await _row(db, encrypted_api_key=encrypt_api_key("from-the-console"), service_metadata={"key_id": "rzp_test_2"})
    creds = await get_razorpay_creds(db)
    assert creds["key_secret"] == "from-the-console" and creds["webhook_secret"] is None


@pytest.mark.asyncio
async def test_no_key_secret_means_no_gateway(db, vault):
    await _row(db, service_metadata={"key_id": "rzp_test_3"})
    assert await get_razorpay_creds(db) is None


@pytest.mark.asyncio
async def test_an_old_plain_text_row_still_works_and_says_so(db, vault, caplog):
    await _row(db, service_metadata={"key_id": "rzp_old", "key_secret": "plain", "webhook_secret": "plain-hook"})
    with caplog.at_level(logging.ERROR, logger="src.billing.razorpay_gateway"):
        creds = await get_razorpay_creds(db)
    assert (creds["key_secret"], creds["webhook_secret"]) == ("plain", "plain-hook")
    assert sum("move_secrets" in r.getMessage() for r in caplog.records) == 2


@pytest.mark.asyncio
async def test_the_registry_api_refuses_plain_text_secrets(db):
    from src.auth.platform import platform_company_id
    from src.config.schemas import IntegrationRegistryCreate, IntegrationRegistryUpdate
    from src.config.service import ConfigService

    service = ConfigService(db)
    entry = IntegrationRegistryCreate(
        company_id=await platform_company_id(db), provider_name="razorpay", service_sku=RAZORPAY_SKU,
        service_category="OTHER", component_type="payment_gateway", internal_cost=0, cost_unit="per_call",
        service_metadata={"key_id": "rzp_x", "key_secret": "plain"}, api_key="unused")
    with pytest.raises(HTTPException) as refused:
        await service.create_registry_entry(entry)
    assert refused.value.status_code == 422 and "key_secret" in refused.value.detail

    row = await _row(db, encrypted_api_key=encrypt_api_key("k"), service_metadata={"key_id": "rzp_x"})
    with pytest.raises(HTTPException) as refused:
        await service.update_registry_entry(row.id, IntegrationRegistryUpdate(
            service_metadata={"key_id": "rzp_x", "webhook_secret": "plain"}))
    assert refused.value.status_code == 422 and "webhook_secret" in refused.value.detail


@pytest.mark.asyncio
async def test_move_secrets_moves_an_old_row_into_the_vault(db, vault):
    from src.config.move_secrets import move_secrets

    row = await _row(db, service_metadata={"key_id": "rzp_old", "key_secret": "plain", "webhook_secret": "plain-hook"})
    dry = await move_secrets(db, vault, apply=False)
    assert {"service_sku": "razorpay_keys.key_secret", "secret_ref": "registry-razorpay-keys"} in dry["would_move"]
    assert (await get_razorpay_creds(db))["key_secret"] == "plain"                     # nothing changed yet

    done = await move_secrets(db, vault, apply=True)
    assert not done["failed"] and len([m for m in done["moved"] if m["service_sku"].startswith("razorpay")]) == 2
    await db.refresh(row)
    assert row.service_metadata == {"key_id": "rzp_old", "webhook_secret_ref": "registry-razorpay-keys-webhook"}
    assert (row.secret_ref, row.encrypted_api_key) == ("registry-razorpay-keys", None)
    assert await get_razorpay_creds(db) == {"key_id": "rzp_old", "key_secret": "plain", "webhook_secret": "plain-hook"}

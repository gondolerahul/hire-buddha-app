"""AU-24 on Postgres: rotating the credential key re-encrypts every stored secret.

Rows are written under an old key — some in the pre-AU-24 format, some in v2 —
then ``reencrypt_all`` moves them to a new key. Scoped to the test's company, in
a rolled-back transaction.
"""
from __future__ import annotations

import base64
import os
import uuid

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.common.encrypted_fields import RotationError, reencrypt_all
from src.common.orm_models import import_all_models
from src.common.security import decrypt_api_key, encrypt_api_key

pytestmark = pytest.mark.needs_db

import_all_models()   # every mapper, for the foreign keys between them

OLD = "old-key-" + "o" * 32
NEW = "new-key-" + "n" * 32


def _legacy(plain: str, master: str) -> str:
    key = master.encode()[:32]
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plain.encode(), None)).decode()


async def _world(db):
    from src.auth.models import Company
    from src.config.models import IntegrationRegistry
    from src.gateway.models import WebhookEndpoint

    company = Company(name=f"au24-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(company)
    await db.flush()
    integration = IntegrationRegistry(
        company_id=company.id, provider_name="tata_tele", service_sku="tata-voice",
        component_type="telephony", internal_cost=0, cost_unit_code="PER_MINUTE",
        status="active", encrypted_api_key=_legacy("tata-api-key", OLD),
        service_metadata={"login_email": "ops@example.com",
                          "secrets_encrypted": {"auth_token": encrypt_api_key("tata-auth", master=OLD)}},
    )
    endpoint = WebhookEndpoint(company_id=company.id, source="generic", name="hook",
                               secret_encrypted=encrypt_api_key("hook-secret", master=OLD))
    db.add_all([integration, endpoint])
    await db.flush()
    return company, integration, endpoint


@pytest.mark.asyncio
async def test_every_secret_moves_to_the_new_key(db):
    company, integration, endpoint = await _world(db)
    counts = await reencrypt_all(db, OLD, NEW, company_id=company.id)
    await db.refresh(integration)
    await db.refresh(endpoint)
    assert integration.encrypted_api_key.startswith("v2:")
    assert decrypt_api_key(integration.encrypted_api_key, master=NEW) == "tata-api-key"
    assert decrypt_api_key(integration.service_metadata["secrets_encrypted"]["auth_token"], master=NEW) == "tata-auth"
    assert integration.service_metadata["login_email"] == "ops@example.com"
    assert decrypt_api_key(endpoint.secret_encrypted, master=NEW) == "hook-secret"
    assert counts["integration_registry.encrypted_api_key"] == 1
    assert counts["webhook_endpoints.secret_encrypted"] == 1
    assert counts["integration_registry.service_metadata.secrets_encrypted"] == 1

    again = await reencrypt_all(db, OLD, NEW, company_id=company.id)     # an interrupted run, re-run
    assert sum(again.values()) == 0


@pytest.mark.asyncio
async def test_the_same_key_upgrades_old_ciphertexts_to_v2(db):
    company, integration, _ = await _world(db)
    await reencrypt_all(db, OLD, OLD, company_id=company.id)
    await db.refresh(integration)
    assert integration.encrypted_api_key.startswith("v2:")
    assert decrypt_api_key(integration.encrypted_api_key, master=OLD) == "tata-api-key"


@pytest.mark.asyncio
async def test_a_value_under_neither_key_aborts(db):
    company, _, _ = await _world(db)
    with pytest.raises(RotationError):
        await reencrypt_all(db, "wrong-key-" + "w" * 30, NEW, company_id=company.id)

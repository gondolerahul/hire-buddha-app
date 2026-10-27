"""Destroying a tenant's key on Azure (offboarding, docs/phase15/13 §6 step 11).

The adapter uses the *async* Key Vault client, whose delete is ``delete_key`` (it waits itself);
``begin_delete_key`` — the sync client's — does not exist there. The first real erasure on Azure
dev failed on exactly that, so this pins the call to the SDK's async API.
"""
from __future__ import annotations

import pytest

pytest.importorskip("azure.keyvault.keys")


@pytest.mark.asyncio
async def test_the_key_is_deleted_with_the_async_clients_own_call(monkeypatch):
    from azure.core.exceptions import ResourceNotFoundError
    from azure.keyvault.keys.aio import KeyClient

    from src.common.platform.kek.azure_keyvault import KeyVaultKeyEncryption

    assert hasattr(KeyClient, "delete_key") and not hasattr(KeyClient, "begin_delete_key")
    deleted = []

    class FakeClient:
        async def delete_key(self, name):
            if name in deleted:
                raise ResourceNotFoundError("gone")
            deleted.append(name)

    kek = KeyVaultKeyEncryption("https://vault.example")
    monkeypatch.setattr(kek, "_client", lambda: FakeClient())
    await kek.destroy("t-abc123")
    await kek.destroy("t-abc123")              # already gone: not an error
    assert deleted == ["t-abc123"]

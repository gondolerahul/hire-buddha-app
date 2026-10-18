"""Phase 14 P-03: a profile picks every capability's adapter; a setting overrides one."""
import pytest

from src.common import platform
from src.common.config import settings
from src.common.platform import AdapterNotAvailable, adapter_name
from src.common.platform import secrets as secrets_mod
from src.common.platform import storage as storage_mod


@pytest.fixture(autouse=True)
def _fresh_adapters():
    storage_mod.set_storage(None)
    secrets_mod.set_secrets(None)
    yield
    storage_mod.set_storage(None)
    secrets_mod.set_secrets(None)


@pytest.mark.parametrize("profile, storage, secrets", [
    ("local", "local_disk", "env"),
    ("azure", "azure_blob", "azure_keyvault"),
    ("onprem", "s3", "vault"),
])
def test_profile_defaults(monkeypatch, profile, storage, secrets):
    monkeypatch.setattr(settings, "PLATFORM_PROFILE", profile)
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "")
    monkeypatch.setattr(settings, "SECRETS_BACKEND", "")
    assert adapter_name("storage") == storage
    assert adapter_name("secrets") == secrets


def test_override_beats_profile(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "azure")
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "Local_Disk")
    assert adapter_name("storage") == "local_disk"


def test_unknown_profile_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "gcp")
    with pytest.raises(AdapterNotAvailable, match="PLATFORM_PROFILE"):
        platform.platform_profile()


def test_unbuilt_adapter_names_its_setting(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "onprem")
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "")
    with pytest.raises(AdapterNotAvailable, match="STORAGE_BACKEND"):
        storage_mod.get_storage()


def test_local_profile_storage_is_local_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "local")
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "")
    monkeypatch.setattr(settings, "STORAGE_LOCAL_ROOT", str(tmp_path))
    backend = storage_mod.get_storage()
    assert backend.name == "local_disk"
    assert backend.local_path("c-abc/x.txt") == (tmp_path / "c-abc" / "x.txt").resolve()


def test_azure_blob_needs_an_account(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "azure_blob")
    monkeypatch.setattr(settings, "AZURE_STORAGE_ACCOUNT_URL", "")
    monkeypatch.setattr(settings, "AZURE_STORAGE_CONNECTION_STRING", "")
    with pytest.raises(ValueError, match="AZURE_STORAGE_ACCOUNT_URL"):
        storage_mod.get_storage()


async def test_env_secrets_map_names_to_variables(monkeypatch):
    monkeypatch.setattr(settings, "SECRETS_BACKEND", "env")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_1")
    provider = secrets_mod.get_secrets()
    assert await provider.get("razorpay-key-id") == "rzp_test_1"
    assert await provider.get("absent-secret") is None
    with pytest.raises(secrets_mod.InvalidSecretName):
        await provider.get("../etc")


async def test_secrets_are_cached_briefly():
    calls = []

    class Counting:
        name = "counting"

        async def get(self, name):
            calls.append(name)
            return "v"

    secrets_mod.set_secrets(Counting())
    provider = secrets_mod.get_secrets()
    assert await provider.get("a") == "v" and await provider.get("a") == "v"
    assert calls == ["a"]
    provider.forget("a")
    await provider.get("a")
    assert calls == ["a", "a"]


def test_settings_read_mounted_secret_files(monkeypatch, tmp_path):
    """WS1 1.4: the Key Vault CSI mount fills settings the environment leaves unset."""
    from src.common import config

    (tmp_path / "AZURE_KEYVAULT_URL").write_text("https://kv-hb-dev-0000.vault.azure.net/")
    monkeypatch.setenv("SETTINGS_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("AZURE_KEYVAULT_URL", raising=False)
    assert config._load_settings().AZURE_KEYVAULT_URL == "https://kv-hb-dev-0000.vault.azure.net/"

    monkeypatch.setenv("AZURE_KEYVAULT_URL", "https://from-env/")
    assert config._load_settings().AZURE_KEYVAULT_URL == "https://from-env/"


def test_the_azure_identity_reuses_a_token_until_near_expiry(monkeypatch):
    """A database connect hook asks per connection; Entra is asked about once an hour."""
    import time
    from types import SimpleNamespace

    from src.common.platform.identity import azure_workload_identity as azure_identity

    issued = []

    class _Credential:
        def __init__(self, **kwargs):
            pass

        def get_token(self, scope):
            issued.append(scope)
            return SimpleNamespace(token=f"t{len(issued)}", expires_on=clock["now"] + 3600)

    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(azure_identity, "SyncDefaultAzureCredential", _Credential)
    monkeypatch.setattr(time, "time", lambda: clock["now"])
    source = azure_identity.AzureWorkloadIdentity()
    assert source.sync_token("scope") == "t1"
    clock["now"] += 3000  # 10 minutes left: still good
    assert source.sync_token("scope") == "t1"
    clock["now"] += 400   # under 5 minutes left: refreshed
    assert source.sync_token("scope") == "t2"
    assert issued == ["scope", "scope"]

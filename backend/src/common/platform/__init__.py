"""Cloud-neutral platform capabilities (Phase 14, tech spec §19).

Application code depends on the interfaces in this package's sub-packages —
``storage``, ``secrets`` and the others Phase 14 adds — never on a cloud SDK.
Each capability has one adapter per target, chosen by settings:
``PLATFORM_PROFILE`` (``local`` | ``azure`` | ``onprem``) sets the defaults
and a per-capability setting (``STORAGE_BACKEND``, ``SECRETS_BACKEND``, …)
overrides one (P-03).

Cloud SDKs (``azure.*``, ``google.cloud.*``) are imported only inside the
adapter modules under this package, and only when that adapter is selected
(P-02, checked by ``tests/unit/test_platform_import_contract.py``), so a
machine without them runs the ``local`` profile.
"""
from __future__ import annotations

from typing import Dict

PROFILES = ("local", "azure", "onprem")

# capability → profile → adapter name. An adapter named here but not built yet
# (the on-premise ones) fails when selected, with a message naming the setting.
DEFAULT_ADAPTERS: Dict[str, Dict[str, str]] = {
    "storage": {"local": "local_disk", "azure": "azure_blob", "onprem": "s3"},
    "secrets": {"local": "env", "azure": "azure_keyvault", "onprem": "vault"},
    "workload_identity": {"local": "none", "azure": "azure_workload_identity", "onprem": "vault_k8s_auth"},
    "db_auth": {"local": "password", "azure": "entra_token", "onprem": "vault_dynamic"},
}

# The setting that overrides each capability's profile default.
OVERRIDE_SETTINGS: Dict[str, str] = {
    "storage": "STORAGE_BACKEND",
    "secrets": "SECRETS_BACKEND",
    "workload_identity": "WORKLOAD_IDENTITY_BACKEND",
    "db_auth": "DB_AUTH",
}


class AdapterNotAvailable(RuntimeError):
    """The selected adapter is unknown, not built yet, or its SDK is not installed."""


def platform_profile() -> str:
    from src.common.config import settings

    profile = (settings.PLATFORM_PROFILE or "local").strip().lower()
    if profile not in PROFILES:
        raise AdapterNotAvailable(f"PLATFORM_PROFILE={profile!r} is not one of {', '.join(PROFILES)}")
    return profile


def adapter_name(capability: str) -> str:
    """The adapter a capability uses: its override setting, else the profile's default."""
    from src.common.config import settings

    override = str(getattr(settings, OVERRIDE_SETTINGS[capability], "") or "").strip().lower()
    return override or DEFAULT_ADAPTERS[capability][platform_profile()]


def missing_sdk(adapter: str, package: str, setting: str) -> AdapterNotAvailable:
    return AdapterNotAvailable(
        f"the {adapter} adapter needs the '{package}' package, which is not installed; "
        f"install it or choose another adapter with {setting}")

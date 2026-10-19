"""The provisioner's rules that need no database (Phase 14 WS2 2.8, 2.9).

The steps run against a real server in ``tests/integration/test_tenant_provisioning.py``.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.common.tenancy import provisioner
from src.common.tenancy.models import PROVISIONING_STEPS

TENANT = provisioner.Tenant(company_id=uuid.uuid4(), key="abc0123456", db_name="t_abc0123456",
                            server_host="localhost")


def test_the_steps_are_the_state_machine_after_requested():
    assert provisioner.STEPS == PROVISIONING_STEPS[1:]
    assert tuple(provisioner.STEP_FUNCTIONS) == provisioner.STEPS


@pytest.mark.parametrize("name, slug", [
    ("Provisioned & Co", "provisioned-co"), ("  ", "workspace"), ("Rahul's Workspace", "rahul-s-workspace"),
    ("x" * 80, "x" * 40),
])
def test_slugs_are_lower_case_words(name, slug):
    assert provisioner.slugify(name) == slug


@pytest.mark.parametrize("step", ["identity_ready", "keys_ready", "namespace_ready", "data_api_ready"])
async def test_a_step_not_built_for_azure_fails_instead_of_passing(monkeypatch, step):
    """Locally skipped with a reason; on Azure refused, so a tenant is never
    ``active`` without its identity, keys, namespace or Data API."""
    from src.common.config import settings

    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "local")
    skipped = await provisioner.STEP_FUNCTIONS[step](TENANT)
    assert skipped.outcome == "skipped" and skipped.detail["reason"]
    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "azure")
    with pytest.raises(provisioner.StepNotBuilt, match=step):
        await provisioner.STEP_FUNCTIONS[step](TENANT)


async def test_the_storage_step_marks_the_namespace_once(monkeypatch):
    from src.common.platform.storage import set_storage
    from tests.harness.storage import MemoryStorage

    storage = MemoryStorage()
    set_storage(storage)
    try:
        first = await provisioner.STEP_FUNCTIONS["storage_ready"](TENANT)
        second = await provisioner.STEP_FUNCTIONS["storage_ready"](TENANT)
    finally:
        set_storage(None)
    assert first.detail == {"namespace": "t-abc0123456", "created": True}
    assert second.detail["created"] is False and list(storage.objects) == ["t-abc0123456/workspace.json"]


async def test_sign_up_requests_a_workspace_only_in_split_mode(monkeypatch):
    from src.auth.service import request_workspace
    from src.common.config import settings

    requested, queued = [], []

    async def _request(company_id, server_name=None):
        requested.append(company_id)

    async def _enqueue(function, *args, **kwargs):
        queued.append((function, args, kwargs.get("_job_id")))

    monkeypatch.setattr(provisioner, "request_tenant", _request)
    monkeypatch.setattr("src.common.job_queue.enqueue_job", _enqueue)
    company = uuid.uuid4()
    monkeypatch.setattr(settings, "TENANCY_MODE", "single")
    await request_workspace(company)
    assert requested == [] and queued == []
    monkeypatch.setattr(settings, "TENANCY_MODE", "split")
    await request_workspace(company)
    assert requested == [company]
    assert queued == [("provision_tenant", (str(company),), f"provision-tenant:{company}")]


async def test_sign_up_never_fails_for_its_workspace(monkeypatch):
    from src.auth.service import request_workspace
    from src.common.config import settings

    async def _no_server(company_id, server_name=None):
        raise provisioner.NoServerAvailable("no room")

    monkeypatch.setattr(settings, "TENANCY_MODE", "split")
    monkeypatch.setattr(provisioner, "request_tenant", _no_server)
    await request_workspace(uuid.uuid4())  # logged, not raised


async def test_a_workspace_not_ready_is_a_503_that_says_so():
    import httpx
    from fastapi import FastAPI

    from src.common.tenancy.directory import TenantNotFound, TenantNotReady
    from src.common.tenancy.errors import install_tenancy_error_handlers

    app = FastAPI()
    install_tenancy_error_handlers(app)

    @app.get("/not-ready")
    async def _not_ready():
        raise TenantNotReady("tenant abc is db_created")

    @app.get("/none")
    async def _none():
        raise TenantNotFound("no row")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        not_ready, none = await client.get("/not-ready"), await client.get("/none")
    assert not_ready.status_code == 503 and not_ready.json()["code"] == "workspace_not_ready"
    assert not_ready.headers["Retry-After"] == "10"
    assert none.status_code == 503 and none.json()["code"] == "workspace_not_provisioned"

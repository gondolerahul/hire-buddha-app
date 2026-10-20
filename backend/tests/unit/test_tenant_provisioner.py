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


async def test_the_namespace_step_makes_a_locked_down_namespace_on_a_cluster(monkeypatch):
    """Skipped without a cluster; on Azure the tenant's namespace with restricted pods,
    default-deny networking, a quota and default limits (WS6)."""
    from src.common.config import settings
    from src.common.platform import kube as kube_mod

    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "local")
    monkeypatch.setattr(settings, "KUBE_API_URL", "")
    assert (await provisioner.STEP_FUNCTIONS["namespace_ready"](TENANT)).outcome == "skipped"

    applied = []

    class FakeKube:
        async def apply(self, body):
            applied.append(body)
            return body

    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "azure")
    monkeypatch.setattr(kube_mod, "_client", FakeKube())
    result = await provisioner.STEP_FUNCTIONS["namespace_ready"](TENANT)
    assert result.outcome == "succeeded" and result.detail["namespace"] == f"t-{TENANT.key}"
    kinds = {m["kind"]: m for m in applied}
    assert set(kinds) == {"Namespace", "NetworkPolicy", "ResourceQuota", "LimitRange"}
    labels = kinds["Namespace"]["metadata"]["labels"]
    assert labels["pod-security.kubernetes.io/enforce"] == "restricted"
    assert labels["hirebuddha.com/tenant"] == TENANT.key
    assert kinds["NetworkPolicy"]["spec"] == {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}
    assert all(m["metadata"].get("namespace", f"t-{TENANT.key}") == f"t-{TENANT.key}" for m in applied)


async def test_the_data_api_step_is_in_process_or_refused(monkeypatch):
    """Locally, and on Azure dev with DATA_API_MODE=in_process, the platform API
    serves /data; otherwise refused, so no tenant is active without its Data API."""
    from src.common.config import settings

    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "local")
    monkeypatch.setattr(settings, "DATA_API_MODE", "")
    assert (await provisioner.STEP_FUNCTIONS["data_api_ready"](TENANT)).outcome == "skipped"
    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "azure")
    with pytest.raises(provisioner.StepNotBuilt, match="data_api_ready"):
        await provisioner.STEP_FUNCTIONS["data_api_ready"](TENANT)
    monkeypatch.setattr(settings, "DATA_API_MODE", "in_process")
    assert (await provisioner.STEP_FUNCTIONS["data_api_ready"](TENANT)).outcome == "skipped"


async def test_the_identity_step_makes_the_tenants_identity_and_its_sign_in(monkeypatch):
    from src.common.config import settings
    from src.common.tenancy import azure_identity, db_roles

    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "local")
    assert (await provisioner.STEP_FUNCTIONS["identity_ready"](TENANT)).outcome == "skipped"

    granted = []

    async def fake_identity(key):
        return {"name": f"id-hb-dev-t-{key}", "principal_id": "oid-1", "client_id": "cid-1",
                "subject": f"system:serviceaccount:t-{key}:data-api"}

    async def fake_grant(conn, db_name, name, object_id):
        granted.append((db_name, name, object_id))
        return {"made": True}

    class FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeEngine:
        def connect(self):
            return FakeConn()

        async def dispose(self):
            pass

    monkeypatch.setattr(settings, "PLATFORM_PROFILE", "azure")
    monkeypatch.setattr(azure_identity, "ensure_tenant_identity", fake_identity)
    monkeypatch.setattr(db_roles, "grant_tenant_principal", fake_grant)
    monkeypatch.setattr(provisioner, "_engine", lambda url: FakeEngine())
    result = await provisioner.STEP_FUNCTIONS["identity_ready"](TENANT)
    assert result.outcome == "succeeded"
    assert result.detail["name"] == "id-hb-dev-t-abc0123456" and result.detail["database_role"] == "hb_dataapi"
    assert granted == [("t_abc0123456", "id-hb-dev-t-abc0123456", "oid-1")]


async def test_the_tenant_identity_is_two_idempotent_puts(monkeypatch):
    import json

    import httpx

    from src.common.config import settings
    from src.common.tenancy import azure_identity

    for key, value in {"AZURE_SUBSCRIPTION_ID": "sub", "TENANT_IDENTITY_RESOURCE_GROUP": "rg-hb-dev-tenants",
                       "AZURE_LOCATION": "centralindia", "AKS_OIDC_ISSUER": "https://issuer/",
                       "TENANT_IDENTITY_NAME_PREFIX": "id-hb-dev-t-"}.items():
        monkeypatch.setattr(settings, key, value)

    class Tokens:
        async def token(self, scope):
            assert scope == "https://management.azure.com/.default"
            return "arm-token"

    monkeypatch.setattr("src.common.platform.identity.get_token_source", lambda: Tokens())
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.url.params["api-version"],
                      request.headers["authorization"], json.loads(request.content)))
        if request.url.path.endswith("/federatedIdentityCredentials/data-api"):
            return httpx.Response(200, json={})
        return httpx.Response(201, json={"properties": {"principalId": "oid-9", "clientId": "cid-9"}})

    made = await azure_identity.ensure_tenant_identity("abc0123456", transport=httpx.MockTransport(handler))
    base = ("/subscriptions/sub/resourceGroups/rg-hb-dev-tenants/providers/Microsoft.ManagedIdentity/"
            "userAssignedIdentities/id-hb-dev-t-abc0123456")
    assert [(m, path) for m, path, *_ in calls] == [("PUT", base), ("PUT", base + "/federatedIdentityCredentials/data-api")]
    assert all(c[2] == "2023-01-31" and c[3] == "Bearer arm-token" for c in calls)
    assert calls[0][4]["location"] == "centralindia"
    assert calls[1][4]["properties"] == {"issuer": "https://issuer/",
                                         "subject": "system:serviceaccount:t-abc0123456:data-api",
                                         "audiences": ["api://AzureADTokenExchange"]}
    assert made == {"name": "id-hb-dev-t-abc0123456", "principal_id": "oid-9", "client_id": "cid-9",
                    "subject": "system:serviceaccount:t-abc0123456:data-api"}

    monkeypatch.setattr(settings, "AKS_OIDC_ISSUER", "")
    with pytest.raises(azure_identity.TenantIdentityError, match="AKS_OIDC_ISSUER"):
        await azure_identity.ensure_tenant_identity("abc0123456", transport=httpx.MockTransport(handler))


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


async def test_provisioning_goes_to_its_own_queue_when_one_is_set(monkeypatch):
    """M2: on Azure provisioning has its own worker (the provisioner identity);
    locally the default queue's worker runs it, and health expects what is set."""
    from src.common import job_queue
    from src.common.config import settings
    from src.common.worker_health import EXPECTED_QUEUES, expected_queues

    queued = []

    async def fake_enqueue(function, *args, **kwargs):
        queued.append((function, args, kwargs))
        return "job"

    monkeypatch.setattr(job_queue, "enqueue_job", fake_enqueue)
    monkeypatch.setattr(settings, "PROVISIONING_QUEUE", "")
    await provisioner.enqueue_provisioning(TENANT.company_id, job_id="j1")
    assert queued[-1] == ("provision_tenant", (str(TENANT.company_id),), {"_job_id": "j1"})
    assert expected_queues() == EXPECTED_QUEUES

    monkeypatch.setattr(settings, "PROVISIONING_QUEUE", "provisioning")
    await provisioner.enqueue_provisioning(TENANT.company_id)
    assert queued[-1][2] == {"_queue_name": "provisioning"}
    assert expected_queues() == EXPECTED_QUEUES + ("provisioning",)

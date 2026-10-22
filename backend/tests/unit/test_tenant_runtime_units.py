"""Tenant runtime and apps, the parts with no database (Phase 14 WS6).

The App Controller's rendering and the edge's Caddyfile; app templates; the
promotion check suite; build contexts, ACR Tasks and the scan summary; the
Gitea and GitHub providers against played APIs; the sandbox pod, its path
mapping and proxy credentials; the egress proxy's cluster mode; custom-domain
names; app-user passwords and row scopes; row policies in blueprints; the
Kubernetes app runtime and checks Job; metering's overlap arithmetic.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import tarfile
import uuid
from pathlib import Path

import httpx
import pytest

from src.apps import controller, templates as tpl

BACKEND = Path(__file__).resolve().parents[2]


def _cr(**spec):
    base = {"tenantKey": "acme01", "app": "crm", "image": "acr.io/t-acme01/crm@sha256:abc", "healthPath": "/healthz",
            "env": {"HB_APP": "crm"}, "appKeySecret": "crm-key", "resources": {"cpu": "250m", "memory": "256Mi"},
            "mode": "always_on", "routes": ["crm-acme.apps.example.com"], "egress": []}
    base.update(spec)
    return {"apiVersion": "hirebuddha.com/v1", "kind": "TenantApp",
            "metadata": {"name": "crm", "namespace": "t-acme01", "uid": "u-1", "generation": 3}, "spec": base}


# ── App Controller ──────────────────────────────────────────────────────────

def test_a_tenant_app_becomes_a_locked_down_deployment_and_its_neighbours():
    kinds = {c["kind"]: c for c in controller.children(_cr())}
    assert set(kinds) == {"ServiceAccount", "Deployment", "Service", "NetworkPolicy"}
    deploy = kinds["Deployment"]
    pod = deploy["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert pod["automountServiceAccountToken"] is False and pod["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["image"].endswith("@sha256:abc") and deploy["spec"]["replicas"] == 1
    key = next(e for e in container["env"] if e["name"] == "HB_APP_KEY")
    assert key["valueFrom"]["secretKeyRef"] == {"name": "crm-key", "key": "key"}
    assert all(c["metadata"]["ownerReferences"][0]["uid"] == "u-1" for c in kinds.values())
    policy = kinds["NetworkPolicy"]["spec"]
    assert policy["ingress"][0]["from"][0]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "tenant-edge"}
    assert len(policy["egress"]) == 2   # DNS and the tenant's Data API; no proxy without an allow-list
    assert not any("HTTPS_PROXY" == e["name"] for e in container["env"])


def test_a_tenant_app_runs_on_the_apps_pool_when_there_is_one(monkeypatch):
    """Slice 4 (D53): the apps node pool's label and taint; without APPS_NODE_POOL, anywhere."""
    pod = lambda: controller.deployment(_cr())["spec"]["template"]["spec"]  # noqa: E731
    monkeypatch.delenv("APPS_NODE_POOL", raising=False)
    assert "nodeSelector" not in pod() and "tolerations" not in pod()
    monkeypatch.setenv("APPS_NODE_POOL", "apps")
    assert pod()["nodeSelector"] == {"hb/pool": "apps"}
    assert pod()["tolerations"] == [{"key": "hb/pool", "operator": "Equal", "value": "apps", "effect": "NoSchedule"}]


def test_an_allow_list_opens_the_proxy_and_sleep_mode_adds_a_scaler():
    kinds = {c["kind"]: c for c in controller.children(_cr(egress=["api.stripe.com"], mode="sleep"))}
    assert kinds["HTTPScaledObject"]["spec"]["replicas"]["min"] == 0
    assert kinds["HTTPScaledObject"]["spec"]["hosts"] == ["crm-acme.apps.example.com"]
    assert len(kinds["NetworkPolicy"]["spec"]["egress"]) == 3
    stopped = {c["kind"]: c for c in controller.children(_cr(stopped=True))}
    assert stopped["Deployment"]["spec"]["replicas"] == 0 and "HTTPScaledObject" not in stopped
    many = {c["kind"] for c in controller.children(_cr(resources={"replicas": 3}))}
    assert "PodDisruptionBudget" in many


def test_the_edge_serves_every_running_apps_names_with_on_demand_tls():
    sleeping = _cr(mode="sleep")
    sleeping["metadata"] = {**sleeping["metadata"], "name": "shop", "namespace": "t-beta02"}
    sleeping["spec"]["routes"] = ["shop.beta.com"]
    stopped = _cr(stopped=True)
    stopped["metadata"] = {**stopped["metadata"], "name": "old"}
    stopped["spec"]["routes"] = ["old.example.com"]
    caddyfile = controller.edge_caddyfile([_cr(), sleeping, stopped], ask_url="http://api/internal/v1/edge/ask?token=t")
    assert "ask http://api/internal/v1/edge/ask?token=t" in caddyfile
    assert "https://crm-acme.apps.example.com {" in caddyfile
    assert "reverse_proxy crm.t-acme01.svc.cluster.local:8080" in caddyfile
    assert "keda-add-ons-http-interceptor-proxy" in caddyfile   # a sleeping app wakes through KEDA
    assert "old.example.com" not in caddyfile and "on_demand" in caddyfile
    # Unprivileged Caddy: its own ports, and the one redirect is the plain-HTTP block's.
    assert "http_port 8080" in caddyfile and "https_port 8443" in caddyfile
    assert "auto_https disable_redirects" in caddyfile and ":8080 {" in caddyfile and ":80 {" not in caddyfile


def test_egress_allow_lists_and_status():
    lists = controller.egress_allowlists([_cr(egress=["b.com", "a.com", "a.com"]), _cr()])
    assert lists == {"t-acme01/app-crm": ["a.com", "b.com"]}
    assert controller.status_of(None, _cr())["phase"] == "Pending"
    running = {"spec": {"replicas": 1}, "status": {"readyReplicas": 1}}
    assert controller.status_of(running, _cr())["phase"] == "Running"
    assert controller.status_of({"spec": {"replicas": 0}, "status": {}}, _cr(mode="sleep"))["phase"] == "Sleeping"


def test_the_controller_drops_its_token_after_the_kubelet_replaced_it_and_before_it_expires():
    from datetime import datetime, timezone

    from src.common.platform.kube import token_expiry

    def jwt(claims):
        body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        return f"e30.{body}.sig"

    hour = token_expiry(jwt({"iat": 1_000_000, "exp": 1_003_607}))   # AKS: an hour, replaced at ~48 minutes
    assert hour == datetime.fromtimestamp(1_003_307, tz=timezone.utc)   # 55 minutes in
    assert token_expiry(jwt({"iat": 0, "exp": 600})) == datetime.fromtimestamp(540, tz=timezone.utc)
    assert token_expiry("not-a-jwt") is None and token_expiry(jwt({"sub": "x"})) is None


# ── Templates ───────────────────────────────────────────────────────────────

def test_the_five_d48_templates():
    ids = {t["id"]: t for t in tpl.catalog()}
    assert set(ids) == {"static_site", "site_forms", "mobile_backend", "mobile_app", "crm_admin"}
    assert ids["mobile_app"]["deployable"] is False and ids["crm_admin"]["uses_blueprint"] is True


def test_a_template_renders_its_files_with_safe_names():
    files = tpl.render("static_site", app_name="site", display_name='Acme <script>"Shop"</script>',
                       tenant_key="acme01", data_api_url="http://localhost:8000/data")
    for path in ("Dockerfile", "nginx.conf", "40-hb-config.sh", "package.json", "src/App.tsx", "src/main.tsx",
                 "README.md", ".hirebuddha.json"):
        assert path in files, path
    assert json.loads(files["package.json"])["name"] == "site"
    app = files["src/App.tsx"].decode()
    assert "Acme scriptShop/script" in app and "<script>" not in app and "{{" not in app
    assert json.loads(files[".hirebuddha.json"])["port"] == 8080


def test_a_crm_names_its_objects_and_a_form_its_object():
    crm = tpl.render("crm_admin", app_name="crm", display_name="Sales", objects=["contact", "account"])
    assert json.loads(crm["src/app.json"]) == {"display_name": "Sales", "objects": ["contact", "account"]}
    assert "src/lib/hb-data.ts" in crm and "src/ObjectView.tsx" in crm
    form = tpl.render("site_forms", app_name="site", display_name="Acme", params={"form_object": "contact"})
    assert 'const OBJECT = "contact";' in form["src/ContactForm.tsx"].decode()
    with pytest.raises(tpl.TemplateError):
        tpl.render("site_forms", app_name="site", display_name="x", params={"form_object": "a;b<"})
    with pytest.raises(tpl.TemplateError):
        tpl.render("static_site", app_name="Bad Name", display_name="x")
    roles = tpl.default_roles("crm_admin", ["contact", "account"])
    staff = next(r for r in roles if r["name"] == "staff")
    assert staff["permissions"] == {"objects": {"contact": ["read", "create", "update"],
                                                "account": ["read", "create", "update"]}, "own_rows": True}


# ── Promotion checks ────────────────────────────────────────────────────────

def _tree(tmp_path, files):
    for path, content in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


def test_the_built_in_checks_find_secrets_and_broken_code(tmp_path):
    from src.code_lanes import check_suite

    root = _tree(tmp_path, {"ok.py": "def f():\n    return eval('1')\n",
                            "keys.py": "AWS = 'AKIAABCDEFGHIJKLMNOP'\npassword = 'changeme-placeholder-x'\n",
                            "broken.py": "def (:\n"})
    results = {r["name"]: r for r in check_suite.run_suite(root)}
    assert results["secrets"]["conclusion"] == "failure" and "AWS access key" in results["secrets"]["summary"]
    assert "password or key" not in results["secrets"]["summary"]      # a placeholder is not a secret
    assert results["code"]["conclusion"] == "failure" and "syntax error" in results["code"]["summary"]
    assert "calls eval" in results["code"]["summary"]
    assert results["dependencies"]["conclusion"] == "skipped"


def test_clean_code_passes(tmp_path):
    from src.code_lanes import check_suite
    from src.code_lanes.checks import overall, parse_marker

    root = _tree(tmp_path, {"tool.py": "def add(a, b):\n    return a + b\n"})
    results = check_suite.run_suite(root)
    assert overall(results) == "passed" and all(r["conclusion"] in ("success", "skipped") for r in results)
    assert parse_marker("noise\nHB-CHECKS " + json.dumps(results)) == results
    assert parse_marker("nothing") is None


# ── Builds ──────────────────────────────────────────────────────────────────

def _tar(files, mode="w:gz"):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _names(context):
    with tarfile.open(fileobj=io.BytesIO(context), mode="r:gz") as archive:
        return sorted(m.name for m in archive.getmembers())


def test_a_build_context_is_the_commit_without_its_top_folder():
    from src.apps.build import BuildError, build_context

    github = _tar({"acme-crm-abc123/Dockerfile": b"FROM x", "acme-crm-abc123/src/a.ts": b"1"})
    assert _names(build_context(github)) == ["Dockerfile", "src/a.ts"]
    local = _tar({"Dockerfile": b"FROM x", "apps/crm/Dockerfile": b"FROM y", "apps/crm/x.py": b"2"})
    assert _names(build_context(local, strip_top=False)) == ["Dockerfile", "apps/crm/Dockerfile", "apps/crm/x.py"]
    assert _names(build_context(local, subdir="apps/crm", strip_top=False)) == ["Dockerfile", "x.py"]
    with pytest.raises(BuildError, match="no Dockerfile"):
        build_context(_tar({"top/readme.md": b"x"}))


def test_trivy_reports_are_summarised():
    from src.apps.build import summarise_trivy

    report = {"Results": [{"Vulnerabilities": [{"Severity": "CRITICAL", "VulnerabilityID": "CVE-1", "PkgName": "a",
                                                "InstalledVersion": "1"},
                                               {"Severity": "HIGH", "VulnerabilityID": "CVE-2", "PkgName": "b",
                                                "InstalledVersion": "2"},
                                               {"Severity": "LOW"}]}]}
    summary = summarise_trivy(json.dumps(report))
    assert summary["critical"] == 1 and summary["high"] == 1 and summary["top"][0].startswith("CVE-1")


async def test_acr_tasks_uploads_runs_and_reads_the_sbom_and_scan(monkeypatch):
    from src.apps.build import AcrTasksBuilder
    from src.common.config import settings
    from src.common.platform import identity

    class Tokens:
        name = "test"

        async def token(self, scope):
            assert scope == "https://management.azure.com/.default"
            return "arm-token"

    identity.set_token_source(Tokens())
    for key, value in {"ACR_SUBSCRIPTION_ID": "sub", "ACR_RESOURCE_GROUP": "rg", "ACR_REGISTRY_NAME": "acrhbapps"}.items():
        monkeypatch.setattr(settings, key, value)
    sbom = base64.b64encode(b'{"spdxVersion": "SPDX-2.3"}').decode()
    log = f"step 1\nHB-SBOM-BEGIN\n{sbom}\nHB-SBOM-END\nHB-SCAN-BEGIN\n" + json.dumps({"Results": []}) + "\nHB-SCAN-END\n"
    calls, polls = [], {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("listBuildSourceUploadUrl"):
            return httpx.Response(200, json={"uploadUrl": "https://blob.example/ctx?sas", "relativePath": "src/ctx.tgz"})
        if request.url.host == "blob.example":
            assert request.headers["x-ms-blob-type"] == "BlockBlob"
            return httpx.Response(201)
        if path.endswith("scheduleRun"):
            body = json.loads(request.content)
            task = base64.b64decode(body["encodedTaskContent"]).decode()
            assert "push" in task and "syft" in task and "trivy" in task and body["sourceLocation"] == "src/ctx.tgz"
            return httpx.Response(200, json={"properties": {"runId": "cb1"}})
        if path.endswith("/runs/cb1"):
            polls["n"] += 1
            status = "Running" if polls["n"] == 1 else "Succeeded"
            return httpx.Response(200, json={"properties": {"status": status, "outputImages": [{"digest": "sha256:d1"}]}})
        if path.endswith("listLogSasUrl"):
            return httpx.Response(200, json={"logLink": "https://logs.example/cb1"})
        if request.url.host == "logs.example":
            return httpx.Response(200, text=log)
        return httpx.Response(404)

    try:
        builder = AcrTasksBuilder(transport=httpx.MockTransport(handler), poll_seconds=0)
        result = await builder.build(b"ctx", repository="t-acme01/crm", tag="abc123", labels={"a": "b"})
    finally:
        identity.set_token_source(None)
    assert result.image == "acrhbapps.azurecr.io/t-acme01/crm:abc123" and result.digest == "sha256:d1"
    assert result.external_id == "cb1" and json.loads(result.sbom)["spdxVersion"] == "SPDX-2.3"
    assert result.scan["critical"] == 0 and polls["n"] == 2


# ── Git providers against played APIs ───────────────────────────────────────

async def test_gitea_makes_the_tenant_org_commits_and_merges():
    from src.code_lanes.git import GiteaProvider

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path.removeprefix("/api/v1"), request.method
        seen.append((method, path))
        assert request.headers["authorization"] == "token admin"
        if method == "GET" and path == "/orgs/t-acme01":
            return httpx.Response(404)
        if method == "POST" and path == "/orgs":
            return httpx.Response(201, json={"username": "t-acme01"})
        if method == "POST" and path == "/orgs/t-acme01/repos":
            return httpx.Response(201, json={"id": 7, "full_name": "t-acme01/crm", "default_branch": "main",
                                             "html_url": "http://gitea/t-acme01/crm"})
        if method == "GET" and path.startswith("/repos/t-acme01/crm/commits/"):
            return httpx.Response(200, json={"sha": "base1"}) if path.endswith("/main") else httpx.Response(404)
        if method == "GET" and path.startswith("/repos/t-acme01/crm/contents/"):
            return httpx.Response(404)
        if method == "POST" and path == "/repos/t-acme01/crm/contents":
            body = json.loads(request.content)
            assert body["new_branch"] == "hb/1-x" and body["branch"] == "main"
            assert body["files"][0]["operation"] == "create"
            return httpx.Response(201, json={"commit": {"sha": "c2"}})
        if method == "POST" and path == "/repos/t-acme01/crm/pulls":
            return httpx.Response(201, json={"number": 4, "state": "open", "head": {"sha": "c2"}, "html_url": "u"})
        if method == "POST" and path == "/repos/t-acme01/crm/statuses/c2":
            assert json.loads(request.content)["context"] == "hirebuddha/secrets"
            return httpx.Response(201, json={})
        if method == "POST" and path == "/repos/t-acme01/crm/pulls/4/merge":
            assert json.loads(request.content)["Do"] == "squash"
            return httpx.Response(200)
        if method == "GET" and path == "/repos/t-acme01/crm/pulls/4":
            return httpx.Response(200, json={"number": 4, "merged": True, "state": "closed", "merge_commit_sha": "m3"})
        return httpx.Response(500, text=f"unexpected {method} {path}")

    gitea = GiteaProvider("http://gitea", "admin", transport=httpx.MockTransport(handler))
    repo = await gitea.create_repo("t-acme01", "crm")
    assert repo.full_name == "t-acme01/crm" and ("POST", "/orgs") in seen
    sha = await gitea.commit_files(repo.full_name, branch="hb/1-x", base="main", files={"a.py": b"x=1"}, message="m")
    review = await gitea.open_review(repo.full_name, branch="hb/1-x", base="main", title="t", body="b")
    await gitea.post_check(repo.full_name, sha, name="secrets", conclusion="success", summary="none")
    assert sha == "c2" and review.number == 4
    assert await gitea.merge(repo.full_name, 4, message="t") == "m3"


async def test_github_commits_through_the_git_data_api_and_merges_by_squash(monkeypatch):
    from src.code_lanes.github import GitHubProvider
    from src.connections.providers import base
    from src.connections.providers.base import AccessToken

    async def credential(company_id, connection_id, *, purpose):
        assert purpose == "code_lanes"
        return AccessToken(access_token="ghs_inst")

    monkeypatch.setattr("src.connections.service.system_credential", credential)
    created = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        assert request.headers["authorization"] == "Bearer ghs_inst"
        if method == "GET" and path == "/repos/acme/crm/commits/hb/1-x":
            return httpx.Response(404, json={"message": "Not Found"})
        if method == "GET" and path == "/repos/acme/crm/commits/main":
            return httpx.Response(200, json={"sha": "p1"})
        if method == "GET" and path == "/repos/acme/crm/git/commits/p1":
            return httpx.Response(200, json={"tree": {"sha": "t1"}})
        if method == "POST" and path == "/repos/acme/crm/git/blobs":
            return httpx.Response(201, json={"sha": "b1"})
        if method == "POST" and path == "/repos/acme/crm/git/trees":
            assert json.loads(request.content)["base_tree"] == "t1"
            return httpx.Response(201, json={"sha": "t2"})
        if method == "POST" and path == "/repos/acme/crm/git/commits":
            assert json.loads(request.content)["parents"] == ["p1"]
            return httpx.Response(201, json={"sha": "c2"})
        if method == "POST" and path == "/repos/acme/crm/git/refs":
            created.update(json.loads(request.content))
            return httpx.Response(201, json={})
        if method == "PUT" and path == "/repos/acme/crm/pulls/9/merge":
            assert json.loads(request.content)["merge_method"] == "squash"
            return httpx.Response(200, json={"merged": True, "sha": "m9"})
        return httpx.Response(500, text=f"unexpected {method} {path}")

    base.set_transport(httpx.MockTransport(handler))
    try:
        github = GitHubProvider(uuid.uuid4(), uuid.uuid4())
        sha = await github.commit_files("acme/crm", branch="hb/1-x", base="main", files={"a.py": b"x"}, message="m")
        merged = await github.merge("acme/crm", 9, message="t", merged_by="owner@acme.com")
    finally:
        base.set_transport(None)
    assert sha == "c2" and created == {"ref": "refs/heads/hb/1-x", "sha": "c2"} and merged == "m9"


# ── The sandbox on AKS ──────────────────────────────────────────────────────

def test_host_paths_become_pod_paths_and_back(tmp_path):
    from src.ai.tools.sandbox.k8s_runtime import PathMap

    workspace, skills = tmp_path / "ws" / "acme", tmp_path / "skills"
    paths = PathMap([str(workspace), str(skills)])
    script = workspace / "tmp1.py"
    assert paths.to_pod(f"python3 {script}") == "python3 /sandbox/0/tmp1.py"
    assert paths.to_pod(str(skills / "x" / "run.py")) == "/sandbox/1/x/run.py"
    assert paths.to_host("File \"/sandbox/0/tmp1.py\", line 1") == f"File \"{script}\", line 1"
    assert paths.host_of("/sandbox/0/out/a.csv") == str(workspace / "out" / "a.csv")
    assert paths.host_of("/etc/passwd") is None


def test_the_sandbox_pod_is_isolated_and_knows_its_proxy(monkeypatch):
    from src.ai.tools.sandbox import k8s_runtime
    from src.common.config import settings

    monkeypatch.setattr(settings, "EGRESS_PROXY_SECRET", "s3cret")
    pod = k8s_runtime.pod_manifest("t-acme01", "sbx-1", tenant_key="acme01", network="web", company_id="c")
    spec = pod["spec"]
    container = spec["containers"][0]
    assert spec["runtimeClassName"] == settings.SANDBOX_K8S_RUNTIME_CLASS
    assert spec["automountServiceAccountToken"] is False and spec["nodeSelector"] == {"hb/pool": "sandbox"}
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["command"] == ["python3", "/opt/hb/agent.py"]
    proxy = next(e["value"] for e in container["env"] if e["name"] == "HTTPS_PROXY")
    assert proxy.startswith("http://t-acme01%2Fsbx-web:") and k8s_runtime.proxy_secret("t-acme01/sbx-web") in proxy
    none = k8s_runtime.pod_manifest("t-acme01", "sbx-2", tenant_key="acme01", network="none", company_id="c")
    assert not any(e["name"] == "HTTPS_PROXY" for e in none["spec"]["containers"][0]["env"])
    assert k8s_runtime.pod_name("c", "web") != k8s_runtime.pod_name("c", "none")
    policy = k8s_runtime.network_policy("t-acme01")["spec"]
    assert policy["ingress"][0]["from"][0]["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": "hb-platform"}


def _web_proxy():
    spec = importlib.util.spec_from_file_location("web_proxy_test", BACKEND / "docker" / "egress-proxy" / "web_proxy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_cluster_egress_proxy_knows_callers_by_their_credentials(monkeypatch):
    from src.ai.tools.sandbox import k8s_runtime
    from src.common.config import settings

    monkeypatch.setattr(settings, "EGRESS_PROXY_SECRET", "s3cret")
    proxy = _web_proxy()
    monkeypatch.setattr(proxy, "PROXY_SECRET", "s3cret")
    password = k8s_runtime.proxy_secret("t-acme01/app-crm")
    header = "Proxy-Authorization: Basic " + base64.b64encode(f"t-acme01%2Fapp-crm:{password}".encode()).decode()
    assert proxy.principal_of(["Host: x", header]) == "t-acme01/app-crm"
    with pytest.raises(proxy.AuthRequired):
        proxy.principal_of(["Proxy-Authorization: Basic " + base64.b64encode(b"t-acme01%2Fapp-crm:wrong").decode()])
    with pytest.raises(proxy.AuthRequired):
        proxy.principal_of([])
    rules = {"defaults": {"sbx-allowlist": ["googleapis.com"]}, "principals": {"t-acme01/app-crm": ["stripe.com"]}}
    assert proxy.allowed_hosts("t-acme01/sbx-web", rules) is None
    assert proxy.allowed_hosts("t-acme01/sbx-allowlist", rules) == ["googleapis.com"]
    assert proxy.allowed_hosts("t-acme01/app-crm", rules) == ["stripe.com"]
    assert proxy.allowed_hosts("t-beta02/app-shop", rules) == []
    proxy.check_host("api.stripe.com", ["stripe.com"])
    with pytest.raises(proxy.Refused):
        proxy.check_host("evilstripe.com", ["stripe.com"])


# ── Domains, app users, row policies ────────────────────────────────────────

def test_custom_domain_names(monkeypatch):
    from src.apps.domains import normalize
    from src.common.config import settings

    monkeypatch.setattr(settings, "APPS_DOMAIN", "apps.hirebuddha.com")
    assert normalize(" CRM.Acme.com. ") == "crm.acme.com"
    for bad in ("localhost", "10.0.0.1", "crm.apps.hirebuddha.com", "nodot", "a..b.com", "x.internal", "-a.com"):
        with pytest.raises(ValueError):
            normalize(bad)


def test_app_user_passwords_are_argon2id():
    from src.data_api.app_users import AuthProblem, hash_password, verify_password

    stored = hash_password("correct horse")
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, "correct horse") and not verify_password(stored, "wrong")
    assert not verify_password(None, "anything")
    with pytest.raises(AuthProblem):
        hash_password("short")


def test_row_scopes_of_an_app_user():
    from src.data_api import tokens
    from src.data_api.app_users import DENY, row_scope

    blueprint = {"objects": {"deal": {"row_policy": {"owner_field": "owner_email", "match": "email"}},
                             "note": {}}}
    user = tokens.Caller(company_id=uuid.uuid4(), tenant_key="acme01", actor="app_user:1", kind="app_user",
                         own_rows=frozenset({"deal", "note"}), owner={"id": "1", "email": "a@x.com"})
    assert row_scope(user, blueprint, "deal") == ("owner_email", "a@x.com")
    assert row_scope(user, blueprint, "note") == DENY
    assert row_scope(user, blueprint, "contact") is None
    person = tokens.Caller(company_id=uuid.uuid4(), tenant_key="acme01", actor="user:1", kind="user")
    assert row_scope(person, blueprint, "deal") is None


def test_a_row_policy_names_a_text_or_email_field():
    from src.schema_engine import blueprint as bp
    from src.schema_engine import planner

    obj = bp.validate_object("deal", {"fields": {"title": {"type": "text"}, "owner_email": {"type": "email"},
                                                 "amount": {"type": "integer"}},
                                      "row_policy": {"owner_field": "owner_email"}}, known_objects=["deal"])
    assert obj["row_policy"] == {"owner_field": "owner_email", "match": "email"}
    with pytest.raises(bp.BlueprintError):
        bp.validate_object("deal", {"fields": {"amount": {"type": "integer"}},
                                    "row_policy": {"owner_field": "amount"}}, known_objects=["deal"])
    assert "set_row_policy" in planner.OPERATIONS and "set_row_policy" not in planner.ADDITIVE


# ── The Kubernetes app runtime and checks Job ───────────────────────────────

class FakeKube:
    def __init__(self):
        self.applied, self.patched, self.deleted = [], [], []

    async def apply(self, body):
        self.applied.append(body)
        return body

    async def patch(self, path, body):
        self.patched.append((path, body))
        return body

    async def delete(self, path):
        self.deleted.append(path)
        return True


async def test_the_kubernetes_runtime_writes_the_key_secret_and_the_tenant_app():
    from src.apps.runtime import AppSpec, KubernetesAppRuntime

    kube = FakeKube()
    runtime = KubernetesAppRuntime(kube)
    spec = AppSpec(tenant_key="acme01", app="crm", instance="crm", image="acr/x@sha256:1", app_key="hbk_dev_acme01_k",
                   hostnames=["crm-acme.apps.example.com"], egress=["stripe.com"], mode="sleep")
    applied = await runtime.apply(spec)
    secret, app = kube.applied
    assert secret["kind"] == "Secret" and secret["stringData"] == {"key": "hbk_dev_acme01_k"}
    assert app["kind"] == "TenantApp" and app["metadata"]["namespace"] == "t-acme01"
    assert app["spec"]["appKeySecret"] == "crm-key" and app["spec"]["routes"] == ["crm-acme.apps.example.com"]
    assert applied["url"] == "https://crm-acme.apps.example.com"
    await runtime.stop("t-acme01", "crm")
    await runtime.restart("t-acme01", "crm")
    assert kube.patched[0] == ("/apis/hirebuddha.com/v1/namespaces/t-acme01/tenantapps/crm", {"spec": {"stopped": True}})
    assert "restartedAt" in kube.patched[1][1]["spec"]


def test_the_checks_job_runs_on_the_sandbox_pool():
    from src.code_lanes.checks import KubernetesChecksRunner

    job = KubernetesChecksRunner.job_manifest("t-acme01", "checks-1", "https://blob/x?sas")
    pod = job["spec"]["template"]["spec"]
    assert pod["nodeSelector"] == {"hb/pool": "sandbox"} and pod["automountServiceAccountToken"] is False
    assert pod["containers"][0]["args"] == ["/work", "--fetch", "https://blob/x?sas", "--tests", "--json"]
    assert job["spec"]["backoffLimit"] == 0


def test_metering_counts_the_part_of_the_hour_a_deployment_ran():
    from datetime import datetime

    from src.apps.metering import _overlap
    from src.apps.runtime import cores, gb

    start, end = datetime(2026, 10, 19, 10), datetime(2026, 10, 19, 11)
    assert _overlap(start, end, datetime(2026, 10, 19, 10, 30), None) == 0.5
    assert _overlap(start, end, datetime(2026, 10, 19, 9), datetime(2026, 10, 19, 10, 15)) == 0.25
    assert _overlap(start, end, datetime(2026, 10, 19, 12), None) == 0.0
    assert cores("250m") == 0.25 and cores("2") == 2.0 and gb("512Mi") == 0.5 and gb("2Gi") == 2.0


def test_hosting_cost_units_parse():
    from src.ai.usage_service import parse_cost_unit

    assert parse_cost_unit("per_vcpu_hour").noun == "hour"
    assert parse_cost_unit("per_gb").noun == "gb" and parse_cost_unit("per day").noun == "day"

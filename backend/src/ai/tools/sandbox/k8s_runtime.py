"""The sandbox on AKS (Phase 14 WS6 6.1, tech spec §11.1).

``KubernetesSandboxRuntime`` implements ``SandboxRuntime`` with one pod per
company and network policy — ``sbx-<hash>`` in the tenant's namespace
``t-<key>`` — instead of a Docker container. It is selected by
``SANDBOX_RUNTIME=kubernetes`` when the container switch is on.

* **The pod** — Kata micro-VM (``runtimeClassName``), the sandbox node pool,
  non-root, read-only root file system, ``/sandbox`` and ``/tmp`` as
  size-limited ``emptyDir``, limits from the deployment, no service-account
  token, ``hb-sandbox`` running its **agent** (port 7070, a bearer token per
  pod from its own Secret). A ``NetworkPolicy`` lets only the platform in,
  and out only DNS, the tenant's Data API and — for the ``allowlist`` and
  ``web`` policies — the egress proxy, which knows the pod by its proxy
  credentials (``t-<key>/sbx-<policy>``).
* **Files** — the tools keep writing to the platform's own workspace (as
  with Docker's bind mount); each call uploads what changed there since the
  last call (``SANDBOX_SYNC_MAX_BYTES`` at most), runs, and brings back what
  the code wrote under the workspace (outputs, ``$ARTIFACTS_DIR``). Host
  paths in the argv, working directory and environment become pod paths
  (``/sandbox/<n>``) going in, and back in the output.
* **Persistence** — there is no paused pod on AKS: ``pause`` and the idle
  reaper (``SANDBOX_IDLE_DELETE_SECONDS``) save the workspace to Blob
  (``<namespace>/scratch/sandbox/<pod>/workspace.tar.gz``, kept
  ``SANDBOX_SCRATCH_RETENTION_DAYS`` by the container's lifecycle rule) and
  delete the pod; the next ``ensure`` restores it.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

import httpx

from src.ai.tools.sandbox.runtime import ExecResult

logger = logging.getLogger(__name__)

POD_ROOT = "/sandbox"
READY_TIMEOUT_SECONDS = 180
LAST_USED = "hirebuddha.com/last-used"
TOUCH_EVERY_SECONDS = 60
_endpoints: Dict[str, Tuple[str, str]] = {}          # pod → (base URL, token)
_synced: Dict[Tuple[str, str], Dict[str, Tuple[int, float]]] = {}   # (pod, root) → path → (size, mtime)
_touched: Dict[str, float] = {}
_locks: Dict[str, asyncio.Lock] = {}


def pod_name(company_id: str, network: str) -> str:
    return "sbx-" + hashlib.sha256(f"{company_id}:{network}".encode()).hexdigest()[:16]


def proxy_secret(principal: str) -> str:
    """The egress proxy's password for a principal (``t-<key>/sbx-web``): an HMAC of the shared secret."""
    from src.common.config import settings

    secret = settings.EGRESS_PROXY_SECRET or hmac.new(settings.SECRET_KEY.encode(), b"egress-proxy",
                                                      hashlib.sha256).hexdigest()
    return hmac.new(secret.encode(), principal.encode(), hashlib.sha256).hexdigest()[:32]


def proxy_url(principal: str) -> str:
    """``http://<principal>:<password>@egress-proxy…:8888`` (the principal's ``/`` escaped)."""
    from src.common.config import settings

    base = settings.EGRESS_PROXY_URL
    scheme, _, rest = base.partition("://")
    return f"{scheme}://{quote(principal, safe='')}:{proxy_secret(principal)}@{rest}"


def _quantity(value: str) -> str:
    """Docker-style ``1g`` / ``512m`` as a Kubernetes quantity."""
    text = str(value).strip()
    if re.fullmatch(r"\d+(\.\d+)?[gG]", text):
        return text[:-1] + "Gi"
    if re.fullmatch(r"\d+(\.\d+)?[mM]", text):
        return text[:-1] + "Mi"
    return text


def pod_manifest(namespace: str, name: str, *, tenant_key: str, network: str, company_id: str) -> Dict[str, Any]:
    from src.common.config import settings

    env: List[Dict[str, Any]] = [
        {"name": "SANDBOX_AGENT_TOKEN", "valueFrom": {"secretKeyRef": {"name": f"{name}-token", "key": "token"}}},
        {"name": "SANDBOX_ROOT", "value": POD_ROOT}, {"name": "HOME", "value": "/tmp"},
        {"name": "SANDBOX_AGENT_PORT", "value": str(settings.SANDBOX_AGENT_PORT)}]
    if network in ("allowlist", "web"):
        url = proxy_url(f"t-{tenant_key}/sbx-{network}")
        env += [{"name": "HTTPS_PROXY", "value": url}, {"name": "HTTP_PROXY", "value": url},
                {"name": "NO_PROXY", "value": f"data-api.{namespace}.svc.cluster.local"}]
    pool = settings.SANDBOX_K8S_NODE_POOL
    return {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": name, "namespace": namespace,
                     "labels": {"hb/role": "sandbox", "hb/tenant": tenant_key, "hb/network": network,
                                "app.kubernetes.io/name": "sandbox"},
                     "annotations": {LAST_USED: str(int(time.time())), "hirebuddha.com/company": company_id}},
        "spec": {
            "runtimeClassName": settings.SANDBOX_K8S_RUNTIME_CLASS or None,
            "nodeSelector": {"hb/pool": pool},
            "tolerations": [{"key": "hb/pool", "operator": "Equal", "value": pool, "effect": "NoSchedule"}],
            "automountServiceAccountToken": False, "enableServiceLinks": False, "restartPolicy": "Always",
            "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001, "fsGroup": 10001,
                                "seccompProfile": {"type": "RuntimeDefault"}},
            "containers": [{
                "name": "sandbox", "image": settings.SANDBOX_K8S_IMAGE, "imagePullPolicy": "IfNotPresent",
                "command": ["python3", "/opt/hb/agent.py"], "env": env,
                "ports": [{"name": "agent", "containerPort": settings.SANDBOX_AGENT_PORT}],
                "readinessProbe": {"httpGet": {"path": "/healthz", "port": settings.SANDBOX_AGENT_PORT},
                                   "periodSeconds": 2},
                "resources": {"requests": {"cpu": "250m", "memory": "512Mi"},
                              "limits": {"cpu": settings.SANDBOX_CPUS, "memory": _quantity(settings.SANDBOX_MEMORY),
                                         "ephemeral-storage": settings.SANDBOX_K8S_WORKSPACE_LIMIT}},
                "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                    "capabilities": {"drop": ["ALL"]}},
                "volumeMounts": [{"name": "sandbox", "mountPath": POD_ROOT}, {"name": "tmp", "mountPath": "/tmp"}],
            }],
            "volumes": [{"name": "sandbox", "emptyDir": {"sizeLimit": settings.SANDBOX_K8S_WORKSPACE_LIMIT}},
                        {"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}}],
        },
    }


def network_policy(namespace: str) -> Dict[str, Any]:
    """Sandbox pods of a tenant: in from the platform only; out to DNS, the Data API, the egress proxy (§13.2)."""
    from src.common.config import settings

    return {
        "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
        "metadata": {"name": "sandbox-isolation", "namespace": namespace},
        "spec": {
            "podSelector": {"matchLabels": {"hb/role": "sandbox"}}, "policyTypes": ["Ingress", "Egress"],
            "ingress": [{"from": [{"namespaceSelector": {"matchLabels": {
                "kubernetes.io/metadata.name": "hb-platform"}}}],
                "ports": [{"protocol": "TCP", "port": settings.SANDBOX_AGENT_PORT}]}],
            "egress": [
                {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
                         "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}],
                 "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]},
                {"to": [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "data-api"}}}],
                 "ports": [{"protocol": "TCP", "port": 8080}]},
                {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "hb-system"}},
                         "podSelector": {"matchLabels": {"app.kubernetes.io/name": "egress-proxy"}}}],
                 "ports": [{"protocol": "TCP", "port": 8888}]},
            ],
        },
    }


class PathMap:
    """Host roots ↔ pod roots (``/sandbox/0`` is the workspace)."""

    def __init__(self, roots: Sequence[str]) -> None:
        self.roots = [(os.path.abspath(r), f"{POD_ROOT}/{i}") for i, r in enumerate(roots)]

    @staticmethod
    def _pattern(root: str) -> "re.Pattern[str]":
        """The root written with either separator, then the rest of a path (captured)."""
        parts = [re.escape(p) for p in re.split(r"[\\/]+", root) if p]
        lead = r"[\\/]" if root.startswith(("/", "\\")) else ""
        return re.compile(lead + r"[\\/]+".join(parts) + r"""((?:[\\/][^\s"'`<>|;]*)?)""", re.IGNORECASE)

    def to_pod(self, text: str) -> str:
        if not text:
            return text
        for host, pod in sorted(self.roots, key=lambda r: len(r[0]), reverse=True):
            text = self._pattern(host).sub(lambda m: pod + m.group(1).replace("\\", "/"), text)
        return text

    def to_host(self, text: str) -> str:
        if not text:
            return text
        for host, pod in sorted(self.roots, key=lambda r: len(r[1]), reverse=True):
            text = re.sub(re.escape(pod) + r"((?:/[^\s\"'`<>|;]*)?)",
                          lambda m: host + m.group(1).replace("/", os.sep), text)
        return text

    def host_of(self, pod_path: str) -> Optional[str]:
        for host, pod in self.roots:
            if pod_path == pod or pod_path.startswith(pod + "/"):
                return os.path.join(host, *pod_path[len(pod):].strip("/").split("/")) if pod_path != pod else host
        return None


class KubernetesSandboxRuntime:
    """``SandboxRuntime`` backed by a sandbox pod on AKS."""

    def __init__(self, company_id: Optional[str] = None, *, network: str = "none", kube: Any = None,
                 transport: Optional[httpx.AsyncBaseTransport] = None, roots: Optional[Sequence[str]] = None) -> None:
        self.company_id = str(company_id) if company_id else "_shared"
        self.network = network
        self._kube = kube
        self._transport = transport
        self.name = pod_name(self.company_id, network)
        if roots is None:
            from src.ai.tools.sandbox.tenant_manager import mounted_roots

            roots = mounted_roots(self.company_id)
        self.paths = PathMap(roots)
        self._namespace: Optional[str] = None
        self._tenant_key: Optional[str] = None

    @property
    def kube(self) -> Any:
        if self._kube is None:
            from src.common.platform.kube import get_kube

            self._kube = get_kube()
        return self._kube

    async def _where(self) -> Tuple[str, str]:
        if self._namespace is None:
            from src.common.tenancy.directory import directory

            location = await directory.get(self.company_id)
            self._tenant_key, self._namespace = location.key, f"t-{location.key}"
        return self._namespace, self._tenant_key or ""

    # ── lifecycle ──────────────────────────────────────────────────────────
    async def ensure(self) -> None:
        await self._endpoint()

    async def _endpoint(self) -> Tuple[str, str]:
        if self.name in _endpoints:
            return _endpoints[self.name]
        lock = _locks.setdefault(self.name, asyncio.Lock())
        async with lock:
            if self.name in _endpoints:
                return _endpoints[self.name]
            from src.common.platform.kube import path_for

            namespace, tenant_key = await self._where()
            pod = await self.kube.find(path_for("Pod", namespace, self.name))
            created = False
            if pod is None or (pod.get("status") or {}).get("phase") in ("Failed", "Succeeded"):
                if pod is not None:
                    await self.kube.delete(path_for("Pod", namespace, self.name))
                token = secrets.token_urlsafe(32)
                await self.kube.apply(network_policy(namespace))
                await self.kube.apply({"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
                                       "metadata": {"name": f"{self.name}-token", "namespace": namespace,
                                                    "labels": {"hb/role": "sandbox"}},
                                       "stringData": {"token": token}})
                await self.kube.apply(pod_manifest(namespace, self.name, tenant_key=tenant_key, network=self.network,
                                                   company_id=self.company_id))
                created = True
            else:
                secret = await self.kube.get(path_for("Secret", namespace, f"{self.name}-token"))
                token = base64.b64decode(secret["data"]["token"]).decode()
            ip = await self._wait_ready(namespace)
            from src.common.config import settings

            _endpoints[self.name] = (f"http://{ip}:{settings.SANDBOX_AGENT_PORT}", token)
            if created:
                for key in [k for k in _synced if k[0] == self.name]:
                    _synced.pop(key, None)
                await self._restore(namespace)
        return _endpoints[self.name]

    async def _wait_ready(self, namespace: str) -> str:
        from src.common.platform.kube import path_for

        from src.common.config import settings

        wait = settings.SANDBOX_K8S_READY_TIMEOUT_SECONDS or READY_TIMEOUT_SECONDS
        deadline = time.monotonic() + wait
        while True:
            pod = await self.kube.get(path_for("Pod", namespace, self.name))
            status = pod.get("status") or {}
            ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in status.get("conditions") or [])
            if ready and status.get("podIP"):
                return status["podIP"]
            if status.get("phase") == "Failed":
                raise RuntimeError(f"sandbox pod {self.name} failed: {status.get('reason') or status.get('message')}")
            if time.monotonic() > deadline:
                raise RuntimeError(f"sandbox pod {self.name} was not ready in {wait}s")
            await asyncio.sleep(1)

    def _scratch_key(self, namespace: str) -> str:
        return f"{namespace}/scratch/sandbox/{self.name}/workspace.tar.gz"

    async def _restore(self, namespace: str) -> None:
        from src.common.platform.storage import StorageObjectNotFound, get_storage

        try:
            data = await get_storage().get(self._scratch_key(namespace))
        except StorageObjectNotFound:
            return
        except Exception:  # noqa: BLE001 - a fresh workspace rather than no sandbox
            logger.warning("sandbox %s: saved workspace not restored", self.name, exc_info=True)
            return
        await self._agent("POST", "/restore", params={"path": f"{POD_ROOT}/0"}, content=data)

    async def _save(self) -> None:
        from src.common.platform.storage import get_storage

        namespace, _ = await self._where()
        if self.name not in _endpoints:
            return
        data = await self._agent("GET", "/archive", params={"path": f"{POD_ROOT}/0"}, raw=True)
        await get_storage().put(self._scratch_key(namespace), data, content_type="application/gzip")

    async def _delete_pod(self) -> None:
        from src.common.platform.kube import path_for

        namespace, _ = await self._where()
        await self.kube.delete(path_for("Pod", namespace, self.name))
        _endpoints.pop(self.name, None)
        for key in [k for k in _synced if k[0] == self.name]:
            _synced.pop(key, None)

    async def pause(self) -> None:
        """No paused pods on AKS: save the workspace and delete the pod."""
        try:
            await self._save()
        finally:
            await self._delete_pod()

    async def resume(self) -> None:
        await self.ensure()

    async def destroy(self) -> None:
        from src.common.platform.kube import path_for

        try:
            await self._save()
        except Exception:  # noqa: BLE001 - destroying goes on
            logger.warning("sandbox %s: workspace not saved before destroy", self.name, exc_info=True)
        await self._delete_pod()
        namespace, _ = await self._where()
        await self.kube.delete(path_for("Secret", namespace, f"{self.name}-token"))

    # ── the agent ──────────────────────────────────────────────────────────
    async def _agent(self, method: str, path: str, *, json_body: Any = None, params: Optional[Dict[str, Any]] = None,
                     content: Optional[bytes] = None, raw: bool = False, timeout: float = 60) -> Any:
        base, token = await self._endpoint()
        async with httpx.AsyncClient(base_url=base, transport=self._transport, timeout=timeout) as client:
            try:
                response = await client.request(method, path, json=json_body, params=params, content=content,
                                                 headers={"Authorization": f"Bearer {token}"})
            except httpx.TransportError:
                _endpoints.pop(self.name, None)   # the pod went away: the next call makes a new one
                raise
        if response.status_code >= 400:
            raise RuntimeError(f"sandbox agent {path}: {response.status_code} {response.text[:300]}")
        return response.content if raw else response.json()

    async def _touch(self) -> None:
        from src.common.platform.kube import path_for

        now = time.time()
        if now - _touched.get(self.name, 0) < TOUCH_EVERY_SECONDS:
            return
        _touched[self.name] = now
        namespace, _ = await self._where()
        try:
            await self.kube.patch(path_for("Pod", namespace, self.name),
                                  {"metadata": {"annotations": {LAST_USED: str(int(now))}}})
        except Exception:  # noqa: BLE001 - the reaper may delete it a little early
            logger.debug("sandbox %s not touched", self.name, exc_info=True)

    async def _sync_in(self) -> None:
        """Upload what changed in the platform's copy of each root since the last call."""
        from src.common.config import settings

        budget = settings.SANDBOX_SYNC_MAX_BYTES
        for host, pod in self.paths.roots:
            if not os.path.isdir(host):
                continue
            known = _synced.setdefault((self.name, pod), {})
            for dirpath, dirnames, filenames in os.walk(host):
                dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__")]
                for filename in filenames:
                    path = os.path.join(dirpath, filename)
                    try:
                        stat = os.stat(path)
                    except OSError:
                        continue
                    rel = os.path.relpath(path, host).replace(os.sep, "/")
                    if known.get(rel) == (stat.st_size, stat.st_mtime):
                        continue
                    budget -= stat.st_size
                    if budget < 0:
                        raise RuntimeError(f"more than {settings.SANDBOX_SYNC_MAX_BYTES} bytes changed in the "
                                           "workspace since the last call")
                    with open(path, "rb") as handle:
                        await self._agent("PUT", "/files", params={"path": f"{pod}/{rel}", "mtime": stat.st_mtime},
                                          content=handle.read())
                    known[rel] = (stat.st_size, stat.st_mtime)

    async def _sync_out(self, changed: List[Dict[str, Any]]) -> None:
        """Bring back what the code wrote (only into the workspace root's copy and its sub-folders)."""
        workspace_host, workspace_pod = self.paths.roots[0]
        known = _synced.setdefault((self.name, workspace_pod), {})
        for item in changed:
            pod_path = item["path"]
            if not pod_path.startswith(workspace_pod + "/"):
                continue
            host = self.paths.host_of(pod_path)
            if host is None:
                continue
            data = await self._agent("GET", "/files", params={"path": pod_path}, raw=True)
            os.makedirs(os.path.dirname(host), exist_ok=True)
            with open(host, "wb") as handle:
                handle.write(data)
            os.utime(host, (item["mtime"], item["mtime"]))
            known[pod_path[len(workspace_pod) + 1:]] = (len(data), item["mtime"])

    async def exec(self, argv: Sequence[str], *, cwd: Optional[str] = None, timeout: float = 30.0,
                   env: Optional[Mapping[str, str]] = None) -> ExecResult:
        started = time.monotonic()
        try:
            await self._endpoint()
            await self._sync_in()
        except Exception as error:  # noqa: BLE001 - reported as a launch failure, never the host
            return ExecResult(returncode=-1, launch_error=f"the sandbox pod is unavailable: {error}")
        body = {"argv": [self.paths.to_pod(str(a)) for a in argv], "timeout": timeout,
                "cwd": self.paths.to_pod(cwd) if cwd else self.paths.roots[0][1],
                "env": {k: self.paths.to_pod(str(v)) for k, v in (env or {}).items()},
                "watch": [self.paths.roots[0][1]]}
        try:
            result = await self._agent("POST", "/exec", json_body=body, timeout=float(timeout) + 30)
            await self._sync_out(result.get("changed") or [])
        except Exception as error:  # noqa: BLE001
            return ExecResult(returncode=-1, launch_error=f"the sandbox call failed: {error}",
                              duration_ms=int((time.monotonic() - started) * 1000))
        await self._touch()
        if result.get("timed_out"):
            return ExecResult(returncode=-1, timed_out=True, duration_ms=result.get("duration_ms", 0))
        return ExecResult(returncode=int(result.get("returncode", -1)),
                          stdout=self.paths.to_host(result.get("stdout") or ""),
                          stderr=self.paths.to_host(result.get("stderr") or ""),
                          duration_ms=int(result.get("duration_ms") or 0),
                          not_found=bool(result.get("not_found")), launch_error=result.get("launch_error"))

    async def run_browser(self, request: Mapping[str, Any], *, timeout: float) -> Dict[str, Any]:
        """The browser session's steps, by the runner in the company's ``web`` pod."""
        from src.ai.tools.sandbox import browser_runner
        from src.ai.tools.sandbox.container_runtime import install_browser_runner
        from src.ai.tools.sandbox.workspace import tenant_workspace

        runner = install_browser_runner(self.company_id)
        call_dir = os.path.join(tenant_workspace(self.company_id), ".browser-calls", uuid.uuid4().hex[:12])
        os.makedirs(call_dir, exist_ok=True)
        request_path = os.path.join(call_dir, "request.json")
        with open(request_path, "w", encoding="utf-8") as fh:
            json.dump({"steps": list(request.get("steps") or []), "timeout_ms": int(request.get("timeout_ms") or 30000)},
                      fh)
        env = {"HOME": "/tmp"}
        if request.get("out_dir"):
            env["ARTIFACTS_DIR"] = str(request["out_dir"])
        if request.get("user_data_dir"):
            env[browser_runner.PROFILE_ENV] = str(request["user_data_dir"])
        web = self if self.network == "web" else KubernetesSandboxRuntime(
            self.company_id, network="web", kube=self._kube, transport=self._transport,
            roots=[h for h, _ in self.paths.roots])
        res = await web.exec(["python3", runner, request_path], cwd=call_dir, timeout=timeout, env=env)
        if browser_runner.MARKER not in res.stdout:
            reason = res.launch_error or ("timed out" if res.timed_out else (res.stderr or res.stdout)[-500:])
            raise RuntimeError(f"the browser runner failed in the sandbox pod: {reason}")
        return json.loads(res.stdout.split(browser_runner.MARKER, 1)[1].strip().splitlines()[0])

    # ── file ops: the platform's copy; the pod sees it at the next call ──────
    async def write_file(self, path: str, content: bytes) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(content)

    async def read_file(self, path: str) -> bytes:
        with open(path, "rb") as fh:
            return fh.read()

    async def list_dir(self, path: str) -> List[str]:
        return os.listdir(path)


async def reap_idle(kube: Any = None, now: Optional[float] = None) -> Dict[str, int]:
    """Save and delete sandbox pods idle longer than ``SANDBOX_IDLE_DELETE_SECONDS`` (every namespace)."""
    from src.common.config import settings
    from src.common.platform.kube import get_kube

    kube = kube or get_kube()
    now = now or time.time()
    pods = await kube.list("/api/v1/pods", labels={"hb/role": "sandbox"})
    reaped = failed = 0
    for pod in pods:
        meta = pod.get("metadata") or {}
        last = float((meta.get("annotations") or {}).get(LAST_USED) or 0)
        if now - last < settings.SANDBOX_IDLE_DELETE_SECONDS:
            continue
        company = (meta.get("annotations") or {}).get("hirebuddha.com/company") or "_shared"
        runtime = KubernetesSandboxRuntime(company, network=(meta.get("labels") or {}).get("hb/network", "none"),
                                           kube=kube, roots=[])
        runtime.name = meta["name"]
        runtime._namespace = meta["namespace"]  # noqa: SLF001
        try:
            await runtime.pause()
            reaped += 1
        except Exception:  # noqa: BLE001 - tried again at the next sweep
            logger.exception("sandbox pod %s/%s not reaped", meta.get("namespace"), meta.get("name"))
            failed += 1
    return {"reaped": reaped, "failed": failed}

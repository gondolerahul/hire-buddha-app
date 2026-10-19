"""Where apps run (Phase 14 WS6 6.8, 6.11; tech spec §11.5, §11.7).

``AppSpec`` is one running instance of an app — the published app, or a
preview of one pull request — and an :class:`AppRuntime` runs it
(``APP_RUNTIME``, default from ``PLATFORM_PROFILE``):

* ``kubernetes`` — writes a ``TenantApp`` object (and the Secret with the
  app's key) in the tenant's namespace; the App Controller makes the
  Deployment, Service, routes and policies, and the tenant edge serves it.
  Stop, start, restart and rollback are changes to that object, so they work
  even when the platform's workers are down.
* ``docker`` — a container on this machine (development): published on a
  local port, read-only root, ``/tmp`` in memory, the spec's CPU and memory.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RuntimeProblem(RuntimeError):
    pass


@dataclass
class AppSpec:
    tenant_key: str
    app: str                         # the app's name: crm
    instance: str                    # crm (published), crm-pr7 (a preview)
    image: str
    port: int = 8080
    health_path: str = "/healthz"
    env: Dict[str, str] = field(default_factory=dict)
    app_key: Optional[str] = None    # the app's Data API key (a Secret on the cluster)
    resources: Dict[str, Any] = field(default_factory=dict)
    mode: str = "always_on"
    hostnames: List[str] = field(default_factory=list)
    egress: List[str] = field(default_factory=list)
    previous_images: List[str] = field(default_factory=list)
    stopped: bool = False

    @property
    def namespace(self) -> str:
        return f"t-{self.tenant_key}"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tenant_app(spec: AppSpec) -> Dict[str, Any]:
    """The ``TenantApp`` object for a spec."""
    return {
        "apiVersion": "hirebuddha.com/v1", "kind": "TenantApp",
        "metadata": {"name": spec.instance, "namespace": spec.namespace,
                     "labels": {"hb/tenant": spec.tenant_key, "hb/app": spec.app}},
        "spec": {"tenantKey": spec.tenant_key, "app": spec.app, "image": spec.image, "healthPath": spec.health_path,
                 "env": dict(spec.env), "appKeySecret": f"{spec.instance}-key" if spec.app_key else None,
                 "resources": dict(spec.resources), "mode": spec.mode, "routes": list(spec.hostnames),
                 "egress": list(spec.egress), "previousImages": list(spec.previous_images)[-5:],
                 "stopped": spec.stopped},
    }


class KubernetesAppRuntime:
    name = "kubernetes"

    def __init__(self, kube: Any = None) -> None:
        self._kube = kube

    @property
    def kube(self) -> Any:
        if self._kube is None:
            from src.common.platform.kube import get_kube

            self._kube = get_kube()
        return self._kube

    def _path(self, namespace: str, name: Optional[str] = None) -> str:
        from src.common.platform.kube import path_for

        return path_for("TenantApp", namespace, name)

    async def apply(self, spec: AppSpec) -> Dict[str, Any]:
        if spec.app_key:
            await self.kube.apply({"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
                                   "metadata": {"name": f"{spec.instance}-key", "namespace": spec.namespace,
                                                "labels": {"hb/tenant": spec.tenant_key, "hb/app": spec.app}},
                                   "stringData": {"key": spec.app_key}})
        await self.kube.apply(tenant_app(spec))
        return {"ref": f"{spec.namespace}/{spec.instance}", "url": f"https://{spec.hostnames[0]}" if spec.hostnames else None}

    async def _patch(self, namespace: str, instance: str, spec_patch: Dict[str, Any]) -> None:
        await self.kube.patch(self._path(namespace, instance), {"spec": spec_patch})

    async def stop(self, namespace: str, instance: str) -> None:
        await self._patch(namespace, instance, {"stopped": True})

    async def start(self, namespace: str, instance: str) -> None:
        await self._patch(namespace, instance, {"stopped": False})

    async def restart(self, namespace: str, instance: str) -> None:
        await self._patch(namespace, instance, {"restartedAt": _now()})

    async def delete(self, namespace: str, instance: str) -> None:
        from src.common.platform.kube import path_for

        await self.kube.delete(self._path(namespace, instance))
        await self.kube.delete(path_for("Secret", namespace, f"{instance}-key"))

    async def status(self, namespace: str, instance: str) -> Dict[str, Any]:
        found = await self.kube.find(self._path(namespace, instance))
        if found is None:
            return {"phase": "Missing"}
        return {**(found.get("status") or {}), "stopped": bool((found.get("spec") or {}).get("stopped"))}

    async def logs(self, namespace: str, instance: str, *, tail: int = 200, since_seconds: Optional[int] = None) -> str:
        from src.common.platform.kube import path_for

        pods = await self.kube.list(path_for("Pod", namespace), labels={"app.kubernetes.io/name": instance})
        chunks = []
        for pod in pods[:5]:
            name = pod["metadata"]["name"]
            text = await self.kube.logs(namespace, name, tail=tail, container="app", since_seconds=since_seconds)
            chunks.append(f"── {name} ──\n{text}")
        return "\n".join(chunks)

    async def metrics(self, namespace: str, instance: str) -> Dict[str, Any]:
        from src.apps.metering import prometheus_query

        selector = f'namespace="{namespace}",pod=~"{re.escape(instance)}-.*",container="app"'
        cpu = await prometheus_query(f"sum(rate(container_cpu_usage_seconds_total{{{selector}}}[5m]))")
        memory = await prometheus_query(f"sum(container_memory_working_set_bytes{{{selector}}})")
        return {"cpu_cores": cpu, "memory_bytes": memory, "source": "prometheus"}


class DockerAppRuntime:
    """A container per instance on this machine; ``url`` is ``http://localhost:<port>``."""

    name = "docker"

    @staticmethod
    def container(namespace: str, instance: str) -> str:
        return f"hbapp-{namespace}-{instance}"

    async def _docker(self, *args: str, check: bool = True, timeout: float = 120) -> str:
        if not shutil.which("docker"):
            raise RuntimeProblem("the docker CLI is not on this machine (APP_RUNTIME=docker)")
        proc = await asyncio.create_subprocess_exec("docker", *args, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if check and proc.returncode != 0:
            raise RuntimeProblem(f"docker {args[0]}: {err.decode(errors='replace').strip()[:500]}")
        return out.decode(errors="replace")

    async def apply(self, spec: AppSpec) -> Dict[str, Any]:
        name = self.container(spec.namespace, spec.instance)
        await self._docker("rm", "-f", name, check=False)
        resources = spec.resources or {}
        argv = ["run", "-d", "--name", name, "--label", f"hb.tenant={spec.tenant_key}", "--label",
                f"hb.app={spec.app}", "--label", f"hb.instance={spec.instance}", "-p", f"127.0.0.1::{spec.port}",
                "--read-only", "--tmpfs", "/tmp:rw,size=256m", "--security-opt", "no-new-privileges",
                "--cap-drop", "ALL", "--memory", _docker_memory(resources.get("memory", "256Mi")),
                "--cpus", str(_cores(resources.get("cpu", "250m"))), "--add-host", "host.docker.internal:host-gateway"]
        env = dict(spec.env)
        if spec.app_key:
            env["HB_APP_KEY"] = spec.app_key
        for key, value in sorted(env.items()):
            argv += ["-e", f"{key}={value}"]
        await self._docker(*argv, spec.image)
        if spec.stopped:
            await self._docker("stop", name)
            return {"ref": name, "url": None}
        mapping = (await self._docker("port", name, str(spec.port))).strip().splitlines()
        port = mapping[0].rsplit(":", 1)[-1] if mapping else None
        return {"ref": name, "url": f"http://localhost:{port}" if port else None}

    async def stop(self, namespace: str, instance: str) -> None:
        await self._docker("stop", self.container(namespace, instance))

    async def start(self, namespace: str, instance: str) -> None:
        await self._docker("start", self.container(namespace, instance))

    async def restart(self, namespace: str, instance: str) -> None:
        await self._docker("restart", self.container(namespace, instance))

    async def delete(self, namespace: str, instance: str) -> None:
        await self._docker("rm", "-f", self.container(namespace, instance), check=False)

    async def status(self, namespace: str, instance: str) -> Dict[str, Any]:
        out = await self._docker("inspect", "--format", "{{json .State}}", self.container(namespace, instance),
                                 check=False)
        if not out.strip():
            return {"phase": "Missing"}
        state = json.loads(out)
        phase = "Running" if state.get("Running") else ("Failed" if state.get("ExitCode") else "Stopped")
        return {"phase": phase, "readyReplicas": 1 if state.get("Running") else 0,
                "started_at": state.get("StartedAt"), "exit_code": state.get("ExitCode")}

    async def logs(self, namespace: str, instance: str, *, tail: int = 200, since_seconds: Optional[int] = None) -> str:
        argv = ["logs", "--timestamps", "--tail", str(tail)]
        if since_seconds:
            argv += ["--since", f"{since_seconds}s"]
        proc_out = await self._docker(*argv, self.container(namespace, instance), check=False)
        return proc_out

    async def metrics(self, namespace: str, instance: str) -> Dict[str, Any]:
        out = await self._docker("stats", "--no-stream", "--format", "{{json .}}", self.container(namespace, instance),
                                 check=False)
        try:
            stats = json.loads(out.strip().splitlines()[0])
        except (ValueError, IndexError):
            return {"source": "docker", "available": False}
        return {"source": "docker", "cpu_percent": stats.get("CPUPerc"), "memory": stats.get("MemUsage"),
                "network": stats.get("NetIO")}


def _cores(cpu: Any) -> float:
    text = str(cpu)
    return round(int(text[:-1]) / 1000, 3) if text.endswith("m") else float(text)


def _docker_memory(memory: Any) -> str:
    text = str(memory)
    for suffix, unit in (("Gi", "g"), ("Mi", "m"), ("G", "g"), ("M", "m")):
        if text.endswith(suffix):
            return text[: -len(suffix)] + unit
    return text


def gb(memory: Any) -> float:
    """``256Mi`` → 0.25 (GiB, for metering)."""
    text = str(memory)
    if text.endswith("Gi"):
        return float(text[:-2])
    if text.endswith("Mi"):
        return float(text[:-2]) / 1024
    if text.endswith("G"):
        return float(text[:-1])
    if text.endswith("M"):
        return float(text[:-1]) / 1024
    return float(text) / (1024 ** 3)


cores = _cores

_runtime: Any = None


def get_runtime() -> Any:
    global _runtime
    if _runtime is None:
        from src.common.platform import AdapterNotAvailable, adapter_name

        name = adapter_name("app_runtime")
        if name == "docker":
            _runtime = DockerAppRuntime()
        elif name == "kubernetes":
            _runtime = KubernetesAppRuntime()
        else:
            raise AdapterNotAvailable(f"APP_RUNTIME={name!r} has no adapter (docker, kubernetes)")
    return _runtime


def set_runtime(runtime: Any) -> None:
    global _runtime
    _runtime = runtime


__all__ = ["AppSpec", "DockerAppRuntime", "KubernetesAppRuntime", "RuntimeProblem", "cores", "gb", "get_runtime",
           "set_runtime", "tenant_app"]

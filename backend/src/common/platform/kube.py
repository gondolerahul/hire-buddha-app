"""A small Kubernetes API client (Phase 14 WS6, tech spec §11).

What the platform asks of a cluster is narrow — sandbox pods and their
secrets, ``TenantApp`` objects, the edge's route config, pod logs — so this
talks to the API server over HTTPS with ``httpx`` instead of pulling in a
Kubernetes SDK. Objects are written with **server-side apply** (``PATCH``
``application/apply-patch+yaml``, field manager ``hirebuddha``), so writing
the same object twice is a no-op and two writers never fight over fields
they do not own.

Credentials: inside a pod, the projected service-account token and CA
(``/var/run/secrets/kubernetes.io/serviceaccount``); elsewhere
``KUBE_API_URL`` + ``KUBE_TOKEN`` (+ ``KUBE_CA_FILE``). Tests install a client
over an ``httpx.MockTransport`` with :func:`set_kube`.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

__all__ = ["FIELD_MANAGER", "KubeClient", "KubeError", "KubeNotFound", "get_kube", "path_for", "set_kube",
           "token_expiry"]

FIELD_MANAGER = "hirebuddha"
_SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
# kind → (api prefix, plural); anything else names its plural explicitly.
_KINDS = {
    "Pod": ("/api/v1", "pods"), "Secret": ("/api/v1", "secrets"), "Service": ("/api/v1", "services"),
    "ConfigMap": ("/api/v1", "configmaps"), "ServiceAccount": ("/api/v1", "serviceaccounts"),
    "Namespace": ("/api/v1", "namespaces"), "ResourceQuota": ("/api/v1", "resourcequotas"),
    "LimitRange": ("/api/v1", "limitranges"),
    "Deployment": ("/apis/apps/v1", "deployments"),
    "Job": ("/apis/batch/v1", "jobs"),
    "NetworkPolicy": ("/apis/networking.k8s.io/v1", "networkpolicies"),
    "PodDisruptionBudget": ("/apis/policy/v1", "poddisruptionbudgets"),
    "TenantApp": ("/apis/hirebuddha.com/v1", "tenantapps"),
    "HTTPScaledObject": ("/apis/http.keda.sh/v1alpha1", "httpscaledobjects"),
}
_CLUSTER_SCOPED = {"Namespace"}


class KubeError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"kubernetes API {status}: {message}")
        self.status = status


class KubeNotFound(KubeError):
    pass


def path_for(kind: str, namespace: Optional[str] = None, name: Optional[str] = None,
             *, api_version: Optional[str] = None, plural: Optional[str] = None) -> str:
    """The API path of a kind (in a namespace), or of one object of it."""
    if kind in _KINDS and not (api_version or plural):
        prefix, plural = _KINDS[kind]
    else:
        if not (api_version and plural):
            raise ValueError(f"unknown kind {kind!r}: give api_version and plural")
        prefix = "/api/v1" if api_version == "v1" else f"/apis/{api_version}"
    path = prefix
    if namespace and kind not in _CLUSTER_SCOPED:
        path += f"/namespaces/{namespace}"
    path += f"/{plural}"
    if name:
        path += f"/{name}"
    return path


def _object_path(body: Dict[str, Any]) -> str:
    kind = body["kind"]
    meta = body.get("metadata") or {}
    if kind in _KINDS:
        return path_for(kind, meta.get("namespace"), meta["name"])
    group_version = body["apiVersion"]
    plural = kind.lower() + "s"
    return path_for(kind, meta.get("namespace"), meta["name"], api_version=group_version, plural=plural)


class KubeClient:
    def __init__(self, base_url: str, *, token: Optional[str] = None, verify: Any = True,
                 transport: Optional[httpx.AsyncBaseTransport] = None, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._verify = verify
        self._transport = transport
        self._timeout = timeout

    @classmethod
    def from_settings(cls) -> "KubeClient":
        from src.common.config import settings

        if settings.KUBE_API_URL:
            return cls(settings.KUBE_API_URL, token=settings.KUBE_TOKEN or None,
                       verify=settings.KUBE_CA_FILE or True)
        host, port = os.environ.get("KUBERNETES_SERVICE_HOST"), os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        if host and (_SA_DIR / "token").exists():
            return _InClusterClient(f"https://{host}:{port}", verify=str(_SA_DIR / "ca.crt"))
        raise KubeError(0, "no Kubernetes API: not in a pod, and KUBE_API_URL is not set")

    def _headers(self, content_type: Optional[str] = None) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        token = self.token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def token(self) -> Optional[str]:
        return self._token

    async def request(self, method: str, path: str, *, body: Any = None, params: Optional[Dict[str, Any]] = None,
                      content_type: Optional[str] = None, raw: bool = False) -> Any:
        content = None
        if body is not None:
            content = body if isinstance(body, (bytes, str)) else json.dumps(body)
            content_type = content_type or "application/json"
        async with httpx.AsyncClient(base_url=self.base_url, verify=self._verify, transport=self._transport,
                                     timeout=self._timeout) as client:
            response = await client.request(method, path, content=content, params=params,
                                            headers=self._headers(content_type))
        if response.status_code == 404:
            raise KubeNotFound(404, path)
        if response.status_code >= 400:
            try:
                message = response.json().get("message") or response.text
            except ValueError:
                message = response.text
            raise KubeError(response.status_code, str(message)[:500])
        if raw:
            return response.text
        return response.json() if response.content else {}

    async def get(self, path: str) -> Dict[str, Any]:
        return await self.request("GET", path)

    async def find(self, path: str) -> Optional[Dict[str, Any]]:
        try:
            return await self.get(path)
        except KubeNotFound:
            return None

    async def list(self, path: str, *, labels: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        params = {"labelSelector": ",".join(f"{k}={v}" for k, v in labels.items())} if labels else None
        return list((await self.request("GET", path, params=params)).get("items") or [])

    async def apply(self, body: Dict[str, Any], *, force: bool = True) -> Dict[str, Any]:
        """Create or update an object by server-side apply."""
        return await self.request("PATCH", _object_path(body), body=body,
                                  content_type="application/apply-patch+yaml",
                                  params={"fieldManager": FIELD_MANAGER, "force": "true" if force else "false"})

    async def create(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new object (POST): for one-off objects whose callers may create but not patch."""
        meta = body.get("metadata") or {}
        return await self.request("POST", path_for(body["kind"], meta.get("namespace")), body=body)

    async def patch(self, path: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        """A JSON merge patch (``status``, an annotation)."""
        return await self.request("PATCH", path, body=patch, content_type="application/merge-patch+json")

    async def delete(self, path: str) -> bool:
        """Delete one object (its dependents in the background); ``False`` when it was not there."""
        try:
            await self.request("DELETE", path, body={"propagationPolicy": "Background"})
        except KubeNotFound:
            return False
        return True

    async def logs(self, namespace: str, pod: str, *, tail: int = 200, container: Optional[str] = None,
                   since_seconds: Optional[int] = None) -> str:
        params: Dict[str, Any] = {"tailLines": tail, "timestamps": "true"}
        if container:
            params["container"] = container
        if since_seconds:
            params["sinceSeconds"] = since_seconds
        return await self.request("GET", path_for("Pod", namespace, pod) + "/log", params=params, raw=True)


def token_expiry(token: str) -> Optional[datetime]:
    """When to stop using a service-account token: 5 minutes (at most a tenth of its life) before it
    expires — after the kubelet has replaced the file (at 80 % of its life). None if it is not a JWT."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        issued, expires = int(claims["iat"]), int(claims["exp"])
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    return datetime.fromtimestamp(expires - min(300, (expires - issued) // 10), tz=timezone.utc)


class _InClusterClient(KubeClient):
    """Re-reads the projected token (it rotates hourly)."""

    def token(self) -> Optional[str]:
        try:
            return (_SA_DIR / "token").read_text().strip()
        except OSError:
            return None


_client: Optional[KubeClient] = None


def get_kube() -> KubeClient:
    global _client
    if _client is None:
        _client = KubeClient.from_settings()
    return _client


def set_kube(client: Optional[KubeClient]) -> None:
    global _client
    _client = client

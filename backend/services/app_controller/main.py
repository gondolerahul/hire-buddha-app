"""The App Controller (Phase 14 WS6 6.8, 6.9; tech spec §11.5): a kopf operator.

    kopf run --all-namespaces services/app_controller/main.py

For each ``TenantApp`` (``tenantapps.hirebuddha.com/v1``) it applies what
``src.apps.controller.children`` renders — owned by the TenantApp, so
deleting it deletes them — and writes its status from the Deployment. After
any change it re-renders, from every TenantApp, the tenant edge's Caddyfile
(ConfigMap ``hb-system/tenant-edge-config``; Caddy runs with ``--watch``)
and the egress proxy's policy (ConfigMap ``hb-system/egress-policy``).
Stop, start, restart and rollback are edits of a TenantApp, so they work when
the platform's workers are down. A periodic pass (every 5 minutes) repairs
drift.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
from typing import Any, Dict, Optional

import kopf

from src.apps import controller
from src.common.platform.kube import KubeClient, KubeNotFound, path_for, token_expiry

log = logging.getLogger("app-controller")
EDGE_CONFIG = "tenant-edge-config"
EGRESS_POLICY = "egress-policy"
_kube: KubeClient | None = None


def kube() -> KubeClient:
    global _kube
    if _kube is None:
        _kube = KubeClient.from_settings()
    return _kube


def _cr(body: Any) -> Dict[str, Any]:
    return {"apiVersion": f"{controller.GROUP}/{controller.VERSION}", "kind": controller.KIND,
            "metadata": dict(body["metadata"]), "spec": dict(body.get("spec") or {})}


async def _all_apps() -> list:
    found = await kube().list(f"/apis/{controller.GROUP}/{controller.VERSION}/{controller.PLURAL}")
    return [app for app in found if not (app.get("metadata") or {}).get("deletionTimestamp")]


async def _publish_edge() -> None:
    """The tenant edge's Caddyfile and the egress proxy's policy, from every TenantApp."""
    from src.apps.api import edge_token
    from src.common.config import settings

    apps = await _all_apps()
    ask = os.environ.get("EDGE_ASK_URL", "http://api.hb-platform.svc.cluster.local:8000/internal/v1/edge/ask")
    caddyfile = controller.edge_caddyfile(apps, ask_url=f"{ask}?token={edge_token()}",
                                          email=os.environ.get("ACME_EMAIL", ""))
    await kube().apply({"apiVersion": "v1", "kind": "ConfigMap",
                        "metadata": {"name": EDGE_CONFIG, "namespace": controller.EDGE_NAMESPACE},
                        "data": {"Caddyfile": caddyfile}})
    defaults = controller.egress_defaults(sandbox=settings.SANDBOX_EGRESS_ALLOWLIST,
                                          checks=settings.CHECKS_EGRESS_ALLOWLIST,
                                          storage_url=settings.AZURE_STORAGE_ACCOUNT_URL)
    policy = {"defaults": defaults, "principals": controller.egress_allowlists(apps)}
    await kube().apply({"apiVersion": "v1", "kind": "ConfigMap",
                        "metadata": {"name": EGRESS_POLICY, "namespace": controller.EDGE_NAMESPACE},
                        "data": {"policy.json": json.dumps(policy, indent=1, sort_keys=True)}})


async def reconcile(body: Any, patch: Any) -> Dict[str, Any]:
    cr = _cr(body)
    applied = []
    for child in controller.children(cr):
        await kube().apply(child)
        applied.append(f"{child['kind']}/{child['metadata']['name']}")
    if cr["spec"].get("mode") != "sleep":   # sleeping apps lose their scaler when they wake up for good
        try:
            await kube().delete(path_for("HTTPScaledObject", cr["metadata"]["namespace"], cr["metadata"]["name"]))
        except KubeNotFound:
            pass
    deploy = await kube().find(path_for("Deployment", cr["metadata"]["namespace"], cr["metadata"]["name"]))
    patch.status.update(controller.status_of(deploy, cr))
    await _publish_edge()
    return {"applied": applied}


@kopf.on.login()
def login(**kwargs: Any) -> Optional[kopf.ConnectionInfo]:
    """The pod's token with an expiry. AKS's projected token lives an hour and the kubelet replaces the
    file after ~48 minutes; kopf's own handler gives it no expiry, so kopf kept it until the API refused
    it, re-read the same file and stopped with "ran out of valid credentials" (hourly restarts on Azure
    dev, 21 Oct 2026). Expiring it first makes kopf read the replaced file in time."""
    info = kopf.login_with_service_account(**kwargs)
    if info is None:   # outside a pod: the developer's kubeconfig
        return kopf.login_with_kubeconfig(**kwargs)
    if not info.token:
        return info
    return dataclasses.replace(info, expiration=token_expiry(info.token))


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_: Any) -> None:
    settings.persistence.finalizer = "hirebuddha.com/app-controller"
    settings.posting.level = logging.WARNING
    settings.watching.server_timeout = 270


@kopf.on.startup()
async def publish_on_start(**_: Any) -> None:
    """The edge's Caddyfile and the egress policy exist from the start, before any app: the
    edge cannot start without its Caddyfile (found on Azure dev, 21 Oct 2026)."""
    await _publish_edge()


@kopf.on.create(controller.GROUP, controller.VERSION, controller.PLURAL)
@kopf.on.update(controller.GROUP, controller.VERSION, controller.PLURAL, field="spec")
@kopf.on.resume(controller.GROUP, controller.VERSION, controller.PLURAL)
async def apply_app(body: Any, patch: Any, **_: Any) -> Dict[str, Any]:
    return await reconcile(body, patch)


@kopf.timer(controller.GROUP, controller.VERSION, controller.PLURAL, interval=300, initial_delay=60)
async def repair(body: Any, patch: Any, **_: Any) -> None:
    await reconcile(body, patch)


@kopf.on.delete(controller.GROUP, controller.VERSION, controller.PLURAL)
async def removed(**_: Any) -> None:
    # Its children go with it (owner references); the edge stops routing its names.
    await _publish_edge()

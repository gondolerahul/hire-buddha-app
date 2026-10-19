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

import json
import logging
import os
from typing import Any, Dict

import kopf

from src.apps import controller
from src.common.platform.kube import KubeClient, KubeNotFound, path_for

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
    defaults = [h.strip() for h in settings.SANDBOX_EGRESS_ALLOWLIST.split(",") if h.strip()]
    policy = {"defaults": {"sbx-allowlist": defaults}, "principals": controller.egress_allowlists(apps)}
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


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_: Any) -> None:
    settings.persistence.finalizer = "hirebuddha.com/app-controller"
    settings.posting.level = logging.WARNING
    settings.watching.server_timeout = 270


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

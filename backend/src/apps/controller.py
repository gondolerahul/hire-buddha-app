"""The App Controller's reconciliation, as pure functions (Phase 14 WS6 6.8, 6.9; tech spec §11.5).

The operator (``services/app_controller``, kopf) watches ``TenantApp``
objects (``tenantapps.hirebuddha.com/v1``) and, for each, applies what
:func:`children` returns — owned by the ``TenantApp`` so deleting it deletes
them:

* ``ServiceAccount`` (no token mounted) and the app's ``Secret``-mounted key;
* ``Deployment`` — non-root, read-only root file system, ``/tmp`` writable,
  limits from the spec, the image by digest, probes on the health path,
  previous digests kept in an annotation (rollback = set the previous one),
  on the apps node pool (``APPS_NODE_POOL``: its label and taint ``hb/pool``);
* ``Service`` on port 8080;
* ``NetworkPolicy`` — in from the tenant edge only; out to the tenant's Data
  API, the egress proxy and DNS, nothing else (§13.2);
* ``PodDisruptionBudget`` when it runs more than one replica;
* KEDA ``HTTPScaledObject`` when ``mode: sleep`` (to zero when idle).

Across all ``TenantApp`` objects it renders the **tenant app edge**'s
Caddyfile (:func:`edge_caddyfile`, SP-3): one site per hostname, on-demand
TLS (certificates issued at the first request, after the platform's ``ask``
endpoint confirms the hostname), reverse-proxied to the app's Service; and
the egress proxy's allow-lists (:func:`egress_allowlists`).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

GROUP = "hirebuddha.com"
VERSION = "v1"
PLURAL = "tenantapps"
KIND = "TenantApp"
APP_PORT = 8080
KEEP_IMAGES = 5
EDGE_NAMESPACE = "hb-system"
EGRESS_PROXY_PORT = 8888


def labels(spec: Dict[str, Any], name: str) -> Dict[str, str]:
    return {"app.kubernetes.io/name": name, "app.kubernetes.io/managed-by": "hb-app-controller",
            "hb/tenant": spec["tenantKey"], "hb/app": spec["app"], "hb/role": "app"}


def _owner(cr: Dict[str, Any]) -> List[Dict[str, Any]]:
    meta = cr.get("metadata") or {}
    if not meta.get("uid"):
        return []
    return [{"apiVersion": f"{GROUP}/{VERSION}", "kind": KIND, "name": meta["name"], "uid": meta["uid"],
             "controller": True, "blockOwnerDeletion": True}]


def _meta(cr: Dict[str, Any], name: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    spec = cr["spec"]
    meta = {"name": name, "namespace": cr["metadata"]["namespace"], "labels": labels(spec, name),
            "ownerReferences": _owner(cr)}
    if extra:
        meta.update(extra)
    return meta


def _placement() -> Dict[str, Any]:
    """The apps node pool (slice 4, D53): tenant apps run there, not beside the platform."""
    pool = os.environ.get("APPS_NODE_POOL", "").strip()
    if not pool:
        return {}
    return {"nodeSelector": {"hb/pool": pool},
            "tolerations": [{"key": "hb/pool", "operator": "Equal", "value": pool, "effect": "NoSchedule"}]}


def deployment(cr: Dict[str, Any]) -> Dict[str, Any]:
    spec = cr["spec"]
    name = cr["metadata"]["name"]
    resources = spec.get("resources") or {}
    cpu, memory = resources.get("cpu", "250m"), resources.get("memory", "256Mi")
    env = [{"name": k, "value": str(v)} for k, v in sorted((spec.get("env") or {}).items())]
    if spec.get("appKeySecret"):
        env.append({"name": "HB_APP_KEY", "valueFrom": {"secretKeyRef": {"name": spec["appKeySecret"], "key": "key"}}})
    for ref in spec.get("secretRefs") or []:
        env.append({"name": ref["env"], "valueFrom": {"secretKeyRef": {"name": ref["secret"], "key": ref["key"]}}})
    if spec.get("egress"):
        proxy = f"http://egress-proxy.{EDGE_NAMESPACE}.svc.cluster.local:{EGRESS_PROXY_PORT}"
        env += [{"name": "HTTPS_PROXY", "value": proxy}, {"name": "HTTP_PROXY", "value": proxy},
                {"name": "NO_PROXY", "value": f"data-api.t-{spec['tenantKey']}.svc.cluster.local,.svc,.cluster.local"}]
    probe = {"httpGet": {"path": spec.get("healthPath") or "/healthz", "port": APP_PORT}, "periodSeconds": 10,
             "timeoutSeconds": 3}
    replicas = 0 if spec.get("stopped") else (1 if spec.get("mode") == "sleep" else int(resources.get("replicas", 1)))
    template_annotations = {"hirebuddha.com/restarted-at": spec.get("restartedAt") or ""}
    return {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": _meta(cr, name, {"annotations": {
            "hirebuddha.com/previous-images": json.dumps((spec.get("previousImages") or [])[-KEEP_IMAGES:])}}),
        "spec": {
            "replicas": replicas, "revisionHistoryLimit": KEEP_IMAGES,
            "selector": {"matchLabels": {"app.kubernetes.io/name": name}},
            "strategy": {"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}},
            "template": {
                "metadata": {"labels": labels(spec, name), "annotations": template_annotations},
                "spec": {
                    "serviceAccountName": name, "automountServiceAccountToken": False,
                    "enableServiceLinks": False,
                    "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
                    "containers": [{
                        "name": "app", "image": spec["image"], "imagePullPolicy": "IfNotPresent",
                        "ports": [{"name": "http", "containerPort": APP_PORT}], "env": env,
                        "resources": {"requests": {"cpu": cpu, "memory": memory},
                                      "limits": {"cpu": resources.get("cpuLimit", cpu), "memory": memory}},
                        "readinessProbe": probe, "livenessProbe": {**probe, "initialDelaySeconds": 10},
                        "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                            "capabilities": {"drop": ["ALL"]}},
                        "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
                    }],
                    "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "256Mi"}}],
                    "topologySpreadConstraints": [{"maxSkew": 1, "topologyKey": "kubernetes.io/hostname",
                                                   "whenUnsatisfiable": "ScheduleAnyway",
                                                   "labelSelector": {"matchLabels": {"app.kubernetes.io/name": name}}}],
                    **_placement(),
                },
            },
        },
    }


def service(cr: Dict[str, Any]) -> Dict[str, Any]:
    name = cr["metadata"]["name"]
    return {"apiVersion": "v1", "kind": "Service", "metadata": _meta(cr, name),
            "spec": {"selector": {"app.kubernetes.io/name": name},
                     "ports": [{"name": "http", "port": APP_PORT, "targetPort": APP_PORT}]}}


def service_account(cr: Dict[str, Any]) -> Dict[str, Any]:
    name = cr["metadata"]["name"]
    return {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": _meta(cr, name),
            "automountServiceAccountToken": False}


def network_policy(cr: Dict[str, Any]) -> Dict[str, Any]:
    """In: the tenant edge only. Out: the tenant's Data API, the egress proxy, DNS (§13.2)."""
    name = cr["metadata"]["name"]
    tenant = cr["spec"]["tenantKey"]
    dns = {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
                   "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}],
           "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}
    data_api = {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": f"t-{tenant}"}},
                        "podSelector": {"matchLabels": {"app.kubernetes.io/name": "data-api"}}}],
                "ports": [{"protocol": "TCP", "port": 8080}]}
    proxy = {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": EDGE_NAMESPACE}},
                     "podSelector": {"matchLabels": {"app.kubernetes.io/name": "egress-proxy"}}}],
             "ports": [{"protocol": "TCP", "port": EGRESS_PROXY_PORT}]}
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": _meta(cr, name),
            "spec": {"podSelector": {"matchLabels": {"app.kubernetes.io/name": name}},
                     "policyTypes": ["Ingress", "Egress"],
                     "ingress": [{"from": [{"namespaceSelector": {"matchLabels": {
                         "kubernetes.io/metadata.name": EDGE_NAMESPACE}},
                         "podSelector": {"matchLabels": {"app.kubernetes.io/name": "tenant-edge"}}}],
                         "ports": [{"protocol": "TCP", "port": APP_PORT}]}],
                     "egress": [dns, data_api] + ([proxy] if cr["spec"].get("egress") else [])}}


def disruption_budget(cr: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    resources = cr["spec"].get("resources") or {}
    if cr["spec"].get("mode") == "sleep" or int(resources.get("replicas", 1)) < 2:
        return None
    name = cr["metadata"]["name"]
    return {"apiVersion": "policy/v1", "kind": "PodDisruptionBudget", "metadata": _meta(cr, name),
            "spec": {"minAvailable": 1, "selector": {"matchLabels": {"app.kubernetes.io/name": name}}}}


def scaler(cr: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """KEDA's HTTP add-on: the app sleeps at zero replicas and wakes on a request."""
    spec = cr["spec"]
    if spec.get("mode") != "sleep" or spec.get("stopped"):
        return None
    name = cr["metadata"]["name"]
    return {"apiVersion": "http.keda.sh/v1alpha1", "kind": "HTTPScaledObject", "metadata": _meta(cr, name),
            "spec": {"hosts": list(spec.get("routes") or []),
                     "scaleTargetRef": {"name": name, "kind": "Deployment", "apiVersion": "apps/v1",
                                        "service": name, "port": APP_PORT},
                     "replicas": {"min": 0, "max": int((spec.get("resources") or {}).get("maxReplicas", 2))},
                     "scaledownPeriod": 900}}


def children(cr: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Everything one TenantApp owns, in the order to apply them."""
    out = [service_account(cr), deployment(cr), service(cr), network_policy(cr)]
    for optional in (disruption_budget(cr), scaler(cr)):
        if optional is not None:
            out.append(optional)
    return out


def upstream(cr: Dict[str, Any]) -> str:
    spec = cr["spec"]
    if spec.get("mode") == "sleep":   # through KEDA's interceptor, which wakes the app
        return "keda-add-ons-http-interceptor-proxy.keda.svc.cluster.local:8080"
    return f"{cr['metadata']['name']}.{cr['metadata']['namespace']}.svc.cluster.local:{APP_PORT}"


def edge_caddyfile(apps: List[Dict[str, Any]], *, ask_url: str, email: str = "") -> str:
    """The tenant app edge's whole configuration, from every running TenantApp's routes."""
    lines = ["{", f"    on_demand_tls {{\n        ask {ask_url}\n    }}"]
    if email:
        lines.append(f"    email {email}")
    lines += ["    storage redis {\n        address {$REDIS_ADDRESS}\n        password {$REDIS_PASSWORD}\n"
              "        tls_enabled true\n        key_prefix caddy\n    }", "}", ""]
    seen = set()
    for cr in sorted(apps, key=lambda c: (c["metadata"]["namespace"], c["metadata"]["name"])):
        spec = cr.get("spec") or {}
        if spec.get("stopped"):
            continue
        hosts = [h for h in spec.get("routes") or [] if h not in seen]
        if not hosts:
            continue
        seen.update(hosts)
        lines += [", ".join(f"https://{h}" for h in hosts) + " {", "    tls {\n        on_demand\n    }",
                  "    encode gzip zstd",
                  f"    reverse_proxy {upstream(cr)} {{\n        header_up X-Forwarded-Host {{host}}\n    }}",
                  "}", ""]
    lines += [":80 {", "    redir https://{host}{uri} 308", "}", ""]
    return "\n".join(lines)


def egress_allowlists(apps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The egress proxy's allow-lists for apps: ``{"t-<key>/app-<name>": [hosts]}``."""
    out: Dict[str, Any] = {}
    for cr in apps:
        spec = cr.get("spec") or {}
        if spec.get("egress"):
            out[f"t-{spec['tenantKey']}/app-{spec['app']}"] = sorted(set(spec["egress"]))
    return out


def status_of(deploy: Optional[Dict[str, Any]], cr: Dict[str, Any]) -> Dict[str, Any]:
    """The TenantApp's status from its Deployment: ready replicas, the image running, a phase."""
    spec = cr.get("spec") or {}
    if deploy is None:
        return {"phase": "Pending", "readyReplicas": 0}
    status = deploy.get("status") or {}
    ready = int(status.get("readyReplicas") or 0)
    wanted = int((deploy.get("spec") or {}).get("replicas") or 0)
    if spec.get("stopped"):
        phase = "Stopped"
    elif spec.get("mode") == "sleep" and wanted == 0:
        phase = "Sleeping"
    elif ready >= max(1, wanted):
        phase = "Running"
    else:
        failing = [c for c in status.get("conditions") or [] if c.get("type") == "Progressing"
                   and c.get("reason") == "ProgressDeadlineExceeded"]
        phase = "Failed" if failing else "Progressing"
    return {"phase": phase, "readyReplicas": ready, "image": spec.get("image"),
            "observedGeneration": (cr.get("metadata") or {}).get("generation")}

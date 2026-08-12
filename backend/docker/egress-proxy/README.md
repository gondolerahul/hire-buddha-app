# `hb-egress-proxy` — sandbox network gate (Phase 12 `02`/`06`)

A default-deny forward proxy (tinyproxy) that lets a per-tenant sandbox reach a
small **allow-list** of hosts without giving untrusted / synthesized tool code
the open internet. This is the network gate the `02` security review names as a
prerequisite for any network-granting canary, and the runtime backing of
`ToolSpec.network_policy == ALLOWLIST` (`06` §2).

## How it works

```
 sandbox container                      hb-egress-proxy                internet
┌──────────────────┐   HTTP(S)_PROXY   ┌────────────────┐  allow-list  ┌────────┐
│  on --internal   │──────────────────▶│ tinyproxy      │─────────────▶│ approved│
│  net (NO direct  │                   │ FilterDefault  │   (refused   │  hosts  │
│  internet route) │                   │ Deny=Yes       │    otherwise)└────────┘
└──────────────────┘                   └────────────────┘
       (dual-homed: also on the uplink bridge that has internet)
```

* The sandbox joins an **`--internal`** docker network — no route to the
  internet at all. Even if tool code ignores the proxy env, it has nowhere to go.
* The proxy is **dual-homed**: on the internal net (to receive sandbox traffic)
  *and* a normal uplink bridge (to reach approved hosts).
* `FilterDefaultDeny Yes` over the allow-list (built at start from `$ALLOWLIST`)
  means only allow-listed hosts are reachable; everything else is refused.

`EgressProxyManager` (`src/ai/tools/sandbox/egress_proxy.py`) ensures the
networks + proxy idempotently; `TenantSandboxManager.ensure(company_id,
egress=True)` joins a sandbox to the internal net with `HTTP(S)_PROXY` injected.

## Build

```bash
docker build -t hb-egress-proxy:local backend/docker/egress-proxy
# or: backend/docker/egress-proxy/build.sh
```

## Configure (env / settings)

| Setting | Default | Meaning |
|---|---|---|
| `SANDBOX_EGRESS_PROXY_ENABLED` | `false` | master switch for egress mode |
| `SANDBOX_EGRESS_IMAGE` | `hb-egress-proxy:local` | proxy image |
| `SANDBOX_EGRESS_NETWORK` | `hb-egress-internal` | the `--internal` sandbox net |
| `SANDBOX_EGRESS_UPLINK_NETWORK` | `hb-egress-uplink` | proxy's internet-facing net |
| `SANDBOX_EGRESS_PROXY_PORT` | `8888` | proxy port |
| `SANDBOX_EGRESS_ALLOWLIST` | `googleapis.com,google.com` | comma-separated host suffixes |

The allow-list is matched per host suffix (`googleapis.com` allows
`*.googleapis.com`). Change it without rebuilding — it's read from `$ALLOWLIST`
at container start.

## Verify

`tests/unit/test_egress_proxy.py` (hermetic, argv) +
`tests/integration/test_egress_proxy_docker.py` (Docker-gated): proves an
allow-listed host is reachable, a non-allow-listed host is refused, and the
internal network has no direct egress.

## Remaining ops before a prod network-granting canary

* image CVE scan + registry publish (same gate as `hb-sandbox`);
* per-company allow-lists (today one process-wide list) if tenants need
  different approved hosts.

# Security Review — `02` Per-Tenant Container Sandbox

> Release-gate artifact for [`plans/02_sandbox_browser_terminal.md`](./plans/02_sandbox_browser_terminal.md)
> §6. Reviews the `ContainerRuntime` / `TenantSandboxManager` / `hb-sandbox`
> attack surface before the canary flip. Pairs with the memory note
> `phase12-02-sandbox-container-runtime`.
>
> **Date:** 2026-06-08 · **Scope:** S3–S6 (image + runtime + manager + cost) ·
> **Status:** Accepted for dev/canary with the residual-risk items tracked below.

---

## 1. What is being secured

The sandbox runs **model-written and model-driven code** (the `sandbox_code`,
`terminal`, and — via `06`— synthesized tools) plus autonomous browsing. The
container substrate is what makes running untrusted code acceptable. The threat
actor is therefore **the code running inside the sandbox** (prompt-injected or
adversarial), trying to (a) escape to the host, (b) reach other tenants, (c)
exfiltrate data over the network, or (d) exhaust host resources.

Out of scope: the host control plane (API/worker authn), the LLM provider, and
the operator surfaces (Claude-in-Chrome / computer-use MCPs) — those are not the
tenant runtime.

---

## 2. Controls (implemented) vs. threats

All flags are applied at `docker run` by `TenantSandboxManager._create`
(`tools/sandbox/tenant_manager.py`); the image carries none of them.

| Threat | Control | Where |
|--------|---------|-------|
| Privilege escalation in-container | `--user 10001:10001` (non-root; image also `USER sandbox`), `--security-opt no-new-privileges` | manager + Dockerfile |
| Kernel attack surface / cap abuse | `--cap-drop ALL` (no added caps), no `--privileged`, no device mounts | manager |
| Host FS tampering | `--read-only` root FS; only the tenant dir + `/tmp` tmpfs are writable | manager |
| Writable-temp abuse | `--tmpfs /tmp:rw,exec,size=512m` (bounded, per-container) | manager |
| **Data exfiltration / SSRF** | `--network none` by default (default-deny) | manager (`SANDBOX_NETWORK`) |
| Cross-tenant access | one container per `company_id`; only `/tmp/sandbox/<company_id>` is mounted | manager (`_mounts`) |
| Resource exhaustion (CPU/mem/fork-bomb) | `--memory`, `--cpus`, `--pids-limit` | manager (tier-configurable) |
| Runaway exec | coreutils `timeout` **inside** the container (kills the real process, not just the client) | `ContainerRuntime.exec` |
| Secret leakage | no secrets injected by default; env is per-call and tool-built | tools pass explicit env only |
| Cost-amplification blindness | per-exec + per-session metering → `sandbox` attribution | S6 metering |

Defense-in-depth retained: the `terminal` regex blocklist and the
`headless_browser` URL-scheme block still run (they are no longer the security
*boundary*, but cheap extra layers).

Smoke-validated on the built image (uid=10001 confirmed; `touch /root/x` →
`Permission denied`; exec/timeout/network-deny covered by
`tests/integration/test_container_runtime_docker.py`).

---

## 3. Residual risks (accept-with-tracking)

1. **Bind-mount at the identical host path (S4 decision), not a private named
   volume.** The tenant dir lives under the host `/tmp/sandbox/<company_id>`,
   mounted into the container at the same path so tools need zero change. Risk:
   it is a host-FS directory, not an isolated volume; a host-side bug that
   mishandles `company_id` could cross tenants. *Mitigation:* `company_id` is a
   server-trusted UUID, never user input; one dir per company; the container only
   ever mounts its own. *Follow-up:* migrate to a per-tenant named volume at
   `/workspace` (routes tool IO through `runtime.write_file`).

2. **Shared docfactory dirs bind-mounted read-only at host paths.** Low risk
   (read-only, ships in-image too), but it is a host path visible in-container.
   *Follow-up:* drop the RO mount once tools read scripts from the in-image
   `/opt/docfactory/scripts` exclusively.

3. **Egress allow-list proxy — IMPLEMENTED + verified.** Default-deny
   (`--network none`) remains the default; for network-needing tools the
   `hb-egress-proxy` (`backend/docker/egress-proxy/`, tinyproxy with
   `FilterDefaultDeny`) is the gate. `EgressProxyManager` stands up an
   `--internal` sandbox network (no direct internet) plus a **dual-homed** proxy
   on an uplink bridge; `TenantSandboxManager.ensure(..., egress=True)` joins a
   sandbox to the internal net with `HTTP(S)_PROXY` injected. Verified
   end-to-end against real Docker (`tests/integration/test_egress_proxy_docker.py`):
   allow-listed host reachable, non-allow-listed host refused, no direct egress
   without the proxy. **Never** grant blanket `--network bridge`. *Remaining
   prod gate:* image CVE scan + registry publish; optional per-company
   allow-lists (today one process-wide `SANDBOX_EGRESS_ALLOWLIST`).

4. **Timeout kill is best-effort across the docker-exec boundary.** The
   in-container `timeout` covers the normal case; a process that ignores
   SIGTERM/SIGKILL or detaches is bounded only by `--pids-limit` + the reaper.
   *Accepted.*

5. **No image vulnerability scanning in the build path.** The 4.5GB image
   (LibreOffice, Chromium, ffmpeg) has a large CVE surface. *Follow-up:* add a
   `trivy`/`grype` scan to the publish step before any registry push; pin by
   digest (already enforced via `image.pin`).

6. **Idle/reaper policy is primitive** (`reap_exited` + caller-driven `pause`).
   Long-lived containers are a capacity/cost risk, not a security one.
   *Follow-up:* the S7 TTL reaper cron.

---

## 4. Pre-canary checklist

- [x] Non-root, cap-drop, no-new-privileges, read-only root, tmpfs `/tmp`.
- [x] Default-deny network.
- [x] Per-tenant isolation (one container + dir per company).
- [x] Resource limits (cpu/mem/pids) wired + tier-configurable.
- [x] In-container exec timeout.
- [x] Cost attribution (S6).
- [x] Docker-gated integration tests; CI stays Docker-free.
- [x] **Egress proxy** (`hb-egress-proxy` + `EgressProxyManager`) — implemented
      + Docker-verified (allow/deny/no-direct-egress). Enables `NetworkPolicy.ALLOWLIST`.
- [ ] **Image CVE scan** in the publish pipeline.
- [ ] Named `/workspace` volume migration (hardening, not blocking the keyless
      canary).

## 5. Sign-off

For the **dev / keyless environment** (flags flipped on by the operator, nothing
in production), the implemented controls are sufficient and this review is
**accepted** with items 3 (egress proxy) and 5 (CVE scan) as **hard gates before
any production canary that grants network** or pushes the image to a public
registry. This mirrors the Stage-0 telemetry-gate / C4 G4-soak policy: the
operational gates that cannot run in this environment are documented and deferred
to the human, not silently skipped.

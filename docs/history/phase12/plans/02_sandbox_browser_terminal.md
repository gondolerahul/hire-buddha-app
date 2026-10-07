# 02 — Robust Sandbox, Terminal & Headless Browser + Per-Tenant Persistent Containers

> Scope item 2. Today these three tools run as **ephemeral, in-host
> subprocesses**. They are functional but not isolation-grade, not persistent,
> and not safe enough to host the synthesized tools and autonomous code the
> Meta-Agent (`06`) will produce. This plan moves them onto a **persistent
> Docker container per tenant**, behind a single runtime abstraction.

---

## 1. Current state (audited)

| Tool | File | Model today | Gaps |
|------|------|-------------|------|
| `SandboxCodeTool` (`sandbox_code`) | `tools/sandbox_executor.py` (485) | `asyncio` subprocess; temp file; 30s timeout; stdout cap 4096; "no-network flag (best-effort, NOT guaranteed)" | runs as the host user; shares host FS/PID/network; no real isolation; ephemeral (no state between calls) |
| `TerminalTool` | `tools/terminal_tool.py` (459) | subprocess; regex command **blocklist**; `/tmp/sandbox/<company_id>` cwd; 30s/120s | blocklist is bypassable; minimal env but host kernel; no persistence |
| `HeadlessBrowserTool` | `tools/browser_tool.py` (457) | Playwright Chromium; **ephemeral context** (no cookies/state); URL scheme block; output cap 16k | no persistent session/login; no profile per tenant; runs in host; one browser per call |
| `provision_sandbox(...)` | `tools/sandbox_provision.py` (107) | symlinks shared dirs (Document Factory scripts) into `/tmp/sandbox/<company_id>` | host symlinks; tied to host FS |

**Core problems:**

1. **Isolation is advisory, not enforced.** A blocklist + "best-effort
   no-network" is not a security boundary. As the platform gains tool synthesis
   and autonomous terminal use, host-process execution is unacceptable.
2. **No persistence.** Every call is cold. An agent that `pip install`s a
   package, clones a repo, or logs into a site loses it next call. Real
   autonomous work (multi-step builds, authenticated browsing, data pipelines)
   needs a durable workspace.
3. **Three tools, three ad-hoc execution paths.** No shared runtime, lifecycle,
   or resource accounting.

---

## 2. Target architecture — one runtime, three tools

```
        ┌──────────────────────────────────────────────────────────┐
        │  ai/sandbox/  (new package — the runtime boundary)        │
        │                                                          │
        │   SandboxRuntime (Protocol)                              │
        │     ├─ exec(cmd, *, cwd, timeout, env) -> ExecResult     │
        │     ├─ write_file / read_file / list_dir                 │
        │     ├─ open_browser_session() -> BrowserSession          │
        │     └─ lifecycle: ensure(), pause(), resume(), destroy() │
        │                                                          │
        │   Implementations:                                       │
        │     • SubprocessRuntime   (today's behavior; default in  │
        │                            dev/CI; the rollback path)    │
        │     • ContainerRuntime    (Docker, persistent per tenant)│
        │                                                          │
        │   TenantSandboxManager                                   │
        │     - one container per (company_id[, persona])          │
        │     - idle-pause, TTL-reap, disk quota, image pinning    │
        └──────────────────────────────────────────────────────────┘
              ▲              ▲                    ▲
        sandbox_code   terminal           headless_browser
        (exec code)    (exec shell)       (browser session)
```

The three tools become **thin front-ends over `SandboxRuntime`**. They stop
owning subprocess/Playwright logic; they marshal args, call the runtime, and
shape output. This is also the layout move in `01` §5 (`tools/sandbox/`).

### 2.1 Why a Protocol with two implementations

* `SubprocessRuntime` = today's code, refactored behind the interface. It stays
  the **default for local dev, CI, and as the production rollback** if the
  container layer has an incident. Zero new infra to run tests.
* `ContainerRuntime` = the persistent-per-tenant Docker implementation, behind
  `sandbox.container_runtime_enabled` (default OFF; canary per company).

The agent code never knows which runtime it got. This is the same
flag-gated/reversible discipline that made Phase 11 safe.

---

## 3. Per-tenant persistent container — design

### 3.1 Lifecycle

```
first tool call for company C ─▶ TenantSandboxManager.ensure(C)
                                   ├─ container exists & healthy? → reuse
                                   ├─ exists & paused?           → resume (fast)
                                   └─ none?                      → create from pinned image,
                                                                    mount tenant volume, provision
idle > idle_ttl (e.g. 15 min)  ─▶ pause (stop, keep volume)
idle > reap_ttl (e.g. 24 h)    ─▶ stop container (volume persists)
volume unused > vol_ttl (e.g. 30 d) ─▶ archive/destroy (audit)
```

* **One container per `company_id`** (optionally per `(company_id, persona)` for
  strong workload separation — config-driven).
* **Persistent named volume** per tenant mounted at `/workspace` — survives
  pause/stop/recreate. This is the durable workspace: installed packages, cloned
  repos, browser profiles, intermediate artifacts.
* **Image pinning:** a single base image (`hb-sandbox:<digest>`) with Python,
  Node, Playwright + Chromium, ffmpeg (shared with `03`), and the Document
  Factory scripts baked in (replacing today's symlink provisioning). Pinned by
  digest; upgrades are deliberate.

### 3.2 Isolation & resource policy (per container)

| Control | Setting |
|---------|---------|
| User | non-root (`uid != 0`), no `--privileged`, `--cap-drop ALL` + minimal adds |
| Filesystem | tenant volume at `/workspace`; root FS read-only; `/tmp` tmpfs |
| Network | **default deny**, opt-in egress allow-list per tenant (DNS + domain allow-list via egress proxy); browser tool gets a broader but logged policy |
| CPU / memory | `--cpus`, `--memory`, `--pids-limit` from tenant tier |
| Disk | volume quota per tenant tier; enforced + monitored |
| Time | per-exec timeout (unchanged contract) + container wall-clock budget |
| Secrets | **none injected by default**; per-call scoped credentials only when an entity's IO contract declares them |

This replaces the regex blocklist (which stays only as defense-in-depth in
`SubprocessRuntime`). With kernel-enforced isolation, the blocklist is no longer
the security boundary.

### 3.3 Persistent browser sessions

The big browser win: a **persistent Chromium profile** in the tenant volume.

* `open_browser_session()` returns a `BrowserSession` backed by a
  user-data-dir under `/workspace/.browser/<persona>` — cookies, logins, and
  local storage persist across calls.
* Enables authenticated, multi-step web workflows (log in once, reuse) — today
  impossible with the ephemeral context.
* Connection model: run Chromium inside the container; the host's
  `HeadlessBrowserTool` talks to it over the Playwright server/CDP endpoint, or
  (cleaner) the browser actions execute *inside* the container via an in-image
  agent. Recommend **CDP-over-container-network** so Playwright orchestration
  stays in the host process while the browser + profile live in the tenant
  container.
* Keep all existing safety caps (URL scheme block, output cap, per-action
  timeout) and add per-tenant egress logging.

> The environment also exposes a Claude-in-Chrome MCP and a computer-use MCP.
> These are operator/dev surfaces, **not** the tenant runtime — do not couple
> the autonomous tenant browser to them. The tenant browser is the container
> Chromium described here.

---

## 4. How this unblocks tool synthesis (link to `06`)

The Meta-Agent's tool synthesis (`06` §2) **requires** this. Synthesized tool
code and the autonomous terminal/code tools all execute via
`ContainerRuntime.exec(...)` in the tenant container — never in-process, never
on the host. The container's default-deny network + non-root + read-only-root
posture is precisely the boundary that makes running model-written code
acceptable. `02` is therefore a hard dependency of `06` §2's tool-synthesis
canary.

---

## 5. Migration plan (reversible)

| Step | Work | Flag |
|------|------|------|
| S1 | Define `SandboxRuntime` Protocol + `ExecResult`/`BrowserSession` DTOs; refactor the 3 tools to call it | — |
| S2 | `SubprocessRuntime` = today's behavior behind the Protocol; all tests green, zero behavior change | — (default) |
| S3 | Build `hb-sandbox` base image (py/node/playwright/ffmpeg/docfactory scripts); pin by digest | — |
| S4 | `ContainerRuntime` + `TenantSandboxManager` (ensure/pause/resume/reap, volume, quotas, egress proxy) | `sandbox.container_runtime_enabled` (OFF) |
| S5 | Persistent browser profile via container Chromium + CDP | `sandbox.persistent_browser_enabled` (OFF) |
| S6 | Per-call resource/network accounting → CostLedger (attribution `SANDBOX`) | ties to `01` §6.3 |
| S7 | Canary one company; soak; then default ON; SubprocessRuntime stays as documented rollback | flip defaults |

Local dev and CI never need Docker — they ride `SubprocessRuntime`. Production
gets real isolation. Same image is reused by the video tool (`03`) for ffmpeg.

---

## 6. Operational concerns

* **Cold-start latency:** first call per idle tenant pays container
  create/resume. Mitigate with pause-not-stop for the active window, a small
  warm pool for high-traffic tenants, and surfacing "spinning up workspace…" in
  the SSE stream.
* **Capacity:** containers are long-lived → plan host fleet sizing by concurrent
  *active* tenants, not total tenants (idle ones are paused/stopped). Reaper TTLs
  are the main lever.
* **Security review:** the container escape surface, egress proxy, and secret
  handling need a dedicated security review before the canary flip (treat as a
  release gate, like `06` tool synthesis).
* **Observability:** per-tenant container metrics (CPU/mem/disk/egress), exec
  audit log, and a "destroy my workspace" admin action (GDPR/data-retention).
* **Determinism in tests:** keep `SubprocessRuntime` as the test runtime so the
  suite stays hermetic and Docker-free.

---

## 7. Exit criteria

* The three tools share one `SandboxRuntime`; no subprocess/Playwright logic
  left in the tool files themselves.
* `ContainerRuntime` runs one persistent, isolated, non-root, default-deny-net
  container per tenant with a durable `/workspace` volume; pause/resume/reap
  lifecycle works; quotas enforced.
* Persistent authenticated browser sessions work across calls.
* `SubprocessRuntime` remains the dev/CI default and the production rollback.
* Security review signed off; tool synthesis (`06` §2) executes exclusively in
  the container runtime.

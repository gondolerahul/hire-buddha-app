# Phase 12 — "What to Build Next" Checklist

> **Pairs with** [`HANDOFF.md`](./HANDOFF.md) (the entry point) and the eight
> [`plans/`](./plans/) files (the spec). This file sequences and prioritises the
> plan's own item IDs (C0–C13, S1–S7, V1–V6, K1–K7, P-*) by current state.
> **Last updated:** 2026-06-04 (Stage 1 COMPLETE — C4 Phase B + C2/C3/C13 landed)
> **Branch:** `phase12/stage1-consolidation`

Legend: ✅ done · ◐ partial · ❌ not started · 🚧 blocked by a hard gate

---

## 0. Current state in one paragraph

The repo is now the **GA shape** and **Stage 1 consolidation is COMPLETE.** On
top of the earlier cuts (`C0`–`C1`, `C3`-alias, `C5`–`C12`, `C10`/`C11`
de-prefix, lint→error), the keystone **`C4`** landed: the legacy
`ExecutionEngine.execute_run` plan-walker and `execution_engine.py` are deleted,
the **AgentLoop is the sole run engine**, and async suspend/resume is the only
child path (G4 soak dev-skipped by decision). Its fallout also landed: **`C2`**
(MemoryRouter retrieval body deleted, memory v2 unconditional), **`C3`-finish**
(engine MetaReviewer use gone), and **`C13`** (`engine_type` +
`RecursiveReasoningEngine` deleted; per-step reasoning routed via
`reasoning_hint`). All gates green. Remaining Phase-12 work is the new-capability
tracks: `02` (sandbox), `03` (video), `04` (CORTEX package), `06`'s v5
capabilities, `07` hardening — none started.

---

## 1. The critical path

- [x] **STAGE 0 — master switches ON** *(plan `05` §4, `08` Stage 0)* — done (dev
      mode; 30-day telemetry gate intentionally skipped). Parity gate wired + green.

- [x] **C4 — delete legacy `ExecutionEngine.execute_run`** *(`01` §4)* — **DONE.**
      Phase A evidence gate + the full Phase B deletion chain landed (G4 soak
      dev-skipped by decision, same policy as the Stage-0 telemetry gate). The
      AgentLoop is now the sole run engine. See
      [`designs/c4_replatforming_implementation_plan.md`](./designs/c4_replatforming_implementation_plan.md).
  - [x] **G1/G2/G3** parity + resumability chaos + cost guard (Phase A).
  - [x] **PR-5** extract `StepEngine`; **PR-6** async child dispatch is the loop's
        sole child path (+ parity candidate drainer-driven); **PR-7** re-platform
        `RecursiveExecutor` onto the planner; **PR-8** every entry point loop-only
        (arq dispatch, gateway dispatcher, `process_gateway_event`,
        `resume_execution`; dead `enqueue_job("execute_run")` repointed);
        **PR-9** delete `execute_run` + `execution_engine.py` + the child callback
        plumbing + the `agent_loop.enabled` switch.
  - `grep -rn 'execute_run\b' backend/src/ai` → comments/history only.

---

## 2. Stage 1 — consolidation (Track A)

### 2.1 Done
- [x] **C6 / P-F4** — REACT-AFC routes through `ToolResilience` (was already done).
- [~] **C8** — tools/ root-clean criterion satisfied; the `integrations/` wrapper +
      social audit remain deferred (low-value, high-churn).
- [x] **C9 (D-3)** — DebateExecutor + per-step `reasoning_hint`; retired
      REFLECTION/ToT (`d70912a`).
- [x] **C1** — v1 critic body + `v1_compat` flag deleted (`a10130e`).
- [x] **C3-partial** — `CortexRouter` alias removed (`7b946fb`). (The `MetaReviewer`
      half stays — `RealCriticPipeline` uses it — and is part of C4 fallout.)

### 2.2 De-prefix — DONE
- [x] **C10** — `ai/phase11_router.py` → `ai/api/admin.py` (`/api/v1/ai/admin/*`) +
      307 redirect shim in `main.py` (remove 2026-09-01); decision log →
      `docs/DECISIONS.md` (`7379d92`).
- [x] **C11** — 7 `P11*` component pairs + sub-components renamed;
      `types/phase11.ts`→`agentKernel.ts`; `Phase11KPI`→`KPIDashboard`; `p11-`→
      `agentk-` CSS; routes `/admin/agent-kernel/*` + redirect shim (`f9343b9`).
- [x] **Flip `CANARY_LABEL_MODE`→`error`** + neutralize remaining `ai/*.py` tokens
      (env prefix `AI_FLAG_`); raise `core/` cap to 1500; `test_layout_lint_passes`
      green (`98868d4`). Residual `phase11` = shims + migration names + `*.md` docs.

### 2.3 Quality lock-in (trailing)
- [x] **C12 — `mypy --strict` series** *(`01` §6.4, P-M1)* — **DONE: all six
      `ai/` packages strict-clean and gated** (`b17c803`, `996053b`, `4f60690`,
      `0c6aa5a`, `2c84a39`). `scripts/typecheck_ai.py` runs strict over the
      `CLEAN_PACKAGES` allowlist (now governance, orm, planning, meta, memory,
      core — **100 source files**) with `--follow-imports=silent`;
      `test_typecheck_passes` + the `run_ci_matrix.sh` fast lane gate it,
      `pyproject [tool.mypy]` sets the baseline. Per-package start counts: orm
      (migrated to `Mapped[]`), governance 32, planning 87, meta 74, memory 222
      (cortex_models.py also → `Mapped[]`), core 234. The **legacy-`Column` cost
      is GONE** — both `orm/` and `memory/cortex_models.py` are SQLAlchemy 2.0
      `Mapped[]` (DDL-identical, alembic-verified). **Convention:** new packages
      use real annotations + `cast()` for query-result/legacy reads;
      behaviour-preserving `# type: ignore` (not "fixes") on the C4-doomed legacy
      `ExecutionEngine` so parity goldens hold; lazily-built Optional services
      narrowed with `assert ... is not None` after their `_ensure`/`_compose`.
      **Latent bugs surfaced + fixed** along the way: `CriticCalibrator` missing
      `company_id`; meta `curator` anti-sprawl kwargs, `registry_search` missing
      `await` on async `db.get`, `platform_schema_compiler` wrong
      `IntegrationRegistry` columns; and a self-inflicted `child_entity`
      `UnboundLocalError` (inline `from uuid import UUID` shadowing) caught by the
      parity gate.
- [x] **C13 — drop deprecated `engine_type` & `reasoning_mode`** *(`01` §9, D-1)*
      — **DONE.** `engine_type`'s only consumer (`execute_run`'s RECURSIVE branch)
      died with C4; the orphaned `RecursiveReasoningEngine` was deleted (C13a).
      `step_executor` now reads per-step `PlanStep.reasoning_hint` (default REACT)
      instead of the entity-level `reasoning_config.reasoning_mode`; a PlanStep
      before-validator maps a legacy per-step `reasoning_mode` onto the hint
      (C13b). The ORM/`schemas/execution.py` run-telemetry `reasoning_mode` is
      retained.

### 2.4 Legacy deletions (fell out of C4 Phase B)
- [x] **C2** — deleted the `MemoryRouter` retrieval body (`retrieve` /
      `_load_episodic` / `format_for_prompt`) + the assembler v1 branch; v2 is now
      unconditional. `write_episodic` + `search_semantic` + `LegacyEpisodicReader`
      retained. (The loop reads CORTEX via the Perceiver with
      `memory_assembler=None`, so the legacy pipeline was fully dead.)
- [x] **C3 finish** — the engine `MetaReviewer` hook died with `execute_run`;
      `MetaReviewer` itself **stays** as `CriticPipeline.supervisor`'s
      `supervisor_v2_enabled=False` fallback (`critic_pipeline.py:489`).

---

## 3. Stage 2 — Tooling (Track C) — unblocks the marquee capability

`02` is a **hard dependency** of `06`'s tool synthesis.

- [x] **02 S1–S2 — `SandboxRuntime` Protocol + `SubprocessRuntime`** *(`02` §5)* —
      **DONE.** `tools/sandbox/runtime.py`: Protocol (exec/browser/file-ops/lifecycle)
      + `ExecResult`/`BrowserSession` DTOs + `SubprocessRuntime` (today's behavior)
      + `get_sandbox_runtime()` factory. The 3 tools delegate launch to it
      (zero behavior change; terminal/browser e2e green). Next: **S3** `hb-sandbox`
      image, **S4** `ContainerRuntime`/`TenantSandboxManager` (needs Docker + a
      security-review gate).
- [x] **02 S3–S4 — `hb-sandbox` image + `ContainerRuntime`/`TenantSandboxManager`**
      *(`02` §3)* — **DONE (code-complete, behind flag OFF).**
      **S3:** `backend/docker/sandbox/` — the `hb-sandbox` Dockerfile
      (Playwright-python base pinned to Playwright 1.58.0 + ffmpeg + LibreOffice
      + Document Factory libs/scripts, non-root, `/workspace` mount point) +
      `build.sh` (stages a minimal context, pins the digest to `image.pin`) +
      README. **S4:** `tools/sandbox/tenant_manager.py` (`TenantSandboxManager`:
      one container per company via the docker CLI; non-root / read-only-root /
      tmpfs-`/tmp` / `--cap-drop ALL` / `no-new-privileges` / `--network none` /
      cpu-mem-pids limits; the host `/tmp/sandbox/<company_id>` bind-mounted at
      the **identical path** so tools are unchanged + the workspace persists;
      pause/resume/destroy/reap) and `tools/sandbox/container_runtime.py`
      (`ContainerRuntime`: `docker exec` wrapped in coreutils `timeout`, host-side
      file ops over the bind-mount, browser sessions delegated to
      `SubprocessRuntime` until S5). `get_sandbox_runtime` selects it behind
      `settings.SANDBOX_CONTAINER_RUNTIME_ENABLED` / a `context["container_runtime"]`
      override / the `sandbox.container_runtime_enabled` flag (all default OFF),
      falling back to `SubprocessRuntime` on any error. Tests: hermetic unit
      (selection + exec mapping, mocked docker) + a Docker-gated integration suite
      (exec-in-container, bind-mount, network deny, in-container timeout,
      lifecycle) that skips without Docker. **Still required before canary:** the
      security review gate (`02` §6) + building/publishing the real image.
- [x] **02 S5 — persistent browser sessions** — **DONE (flag OFF).**
      `SubprocessRuntime.open_browser_session(user_data_dir=...)` uses
      `launch_persistent_context` so cookies/logins survive across calls;
      `resolve_persistent_browser_dir` layers the flag (context >
      `sandbox.persistent_browser_enabled` per-company > settings master) and
      roots the profile at `/tmp/sandbox/<company>/.browser/<persona>` (the
      bind-mounted path, consistent across runtimes). Real-Chromium persistence
      tests (gated on the binary).
- [x] **02 S6 — sandbox cost attribution** — **DONE.** New `sandbox`
      CostAttribution; `run_sandbox_exec` (the single metered exec entry point)
      + browser session metering bill duration→seconds against the
      `sandbox-runtime` SKU (cost_unit `second`, APP-owned; seed with
      `scripts/seed_sandbox_sku.py`). Unit + cost-attribution integration tests.
- [x] **02 per-company canary wiring** — `resolve_sandbox_runtime(context)`
      resolves `sandbox.container_runtime_enabled` per company and threads it
      into the tool context; all three tools route through it.
- [x] **02 §6 security review** — `docs/phase12/security_review_02_sandbox.md`
      (controls-vs-threats, residuals, pre-canary checklist). **Real `hb-sandbox`
      image built (4.52GB) + smoke-validated** via ContainerRuntime (python/node/
      pptxgenjs/ffmpeg/soffice/docfactory, non-root, read-only root). **Remaining
      prod gates:** egress proxy + image CVE scan before a network-granting prod
      canary; registry publish.
- [◐] **02 S7 — canary one company → default ON** — **egress proxy DONE**
      (`backend/docker/egress-proxy/` + `EgressProxyManager` +
      `TenantSandboxManager.ensure(egress=True)`; `--internal` net + dual-homed
      tinyproxy allow-list; Docker-verified allow/deny/no-direct-egress; backs
      `NetworkPolicy.ALLOWLIST`). **Remaining = ops:** image CVE scan + registry
      publish, then the per-company default-ON flip. *(ops)*
- [x] **03 V1–V6 — split `video_generation`** into `video_generate`/`video_edit`/
      `video_add_sound` *(`03` §4)* — **DONE.** Three composable tools under
      `tools/media/video/` over a shared `_ffmpeg.py` that routes every ffmpeg
      call through `run_sandbox_exec` (container-when-enabled, metered as
      compute). `video_generate` = single-segment generation (refuses >8s with a
      structured compose-hint); `video_edit` = concat/trim/resize/transition/
      overlay + an `extend` planning op (no model cost); `video_add_sound` =
      file/tts/generated audio mux+mix (tts/generated return structured
      provider-unavailable errors until a provider is wired). `video_generation`
      kept as a **DEPRECATED shim** composing the three (no seed references it;
      remove on the next release). Cost/latency/category maps updated; 22
      hermetic tests (ffmpeg faked); package `mypy --strict` clean.

---

## 4. Stage 2 — Meta-Agent v5 (Track B)

v4 board exists; the v5 capabilities are now built (code-complete behind
default-OFF flags; GA flips are in `OPS_REMAINDER.md`).

- [◐] **06 §3 — board GA on the AgentLoop + introspection tools** — introspection
      tools DONE (§3.1); board-on-AgentLoop re-platform + GA flip remain *(canary)*.
- [x] **06 §5 — intelligence → planner wiring + rule lifecycle** — **DONE.**
      `memory/rule_lifecycle.py` (pure candidate→confirmed→retired policy +
      `filter_for_prompt`); the Perceiver drops retired rules and, behind
      `memory.rule_lifecycle_confirmed_only` (OFF), injects confirmed-only (legacy
      lifecycle-less rules stay eligible). task_classifier v1-vs-v2 A/B remains an
      eval-harness run *(ops)*.
- [x] **06 §4 — close the learning loop** — **DONE.** §4.1 Curator consolidation
      merge-plans (`meta/consolidation.py`, propose-only + HITL, gated by
      `meta_agent.curator_consolidation_enabled`); §4.2 composition graph
      (`MetaIntelligenceTree.record_composition`/`query_compositions`); §4.3
      high-stakes third-model spec tiebreak (`meta/spec_tiebreak.py`,
      `meta_agent.spec_critic_tiebreak` OFF); §4.4 TestDriver goldens
      (`meta/board/golden_outcomes.py`).
- [x] **06 §6 — Meta-Agent self-modification** — **DONE.** §6.1 prompt-evolution
      LLM diff (`meta/prompt_evolution.py` critic-of-critic, wired into the
      `meta_agent_prompt_evolution` cron, HITL-gated); §6.3 version-aware reseed
      preserving evolved prompts (`meta/reseed_meta_agent.py`). §6.2 tool-set
      evolution is covered by the tool-synthesis need-detector + the
      prompt_update_candidate mechanism.
- [x] **06 §2 — TOOL SYNTHESIS (marquee)** — **DONE.** Full pipeline:
      `meta/board/tool_smith.py` (LLM writes the `Tool` subclass) →
      `meta/tool_validator.py` (AST gate) → `meta/tool_sandbox_tester.py`
      (container replay) → `meta/tool_red_team.py` (adversarial LLM) →
      `meta/tool_synthesis_pipeline.py` (DRAFT registration). Gated meta-tool
      `tools/meta/tool_synthesis.py` (EXPERIMENTAL visibility + `__is_meta_agent__`
      + `meta_agent.tool_synthesis_enabled` kill switch, OFF); `ToolStatus.DRAFT`
      added; runtime `SandboxedSynthesizedTool` execs only in the sandbox. 13 tests.
- [ ] **06 §3.1 — introspection tools** — **DONE.** `agent_introspect`
      (read-only budget/iteration/subgoals/rules/viewport snapshot) +
      `agent_reflect` (run-scoped + candidate CORTEX write); `resolve_meta_cognition`
      gains `self_introspection`/`reflection` matrix defaults; auto-injected in
      `step_executor`. 12 tests.
- [ ] **06 §3.2 — LLM-Strategist pilot** (Meta-Agent only). *(M)* — the eval
      harness (`07` §5) is now in place to A/B it vs deterministic.

---

## 5. Stage 3 — CORTEX extraction (Track D, parallel)

Phase 11 did Stage-A groundwork.

- [ ] **Stage A — Protocols in place** *(`04` §5)* — can start now. *(L)*
- [x] **Stage B — full code-move DONE** — gated on **C2** (done). The entire
      CORTEX engine lives in `backend/cortex_memory/` with **zero host imports**
      (package self-test enforces it): own `Base` + ORM (opaque FK-free external
      refs, dev-DB FK constraints dropped) + enums + DTOs + `schema.py`; the 4
      provider Protocols + reference impls + host adapters (`cortex_providers`);
      and **all services** — `service` (7 tree ops), `graph`, `ingestion`, the 4
      domain trees, `dreaming`, `assembly` — on injected providers. Host
      `src/ai/memory/` is now thin shims + the genuine adapters. Host alembic
      `target_metadata` includes the package metadata.
- [x] **Stage C — packaging DONE** (in-repo). `backend/cortex_memory/pyproject.toml`
      (PEP 621, name `cortex-memory`, Apache-2.0, dynamic version 0.1.0,
      `package-dir` flat-layout build) + `LICENSE`; a host-free test suite under
      `cortex_memory/tests/` (pure + DB-gated integration via the reference
      providers) at **85% coverage**; **`mypy --strict` clean** (23 files); CI
      (`.github/workflows/cortex-memory.yml`, pgvector service, mypy + coverage
      gate + wheel build); quickstart example. `python -m build` produces a clean
      `cortex_memory-0.1.0-py3-none-any.whl`. **Remaining = publish:** move to a
      public repo + `twine upload` to PyPI; then the host pins the version and
      drops the in-repo copy. **Track `04` is otherwise complete.**
- [ ] **Stage C — docs/coverage/CI → publish `cortex-memory` v0.1.0**. *(L)*
- [ ] Lock decisions K1–K7 (`04` §4). *(S)*

---

## 6. Stage 4 — Hardening / KPI / DX (Track E, trailing)

- [x] **07 §5 — A/B / eval harness** (`tests/eval/`) — **DONE.** `metrics.py`
      (pure: `aggregate` → `delta_report` with two-proportion z for rates +
      Welch's t for cost/latency, p via `math.erfc`, `render_report`), `runner.py`
      (`grade` + corpus replay via injected `run_fn`, DB-gated integration),
      `config.py` (`EvalConfig` flag bundles). Corpus = `tests/regression/cases`.
      14 hermetic tests.
- [x] **07 §1 — MCP tool adapter** — **DONE.** `tools/mcp/` — transport-agnostic
      `MCPClient` Protocol + `MCPToolAdapter` (read-only-first, per-company
      allow-list, `mcp` cost attribution, EXPERIMENTAL visibility) + `bind_mcp_server`.
- [x] **07 §3 — provenance trust-score learning** — **DONE.** `memory/trust_learning.py`
      (Beta-posterior learned trust over in-tenant source outcomes) +
      `source_trust_scores` table; flag `memory.trust_score_learning` (OFF).
- [x] **07 §2 — budget-aware REACT** — **DONE.** Budget pressure → step prompt
      (soft line + a "finish, don't expand" directive past
      `agent_loop.budget_pressure_threshold`=0.70) behind
      `agent_loop.budget_aware_react` (default ON); pure `budget_prompt_lines`.
- [ ] **P-O1** Grafana/Metabase panel JSON *(M)*.
- [x] **07 §6 smalls (partial)** — INTERNAL_KEYS reverse doc-rot guard +
      embedding-SSOT regression test **DONE**; CSAT capture, seed hygiene,
      SSE-narrative check remain.
- [ ] **P-O3** frontend Storybook / Lighthouse / Playwright *(M)*.

---

## 7. Recommended ordering from here

1. **Decide the C4 G4 soak** (run in prod, or dev-skip). It gates the highest-value
   remaining deletion + unblocks C2 and CORTEX Stage B.
2. While that's pending, do independent low-risk work: **C12 mypy --strict**
   (mechanical), or **`04` Stage A** (non-breaking Protocols), or **`02` S1–S2**
   (the sandbox refactor that unblocks tool synthesis).
3. After the soak: **C4 Phase B** (PR-5..PR-9) → **C2/C3 fallout** → **CORTEX
   Stage B**.
4. **06 board GA + tool synthesis** (the marquee, after `02` S4).

---

## 8. Quick status table

| Plan | Item | Status |
|------|------|:------:|
| 05 | Stage 0 master-switch flip (dev mode) | ✅ |
| 01 | C0 narration sweep + lint→error | ✅ |
| 01 | C1 critic v1 body deletion | ✅ |
| 01 | C3 CortexRouter alias removal | ✅ |
| 01 | C5 reconcile-v2 + static-as-prior (D-2) | ✅ |
| 01 | C6/P-F4 REACT ToolResilience | ✅ |
| 01 | C7 cost attribution + flag ON | ✅ |
| 01 | C8 tools/ root clean (integrations/ wrapper deferred) | ◐ |
| 01 | C9 DebateExecutor + retire REFLECTION/ToT (D-3) | ✅ |
| 01 | C10 backend de-prefix (`ai/api/admin`) | ✅ |
| 01 | C11 frontend de-prefix | ✅ |
| 01 | canary lint → error (de-canary) | ✅ |
| 01 | C4 Phase A evidence gate (G1/G2/G3) | ✅ |
| 01 | C4 Phase B (delete execute_run) — G4 soak dev-skipped | ✅ |
| 01 | C2 MemoryRouter retrieval delete + v2 unconditional | ✅ |
| 01 | C3 finish (engine MetaReviewer use gone) | ✅ |
| 01 | C12 mypy --strict (all 6 ai/ packages clean + gated) | ✅ |
| 01 | C13 drop deprecated engine_type/reasoning_mode | ✅ |
| 02 | Sandbox runtime S1–S2 (Protocol + SubprocessRuntime) | ✅ |
| 02 | Sandbox S3–S4 (hb-sandbox image + ContainerRuntime/manager, flag OFF) | ✅ |
| 02 | Sandbox S5 persistent browser (flag OFF) | ✅ |
| 02 | Sandbox S6 cost attribution (`sandbox` SKU) | ✅ |
| 02 | Sandbox per-company canary wiring + §6 security review + real image build | ✅ |
| 02 | Sandbox egress allow-list proxy (NetworkPolicy.ALLOWLIST) | ✅ |
| 02 | Sandbox S7 canary→default ON (remaining: CVE scan + publish) | ◐ |
| 03 | Video tool split (generate/edit/add_sound + deprecated shim) | ✅ |
| 04 | CORTEX package extraction | ❌ (A-groundwork ✅) |
| 06 | v4 board exists | ✅ |
| 06 | introspection tools (agent_introspect/agent_reflect) | ✅ |
| 06 | tool synthesis (ToolSpec + ToolValidator safety core) | ✅ |
| 06 | tool synthesis (ToolSmith LLM loop · red-team · DRAFT register) | ✅ |
| 06 | composition graph (§4.2) · curator consolidation (§4.1) | ✅ |
| 06 | spec tiebreak (§4.3) · TestDriver goldens (§4.4) | ✅ |
| 06 | rule lifecycle + confirmed-only planner gate (§5) | ✅ |
| 06 | prompt-evolution LLM diff (§6.1) · version-aware reseed (§6.3) | ✅ |
| 06 | board GA flip · LLM-Strategist pilot · task_classifier A/B | ◐ (canary/eval) |
| 07 | cost-attribution gate | ✅ |
| 07 | eval harness (tests/eval) | ✅ |
| 07 | budget-aware REACT | ✅ |
| 07 | INTERNAL_KEYS reverse guard + embedding SSOT test | ✅ |
| 07 | MCP adapter (§1) · trust-score learning (§3) | ✅ |
| 07 | CSAT capture (§6) · SSE narrative (§6) | ✅ |
| P-O1 | Phase 12 dashboards (CSAT/sandbox+MCP/synthesis/trust) | ✅ |

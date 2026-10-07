# 08 — Roadmap, Sequencing, Risk & KPIs

> Pulls the seven plan files into one schedule. Effort signals: **S** ≤2 days,
> **M** 3–5 days, **L** 1–2 weeks, **XL** >2 weeks. ~15 calendar weeks for a
> focused 2-engineer crew; CORTEX extraction runs as a parallel third track.

---

## 1. The dependency spine

```
Stage 0 ── canary flip + 30d telemetry watch  ──┐  (HARD GATE for all deletions)
                                                 │
   ┌──────────────────────┬──────────────────────┼───────────────────────┐
   ▼                      ▼                      ▼                       ▼
Track A: Consolidation  Track B: Meta-Agent   Track C: Tooling        Track D: CORTEX
(file 01, 05)           (file 06)             (files 02, 03)          (file 04)
   │                      │                      │                       │
   │  C4 (delete legacy)  │  board GA ──┐        │ 02 container ──┐      │ Stage A (decouple)
   │  needs Stage 0 ✔     │             │        │               │      │  can start early
   │                      │  tool synth ◀┴────────┴── 02 is a HARD dep   │ Stage B cutover
   │  reconcile-v2 (D-2)  │  (06 §2 needs 02 §4)                  │      │  needs 01 §4 ✔
   ▼                      ▼                                       ▼      ▼
            Track E: Hardening / KPI / DX (file 07, 01 §6 mypy)  ── trails everything
```

**Three hard ordering constraints:**

1. **No legacy deletion before Stage 0** (`05` §4) — the two master switches must
   be ON in prod with ≥30 days clean telemetry. Governs all of `01` §4 + C4.
2. **Tool synthesis (`06` §2) requires per-tenant containers (`02` §4)** — you
   cannot safely run model-written code in-process. `02` gates `06`'s marquee
   feature.
3. **CORTEX Stage B cutover requires `01` §4's MemoryRouter deletion** — extract
   the canonical layer, not the v1/v2 double-stack (`04` §5).

---

## 2. Week-by-week

### Stage 0 — Telemetry gate (weeks 1–2)

| Item | File | Effort |
|------|------|--------|
| Flip `agent_loop.enabled` ON, one company at a time; watch R-PRG-3/5/8 | 05 | M |
| Flip `meta_agent.board_routing` ON, one company at a time | 06 §9 | M |
| Verify `meta_cognition_migration` ran in all tenants | 06 §1 | S |
| Stand up the eval/parity corpus (prove loop≈legacy before C4) | 07 §5 | M |

**Exit:** both master switches ON in prod; 30-day clean-telemetry clock started;
parity corpus green.

### Stage 1 — Consolidation (weeks 2–5, Track A)

| Item | File | Effort |
|------|------|--------|
| C0 narration sweep + lint→error + canary-label rule | 01 §3 | S |
| C6 REACT-AFC `ToolResilience` inner closure | 01 §6.2 | M |
| C7 CostLedger attribution everywhere → `cost_attribution_required` ON | 01 §6.3, 07 §4 | M |
| C8 tools/ subgrouping + social audit + READMEs | 01 §5 | M |
| C5 `reconcile`→v2 + static-plan-as-prior (D-2) | 01 §6.1 | M |
| C9 reasoning-mode consolidation + DebateExecutor scaffold (D-3) | 01 §8.3 | M |
| **C1–C4 legacy deletions** (gated on 30-day clock) | 01 §4 | M–L |
| C10/C11 backend+frontend de-prefix + route shims | 01 §2,§7 | M |
| C12 `mypy --strict` series, C13 drop deprecated fields | 01 §6.4,§9 | M |

**Exit:** `01` §10 criteria — zero `p11/P11/phase11`, no legacy bodies, flags
pruned, mypy green, layout locked.

### Stage 2 — Meta-Agent v5 + Tooling (weeks 4–9, Tracks B & C, overlap Stage 1)

| Item | File | Effort |
|------|------|--------|
| 02 S1–S2 `SandboxRuntime` Protocol + `SubprocessRuntime` refactor | 02 §5 | M |
| 02 S3–S4 `hb-sandbox` image + `ContainerRuntime`/`TenantSandboxManager` | 02 §3 | XL |
| 02 S5 persistent browser sessions; S6 sandbox cost attribution | 02 §3.3 | L |
| 03 V1–V5 video tool split (`video_generate`/`video_edit`/`video_add_sound`) | 03 §4 | L |
| 06 board GA on AgentLoop + introspection tools | 06 §3 | L |
| 06 Curator consolidation ON + composition graph | 06 §4 | L |
| 06 intelligence→planner wiring + rule lifecycle | 06 §5 | M |
| 06 prompt-evolution LLM critic-of-critic + reseed | 06 §6 | L |
| 06 **tool synthesis** (needs 02 §4) — canary, HITL, container-only | 06 §2 | XL |
| 06 LLM-Strategist pilot (Meta-Agent only) | 06 §3.2 | M |

**Exit:** `06` §9 + `02` §7 + `03` §5 criteria.

### Stage 3 — CORTEX extraction (weeks 6–14, Track D, parallel)

| Item | File | Effort |
|------|------|--------|
| Stage A: Protocols + `cortex_bridge` implements them (in place) | 04 §5 | L |
| Stage B: package skeleton, move code, **gated on 01 §4**, 1-day cutover | 04 §5 | XL |
| Stage C: docs/examples/coverage/CI → **v0.1.0 on PyPI** | 04 §5 | L |
| Update `CORTEX_Implementation_Plan.md` §3/§4/§6/§19 | 04 §6 | S |

**Exit:** `04` §7 criteria.

### Stage 4 — Hardening / KPI / DX (weeks 12–15, Track E, trailing)

| Item | File | Effort |
|------|------|--------|
| MCP tool adapter (read-only, allow-list) | 07 §1 | L |
| Budget-aware REACT | 07 §2 | S |
| Provenance trust-score learning | 07 §3, 06 | M |
| A/B eval harness hardening | 07 §5 | M |
| Grafana/Metabase panel JSON (P-O1) | 05 §1.4 | M |
| CSAT, resumability test, INTERNAL_KEYS doc test, seed hygiene | 07 §6 | S each |
| Frontend polish (Storybook/Lighthouse/Playwright) | 01 §7 | M |

---

## 3. Risk register

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|:----------:|:------:|------------|
| R1 | C4 (delete legacy executor) regresses a workload the canary didn't cover | med | high | Parity corpus (07 §5) green before merge; staging soak; C4 only after full 30-day clock; no merge until ≥30d zero v1 traffic |
| R2 | Per-tenant containers add cost/ops burden that outweighs benefit | med | med | `SubprocessRuntime` stays default in dev/CI + prod rollback; canary one company; reaper TTLs control fleet size |
| R3 | Tool synthesis produces unsafe code | low | **high** | Container-only exec (cap-drop, non-root, default-deny net); AST static analysis + LLM red-team; HITL promotion; Meta-Agent-only; kill switch; security review gate |
| R4 | CORTEX cutover breaks production memory | low | high | Stage A is non-breaking; one controlled cutover; replay-identical smoke gate; do after 01 §4 so we extract clean code |
| R5 | De-prefix breaks external bookmarks / integrations | low | low | Route + redirect shims for one release with removal dates |
| R6 | Prompt self-evolution drifts the Meta-Agent | low | med | HITL approves every bump; audit rows; reseed preserves evolved prompts |
| R7 | Scope creep — "one more redesign" | med | med | Non-goals in `00` §4; AgentLoop is frozen as the kernel |
| R8 | Two master switches never reach clean 30-day telemetry (canary trips a risk) | med | high | Treat as signal, not blocker: fix the tripping subsystem (critic cost / false-pass / promotion reject) before proceeding; deletions simply wait |

---

## 4. KPIs & exit gates

Inherit the Phase 11 dashboard (`infra/dashboards/phase11/*.sql`). Phase 12
must **hold or beat** these across the cutover:

| KPI | P11 target | P12 gate |
|-----|-----------|----------|
| `goal_hit_rate` | ≥0.78 | ≥0.78 (no regression through C4) |
| `cost_per_success` | ≤0.85 | ≤0.85, with full attribution (no `UNATTRIBUTED`) |
| `false_pass_rate` | ≤0.10 | ≤0.10 |
| `critic_cost_share` | ≤0.25 | ≤0.25 |
| `budget_overshoot_rate` | ≤0.06 | ≤0.05 (budget-aware REACT, 07 §2) |
| `intelligence_rule_yield_per_run` | ≥1/5 | ≥1/run for Meta-Agent board (06) |

Phase-12-specific exit gates (the "done" definition):

* **De-canary:** `grep -rn 'p11\|P11\|phase11' backend/src frontend/src` empty;
  both master switches removed (behavior unconditional); flag count down ~6.
* **Legacy gone:** no `_review_step_output`/`MemoryRouter` body/`MetaReviewer`
  shim/`CortexRouter` alias/legacy `execute_run` in tree.
* **Quality locked:** `mypy --strict` on 5 kernel packages; `lint_ai_layout.py`
  green, no allow-list; cost attribution 100%.
* **Tooling:** 3 video tools; per-tenant container runtime live with
  `SubprocessRuntime` rollback; tool synthesis canary produced ≥1 promoted tool.
* **Meta-Agent:** board is the only path; composition graph + rule lifecycle +
  HITL prompt-evolution live.
* **CORTEX:** `cortex-memory` v0.1.0 on PyPI; host `memory/` is adapters only.

---

## 5. The minimal-path version (if only 6 weeks)

If the crew is small, do these in order for the most value per week:

1. **Stage 0** — flip the master switches; start the telemetry clock. *(Nothing
   else can finish without it.)*
2. **`01` §3/§5/§6 + C1–C3** — narration sweep, tools/ layout, deferred
   functional swaps, the low-risk legacy deletions. *(Pays down the canary debt;
   makes the codebase honest.)*
3. **`06` board GA + intelligence→planner + Curator** — the compounding
   capability lift, mostly a flip + wiring since the board is built.
4. **`02` S1–S4 + `06` tool synthesis canary** — the one true new capability,
   safely sandboxed.

`03` (video split) and `04` (CORTEX extraction) are valuable but independently
schedulable; defer them to the back half without blocking the above.

These four moves take the platform from "a tested canary build with a dormant
world-class Meta-Agent" to "a consolidated GA platform whose Meta-Agent learns,
synthesizes its own tools, and runs them in real isolation."

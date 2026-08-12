# 06 — Meta-Agent v5: the World's Best Agent-Designing Entity

> Scope item 6. Phase 11 shipped the **Architecture Board** (v4): seven roles,
> a Meta-Intelligence Tree, a Skill Library, spec-critic, a test-driver suite,
> and a DRAFT→ACTIVE promoter — all behind `meta_agent.board_routing` (OFF).
> Phase 12 takes the board to **GA** and then adds the three capabilities that
> separate a "good agent factory" from a *self-improving* one:
> **tool synthesis, a closed learning loop, and self-modification.**

The Meta-Agent is the highest-leverage component in the platform: a 10%
improvement here compounds across *every* agent it builds. This file is the
deepest of the Phase 12 plans for that reason.

---

## 1. Where v4 stands, and the per-level contract (D-1 made concrete)

The board exists in `meta/board/{requirement_chat,curator,architect,critic,validator,test_driver,promoter}.py`
with `meta/meta_intelligence_tree.py`, `meta/skill_library.py`,
`meta/anti_sprawl.py`, and the `meta_cognition_migration.py` opt-in flip. The
gates downstream of the master switch (`spec_critic_required`,
`draft_lifecycle`, `testdriver_suite_enabled`, `skill_promotion_cron`,
`prompt_evolution_cron`) are already ON. So **GA is a canary flip, not a build**
(§9).

Per **D-1**, the entity hierarchy survives but type now means *capability +
governance + reuse + meta-cognition defaults*. The Meta-Agent is the keeper of
that contract. The per-level meta-cognition matrix it must enforce when
authoring entities:

| Ability | ACTION | SKILL | AGENT | PROCESS |
|---------|:------:|:-----:|:-----:|:-------:|
| Platform awareness | off | off | **on** | **on** |
| Self-introspection (read budget/viewport/rules) | – | r/o | **on** | **on** |
| Registry search (delegate) | off | off | opt-in | **on** |
| Self-modification (create entities) | off | off | opt-in | opt-in |
| Reflection (write candidate rules) | – | run-scoped | **on** | **on** |
| Request HITL clarification | – | yes | yes | yes |
| Spawn child entity | – | – | – | **yes** |
| Propose skill promotion | – | – | yes | yes |
| Synthesize a tool | – | – | – | Meta-Agent only |

The single highest-value default change Phase 11 already made (and P12 keeps):
**`self_modification` and `registry_search` are opt-in, not auto-on for every
AGENT/PROCESS.** Only the Meta-Agent creates agents by default — this closes the
sprawl vector (review F-13/F-14). The `meta_cognition_migration.py` preserved
already-opted-in entities; verify the migration ran in all tenants before GA.

---

## 2. Capability A — **Tool Synthesis** (the marquee feature)

Today the Meta-Agent can *compose* existing tools but cannot *create* one.
Voyager/Devin can; this is the biggest single capability gap (review W8, gap
#6). It is also the natural partner to the per-tenant sandbox (`02`).

### 2.1 The pipeline

```
Need detected ──▶ ToolSpec ──▶ Synthesize ──▶ Sandbox test ──▶ Critic ──▶ Register (DRAFT)
   (Architect      (NL +        (LLM writes    (per-tenant     (red-team   (ToolRegistry
    or recurring    IO schema    a Tool         container,      + static    status=DRAFT,
    chain)          + examples)  subclass)      02 §4)          analysis)   trust=low)
```

* **Need detection.** Two sources: (a) the Architect, mid-build, declares "I
  need a tool that does X and none exists"; (b) the Skill Library promotion scan
  notices a repeated *tool-less* THOUGHT pattern that should be a tool.
* **ToolSpec** (new typed schema in `schemas/tools.py`): `name`, `description`,
  `input_schema` (JSON schema), `output_contract`, `examples[]`,
  `allowed_imports[]`, `network_policy`, `est_cost`.
* **Synthesize.** A new role `meta/board/tool_smith.py` + tool
  `tools/meta/tool_synthesis.py`. The LLM writes a `Tool` subclass body
  constrained to: the `Tool` base contract, an import allow-list, no filesystem
  access outside the sandbox workdir, and a declared `network_policy`.
* **Sandbox test.** The synthesized tool is executed in the **per-tenant
  persistent container** from `02` against its `examples[]`. This is why `02`
  and `06` are siblings: tool synthesis is unsafe without real sandboxing.
* **Critic + static analysis.** `ToolValidator`: AST scan (no `eval`/`exec`/
  `subprocess` outside policy, no secret access, import allow-list enforced),
  plus an LLM red-team ("how could this tool be abused or fail?").
* **Register as DRAFT.** New tools enter `ToolRegistry` with
  `status=DRAFT, trust=low`, visible only to the authoring company behind
  `tools.experimental.<id>` and **never** auto-available to other agents until a
  human promotes them. Promotion reuses the Promoter gate (§ board) + HITL.

### 2.2 Safety posture (non-negotiable)

Tool synthesis is the platform's most dangerous capability. Hard gates:

1. **Only the Meta-Agent (PROCESS, `is_meta_agent`)** may invoke
   `tool_synthesis`. Enforced at the tool-registry visibility layer.
2. **Synthesized code never runs in-process.** Execution is always inside the
   per-tenant container with the tenant's resource/network policy (`02`).
3. **No promotion without HITL** for the first N synthesized tools per company
   (configurable trust ramp). Auto-promotion only unlocks after a company hits a
   trust threshold (ties to the cross-tenant trust model, §8).
4. **Provenance + audit row** on every synthesized tool: who/why/when, the
   ToolSpec, the test results, the critic verdict.
5. **Kill switch:** `meta_agent.tool_synthesis_enabled` (default OFF in P12;
   canary per company).

### 2.3 Why this is the right time

The substrate is all present: the board can drive the multi-role pipeline, the
Skill Library detects repeated patterns, the per-tenant container (`02`) gives a
safe execution target, and `ToolStatus`/`get_visible_tools_for_company`
(shipped in T8) already gates visibility. Tool synthesis is the capstone that
ties them together.

---

## 3. Capability B — make the Meta-Agent *use its own AgentLoop*

Today the board roles are orchestrated by the Meta-Agent template's static plan
+ `meta_*` tools. That is fine for GA, but the symmetry the review called for
(blueprint §2.2) is powerful: **the Meta-Agent should run on the AgentLoop it
builds for everyone else.**

* Open subgoals = each board role's remaining work.
* The Strategist picks which role runs next (Architect↔Critic until satisfied;
  Validator; Test Driver; Promoter) — a graph, not a fixed chain.
* Reflections = what the Critic/Validator caught → Meta-Intelligence Tree.
* Skills = architecture moves that pass critic+validator first-try become
  reusable "design patterns" in the Skill Library.

**Plan:** once `agent_loop.enabled` is unconditional (Stage 0/`01`), re-platform
the Meta-Agent template so the board roles are *executors/strategist moves*
rather than static-plan steps. This is a refactor, not new behavior, and it
makes the Meta-Agent automatically inherit every loop improvement (budget
discipline, reflection persistence, resumability).

### 3.1 Introspection tools (closes review gap "no introspective tools")

Build the two opt-in meta-tools the review specified, available per the §1
matrix:

* `tools/meta/agent_introspect.py` — "what's my budget? current viewport node?
  which intelligence rules apply? what has this entity failed at in 7 days?"
* `tools/meta/agent_reflect.py` — persist a structured reflection into
  run-scoped state + entity IntelligenceTree (`status=candidate`).

These let any AGENT/PROCESS be introspective without engine-side magic, and the
Meta-Agent uses them heavily during board runs.

### 3.2 LLM-driven Strategist pilot (P-F7 partial)

The Strategist is deterministic today (explicit defer, DECISIONS 2026-05-28).
Pilot an **LLM Strategist** behind `agent_loop.llm_strategist_enabled` (default
OFF) **for the Meta-Agent only first** — it is the highest-value, most
controlled environment, and the board's typed `Move` schema (executor,
plan_fragment, expected_value, expected_cost, alternatives) is exactly the
calibrated-output contract the review prescribed. Compare against deterministic
on the board's own KPIs before considering wider rollout (full rollout = P13).

---

## 4. Capability C — close the learning loop (Critic ⇄ Curator ⇄ Intelligence)

The board *writes* to the Meta-Intelligence Tree; Phase 12 makes it *learn* from
it in a measurable loop.

### 4.1 Curator consolidation → ON (P-F8)

`meta_agent.curator_consolidation_enabled` is OFF. Turn it on (canary): the
Curator proposes **merge plans** for ≥5 near-duplicate entities
(combined similarity >0.9): winners/losers, re-point references, archive losers,
fork their intelligence rules into the winner. This converts anti-sprawl from
*block-only* into *consolidate* (review §9). Every merge requires HITL + audit.

### 4.2 Cross-entity composition graph (closes review gap #4)

Build the missing graph: "which AGENT/SKILLs have been composed into a PROCESS,
and what was the outcome?" Store as CORTEX edges in the Meta-Intelligence Tree
(`composed_with`, `outcome_score`). The Curator reads it to recommend proven
compositions over novel ones; the Architect reads it to avoid combinations that
historically fail. This is the substrate for "the platform learns which agents
work *together*."

### 4.3 Calibrated, different-model critic for high stakes (opt-in)

`critic_pipeline.different_model_critic` is ON for runtime critics. For the
**board's spec-critic**, add an opt-in *third-model tiebreak* for high-stakes
specs (PROCESS with >5 children, or cost projection near the governance
ceiling): if Architect and Critic disagree, a third model adjudicates. Default
OFF; enable per company. (Retrospective §6 theme.)

### 4.4 Test Driver → richer suite + golden outcomes

The suite (`test_driver.py`) runs smoke/comparative/boundary/regression/hostile.
P12 additions:

* **Golden-output capture:** when a human approves a DRAFT, snapshot its
  outputs as goldens; future ADAPTs regression-test against them.
* **Comparative against the live REUSE candidate** becomes mandatory when the
  Curator's top search hit scores >0.85 — don't create a near-duplicate that
  isn't measurably better.

---

## 5. Capability D — intelligence actually reaches the planner (closes gaps #1, P-F5, P-F7)

A subtle but critical gap: the loop *writes* candidate rules, but we must verify
they *flow back into decisions*.

* **Inject IntelligenceTree rules into the dynamic-planner prompt** (review §5
  quick-win #6; T7 plumbing exists — confirm it is wired post-`reconcile`-v2
  from `01` §6.1).
* **Task classification:** evaluate `task_classifier.v2_enabled` (embedding NN,
  P-F7). Run the v1-rules vs v2-embedding A/B on the eval harness (`07` §5);
  keep whichever wins per task family. Better task classes ⇒ better bandit arms
  ⇒ better plan-style priors.
* **Rule lifecycle:** enforce the `candidate → confirmed → retired` lifecycle on
  IntelligenceTree nodes (review noted it needs an explicit lifecycle). Dreaming
  validates candidates against subsequent runs before promotion to confirmed;
  confirmed rules that stop predicting get retired. Only `confirmed` rules enter
  planner/critic prompts by default.

---

## 6. Capability E — Meta-Agent self-modification (P-F1, P-F2)

This is what makes it "the world's best agent-designing entity": it improves its
*own* prompt and tool set, not just the agents it builds.

### 6.1 Prompt evolution with critic-of-critic (P-F2)

The cron `meta_agent_prompt_evolution` exists (HITL-gated) but the LLM diff
generation is stubbed. Build it:

1. Weekly, sample ~20 recent Meta-Agent board runs.
2. A *critic-of-critic* LLM (different model) reviews each: "what did the
   Meta-Agent itself do wrong — not the agents it built, the *board's* process?"
3. Aggregate into a `prompt_update_candidate` in the Meta-Intelligence Tree.
4. **HITL approves** → the template prompt bumps to v3.x.y with an audit row.

This is bounded, auditable self-improvement with a human in the loop — the safe
version of "the agent edits itself."

### 6.2 Tool-set evolution

When the prompt-evolution analysis (or the tool-synthesis need-detector)
repeatedly surfaces the same missing capability, the Meta-Agent proposes adding a
new *meta-tool* (e.g. "spec→test-suite generator"). HITL gates every new
meta-tool. Same MetaIntelligenceTree pipeline.

### 6.3 Template re-seed (P-F1)

Build `reseed_meta_agent.py` (deferred from T5-4): idempotent re-seed of the
Meta-Agent template per company, version-aware, that *preserves* per-company
prompt bumps from §6.1 (re-seed must not clobber an evolved prompt). Needs the
UI + content review the retrospective flagged — coordinate with the frontend
MetaIntelligencePage.

---

## 7. The board, end-to-end, after v5

```
RequirementChat ─▶ Curator ─┬─▶ (REUSE) ────────────────────────────────▶ done
   (clarify,       (search,  ├─▶ (ADAPT/COMPOSE/CREATE)
    emit Spec)      sprawl,   │      │
                    merge,    │      ▼
                    compose-  │   Architect ⇄ BoardCritic (diff model, until satisfied)
                    graph)    │      │            └─(needs tool)─▶ ToolSmith ─▶ sandbox(02) ─▶ ToolValidator ─▶ DRAFT tool
                              │      ▼
                              │   Validator (schema + static + cost + cycle)
                              │      ▼
                              │   TestDriver (smoke/comparative/boundary/regression/hostile + goldens)
                              │      ▼
                              │   Promoter (G1..G6 gates + HITL) ─▶ ACTIVE
                              ▼
                         Meta-Intelligence Tree  ◀── every role reads & writes
                         (anti-patterns, spec patterns, test-failure tags,
                          curator decisions, composition graph, tool reliability,
                          prompt-update candidates)
                              │
                         Dreaming validates candidate rules ─▶ confirmed
```

Running on the AgentLoop (§3): budget-disciplined, resumable, reflective.

---

## 8. Cross-tenant intelligence & trust (design only in P12)

Retrospective §6 themes: cross-tenant skill/intelligence sharing, provenance
trust-score learning, per-company trust-level auto-promotion.

Phase 12 produces a **design + privacy review**, not a build:

* **What could be shared:** anonymized architecture anti-patterns, tool
  reliability stats, plan-style priors — *never* tenant data, prompts, or
  outputs.
* **Trust model:** a per-company trust level (earned via successful runs, low
  reject rates) that governs (a) auto-promotion of skill candidates and
  synthesized tools, (b) eligibility to *contribute to* and *consume from* a
  shared anti-pattern pool.
* **Decision required:** product + legal sign-off before any cross-tenant flow.
  Build lands in P13 if approved.

Provenance trust-score *learning* (small, in-tenant, no privacy issue) can ship
in P12 — see `07` §3.

---

## 9. GA rollout & exit criteria

| Step | Action | Gate |
|------|--------|------|
| 1 | Verify `meta_cognition_migration` ran in all tenants | preserved opted-in entities; no agent silently lost `self_modification` |
| 2 | Flip `meta_agent.board_routing` ON, **one company at a time** | watch R-PRG-8 (promotion REJECT ≤30% / 7-day) |
| 3 | Re-platform board onto AgentLoop (§3) | parity with static-plan board on board KPIs |
| 4 | Curator consolidation ON (§4.1) | merges require HITL; audit rows present |
| 5 | Intelligence→planner wiring verified (§5) | confirmed rules appear in planner prompt |
| 6 | Prompt evolution LLM diff live (§6.1) | every bump HITL-approved + audited |
| 7 | Tool synthesis canary (§2) | only Meta-Agent; container-only exec; HITL promotion |

**Exit criteria:**

* `meta_agent.board_routing` default **ON**; board is the only Meta-Agent path.
* ≥1 Meta-Intelligence rule produced per board run in ≥80% of runs.
* Tool synthesis: ≥1 synthesized tool passes the full pipeline + HITL promotion
  in canary, executed only in the per-tenant container.
* Composition graph populated and read by Curator/Architect.
* Prompt-evolution produces ≥1 HITL-approved bump in canary.
* IntelligenceTree rule lifecycle (candidate→confirmed→retired) enforced; only
  confirmed rules enter prompts.

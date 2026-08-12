# Increment 1 / GOV — Governance Schema & Enforcement

> **Status:** Draft — for brainstorm review · **Branch:** `inc1/gov` · **Register findings:** B5 (design closed; this executes it). §20.4 budget envelopes are built in [04](./04_loop_env_runtime_budget.md).
> **Design authority:** technical doc §20.1–.3, .5, .6 (v3.0.2) + Blueprint §9 — restated in full below.
> **Depends on:** SIG only for the `trust` field the PolicyGate reads (build-able first with the field mocked). **Depended on by:** SCH (cross-owner-write checkpoint), LOOP+ENV (envelope ref), all of Increment 2.

---

## 1. Design (self-contained)

**Principle: deterministic policy before LLM judgment.** Blueprint §9's constructs stop being prose and become: a typed config schema, two small platform tables, a pure-function gate in front of the shipped Pre-Critic, and deploy-time checks in the shipped Board Validator. The authority matrix is **data, not prompt text** — an LLM cannot be talked out of a `BLOCK`.

### 1.1 Typed Governance Block

The existing `governance` JSON column on `hierarchical_entities` gains a **Pydantic-validated schema** (extends the shipped `ai/schemas/governance.py`) — no new entity columns:

```json
"governance": {
  "autonomy_level": "A1",
  "authority": { "payout_usd": 500, "refund_usd": 200, "discount_pct": 10, "contract_tcv_usd": 2000 },
  "sod_class": "maker | checker | auditor | none",
  "karuna_profile": true,
  "hitl_checkpoints": ["before_outbound_payout_above_band", "..."],
  "budget": { "envelope_ref": "..." },
  "memory_domains": ["general", "..."]
}
```

Writes that fail schema validation **fail the save** — governance config can no longer be silently malformed. Existing fields already consumed by the kernel (e.g. `max_concurrent_children`, breaker settings) are folded into the same schema, not duplicated. (`memory_domains` is consumed by SCH's viewport enforcement, [03 §1.6](./03_sch_tenant_schema.md).)

### 1.2 Checkpoint Registry

A platform table `hitl_checkpoint_defs` seeds the Blueprint's **18 checkpoints** (`key`, `category`, `description`, `default_threshold`, `platform_mandatory`). The shipped `human_approvals` table gains `checkpoint_key`. Tenants tune thresholds per entity in the governance block; `platform_mandatory` checkpoints (e.g. `before_self_evolving_code_promotion`) cannot be removed.

### 1.3 Runtime Enforcement — the PolicyGate

A deterministic, pure-function stage that runs **inside the shipped critic pipeline, before the LLM Pre-Critic**:

```
Act intent → PolicyGate(action_category, amount, counterparty_flags, signal_trust)
                 │ evaluated against: autonomy_level + authority bands + checkpoint defs + SoD class
                 ├─ PASS        → continue to LLM Pre-Critic (unchanged)
                 ├─ RAISE_HITL  → human_approvals row (checkpoint_key) + run PAUSED  (shipped flow)
                 └─ BLOCK       → step blocked; verdict on the StepHealthRecord      (shipped record)
```

Verdicts land on the existing `StepHealthRecord`, so critic calibration and learning see policy decisions for free. The gate also honors the SIG trust hook: runs triggered by a `counterparty`-trust signal may be refused high-impact tool categories outright (§18.6).

**Unset authority bands (decision 2026-07-19):** when an entity's `authority` block is absent, the PolicyGate **passes monetary actions through** until Increment 2 seeds real bands — checkpoint and SoD evaluation still apply. When Inc 2 seeds the Solo Pack governance defaults, every channel-facing entity must carry explicit bands (an Inc-2 seeding acceptance criterion, noted in its charter).

### 1.4 Deploy-Time Validators

The shipped Meta-Agent Board **Validator** (8 deterministic checks, `ai/meta/board/validator.py`) and the manual entity-publish path gain governance checks that **fail closed**:

1. **Karuna gate** — an entity with an external channel binding must carry `karuna_profile: true`.
2. **SoD conflicts** — declarative `sod_rules` seed data (the five Blueprint §9.4 rules: maker≠checker, vendor-create≠vendor-pay, access-granter≠access-user, auditor independence, self-modification quarantine) evaluated as pure functions over the entity graph.
3. **Autonomy caps** — a new entity cannot exceed its tier's default autonomy ceiling; raises route through the `before_autonomy_level_promotion` checkpoint.

### 1.5 Autonomy Transitions

`autonomy_level` changes **only** through checkpoint 17 (`before_autonomy_level_promotion`) — proposed by evidence, ratified by a human, recorded in `human_approvals`. SLO breaches auto-*propose* demotion through the same path (full demotion criteria: register C4, Increment 3).

## 2. Code Mapping

| Piece | Where | Notes |
|---|---|---|
| Typed schema | `ai/schemas/governance.py` | extend the existing Pydantic model; enforce on entity save in `ai/service.py` |
| Checkpoint defs | new `hitl_checkpoint_defs` table + seed migration | seed data = Blueprint §9.7's 18 checkpoints, checked in as reviewable fixture |
| Approval column | `ai/orm/execution.py` (`HumanApproval`, line ~121) | add `checkpoint_key`, nullable for legacy rows |
| PolicyGate | new `ai/governance/policy_gate.py` | pure functions, zero LLM/IO; inserted in `ai/planning/critic_pipeline.py` ahead of the pre-critic |
| SoD rules | seed data + pure-function evaluator in `ai/governance/` | wired into `ai/meta/board/validator.py` and the manual publish path |
| Verdict recording | existing `StepHealthRecord` flow in `ai/planning/` | new `FailureTag`/verdict source value for policy decisions |

## 3. Task Plan

| # | Task | Deliverable / acceptance |
|---|---|---|
| T1 | Typed governance block + save-time validation + backfill audit of existing entities' governance JSON | malformed governance write → 422; all existing dev entities validate (or get a fix-up data migration) |
| T2 | `hitl_checkpoint_defs` migration + 18-checkpoint seed + `human_approvals.checkpoint_key` | seed reviewed against Blueprint §9.7; mandatory checkpoints undeletable via API |
| T3 | PolicyGate pure functions + unit table-tests per rule (autonomy × authority × SoD × trust) | exhaustive decision-table tests; no LLM calls in the gate |
| T4 | Pipeline insertion + RAISE_HITL / BLOCK paths wired to shipped pause + StepHealthRecord | a run exceeding an authority band pauses with a card in the existing approvals panel — this is the exit-demo scene |
| T5 | Deploy-time validators (Karuna gate, SoD, autonomy caps) in Board Validator + manual publish | publishing a channel-bound entity without `karuna_profile` fails closed, with a clear error |
| T6 | Parity golden re-capture for the new pipeline stage | goldens re-recorded **deliberately** in their own commit with a diff review; eval harness delta clean |

## 4. Testing Notes

The PolicyGate is the one Increment-1 change inside the AgentLoop's stage contract's blast radius. Rule: land T3 (pure functions, fully tested) before T4 (insertion), and treat any unexpected parity-golden drift as a defect, not noise. PASS-path behavior with default governance blocks must be a no-op — verified by running the parity suite with the gate enabled and unconfigured entities.

## 5. Brainstorm Decisions (Rahul, 2026-07-19)

1. **The 18-checkpoint seed list** — agreed: extracted from Blueprint §9.7 into the T2 fixture, reviewed in the PR.
2. **Authority bands for unset entities** — **pass-through until Inc 2 seeds real bands** (folded into §1.3 above); Inc 2's Solo Pack seeding must leave no channel-facing entity without explicit bands.
3. **`sod_class` on existing entities** — backfill `none` everywhere; real classes assigned when the Solo Pack agents are seeded in Inc 2.

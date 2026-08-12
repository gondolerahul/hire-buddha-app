# Increment 1 / LOOP+ENV — Loop Runtime Lite, Budget Envelopes & Wallet Holds

> **Status:** Draft — for brainstorm review · **Branch:** `inc1/loop-env` · **Register findings:** B1, A6, E3 (designs closed; this executes them)
> **Design authority:** technical doc §17, §20.4, §23.3 (v3.0.5) — restated in full below.
> **Depends on:** SIG (schedule/incident signals, parked-sweep), GOV (governance block's `budget.envelope_ref`). Merges last of the four workstreams.

---

## 1. Design (self-contained)

**Principle: a Loop is a scheduler and an aggregator — never a run.** The shipped AgentLoop's run-based model is untouched. The LOOP tier is a thin standing layer built from shipped machinery: Arq cron, CORTEX, cost attribution.

### 1.1 The LOOP Tier

A `LOOP` row in `hierarchical_entities` (`type="LOOP"`). **One root Loop per tenant — Sheel** — enforced by a partial unique index on `(company_id) WHERE type='LOOP' AND parent_id IS NULL`. A Loop never gets an `execution_runs` row. All Loop *cognition* (an executive briefing, a budget reallocation proposal) is dispatched as ordinary AGENT/PROCESS runs — every LLM call the Loop causes flows through the existing run engine, billing, and governance without exception.

**Federation is first-class (§17.6):** a LOOP row may parent LOOP rows. Rules: exactly one root per tenant; only a LOOP may parent a LOOP (deploy-time validation alongside GOV's checks); every Loop gets its own heartbeat, trigger subscriptions, and envelope; a parent's heartbeat rolls up child-Loop stats exactly as it rolls up Processes; memory/policy flow down, KPIs/risk aggregate up, nothing sideways. Only the validation rule and index ship this increment — actual child-Loop topologies are Increment 7.

### 1.2 Heartbeat & State

A per-tenant **heartbeat job** (Arq cron, default every 120s, configurable) performs four deterministic steps:

1. **Dispatch due schedules** — evaluate `loop_config.schedules` and emit `schedule.*` signals (SIG) with the schedule slot as `dedupe_key` — a double-fired heartbeat cannot double-run a Process.
2. **Sweep parked signals** — re-evaluate `PARKED` signals whose review timer expired.
3. **Roll up** — aggregate child Process costs (from the shipped cost-attribution ledger) and KPI inputs into `loop_runtime.stats` and the Loop's CORTEX tree; refresh envelope `spent_usd` (§1.4).
4. **Stamp** `last_beat_at`.

```python
class LoopRuntime(Base):
    __tablename__ = "loop_runtime"
    loop_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hierarchical_entities.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    heartbeat_interval_s: Mapped[int] = mapped_column(default=120)
    last_beat_at: Mapped[datetime | None]
    consecutive_missed: Mapped[int] = mapped_column(default=0)
    stats: Mapped[Any] = mapped_column(JSON)   # rolling KPI/cost aggregates per process/arc
```

Long-horizon memory is the Loop's **CORTEX tree** (shipped auto-checkpointing + Dreaming already solve months-scale compaction). There is no `AgentState` snapshot for a Loop — nothing to suspend or resume; a crashed heartbeat simply fires again.

**Supervision:** a platform watchdog cron flags any Loop whose `last_beat_at` is older than 3 intervals: `consecutive_missed` increments, an `incident.platform` signal is emitted, ops is alerted. Recovery is re-enqueueing the heartbeat — safe because of the dedupe keys.

**Billing:** Loops create no runs, so **no LOOP minimum-wallet threshold exists — by design**. The heartbeat is deterministic code billed as a flat platform-overhead SKU (≈ zero); every dollar of real spend occurs in child runs at existing thresholds.

**Lifecycle:** entity `status` carries `ACTIVE | PAUSED | ARCHIVED`. Pausing stops schedule dispatch and signal claiming, but protected processes (P14/P17) keep running from their reserved envelope.

### 1.3 Budget Envelopes & the Protected Reserve (§20.4)

```python
class BudgetEnvelope(Base):
    __tablename__ = "budget_envelopes"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hierarchical_entities.id"))  # LOOP or PROCESS
    cycle: Mapped[str]                        # monthly | weekly
    envelope_usd: Mapped[Decimal]
    reserved_usd: Mapped[Decimal] = mapped_column(default=0)   # protected carve-out (P14/P17)
    spent_usd: Mapped[Decimal] = mapped_column(default=0)      # rolled up from cost attribution
    downshift_at_pct: Mapped[int] = mapped_column(default=80)
    refreshed_at: Mapped[datetime]
```

The heartbeat refreshes envelopes on cycle and rolls up `spent_usd`. At `downshift_at_pct` → a notification signal to the owner; at 100% → the Loop stops dispatching that Process's non-critical signals (**they park, not drop**). **The protected reserve:** P14/P17 are "never paused" because their share is carved out as `reserved_usd` at cycle refresh — **pre-funded, not exempt**. The platform's hard wallet floor (`InsufficientCreditsError`) is unchanged: a truly empty wallet stops protected processes too and triggers emergency HITL + dunning (degraded mode: register C5, Increment 2). No free execution exists.

### 1.4 Wallet Holds & Settlement (§23.3, closes the E3 race)

```python
class WalletHold(Base):
    __tablename__ = "wallet_holds"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("execution_runs.id"), unique=True)
    amount_held: Mapped[Decimal]           # planner estimate, floored at the tier minimum threshold
    amount_spent: Mapped[Decimal] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(default="ACTIVE")   # ACTIVE | SETTLED | EXHAUSTED
```

* **Admission:** a run starts by placing a hold = the shipped planner cost estimate (floored at the §14.3 tier minimum), debited from *available* balance in one short `SELECT … FOR UPDATE` transaction on the wallet row — concurrent runs can no longer oversubscribe the same dollar.
* **During the run:** steps consume against the hold; at 80% consumed the run tops the hold up from the wallet (or the envelope downshifts it). Envelopes and holds compose: the envelope answers *"may this Process spend?"*, the hold answers *"is the cash actually set aside?"*.
* **Mid-run exhaustion — graceful finish, bounded debt:** the run completes its current step cleanly (a live call is never dropped mid-sentence), then suspends (`PAUSED`, reason `insufficient_funds`) and notifies the owner. Overage is capped at **max($1, 5% of the hold)**, recorded as `wallet_debt`, settled from the next top-up before any new spending. Protected processes draw from `reserved_usd` before this path triggers.
* **Settlement:** run finalize releases the residual hold and writes actuals to cost attribution as today.

## 2. Code Mapping

| Piece | Where | Notes |
|---|---|---|
| `LOOP` enum + root index | `ai/schemas/enums.py` (`EntityType`, line ~27) + migration | partial unique index; parent-of-LOOP validation joins GOV's deploy checks |
| New package | `backend/src/ai/loop/` | `models.py` (`LoopRuntime`), `heartbeat.py`, `watchdog.py`, `schedules.py`, README |
| Crons | `ai/worker.py` | heartbeat (single scanning cron over active `loop_runtime` rows — see Q1) + watchdog; follows the existing cron-registration block |
| Envelopes | `budget_envelopes` migration + `ai/loop/envelopes.py` | refresh/rollup from `ai/services/cost_attribution.py` + `usage_logs`; downshift → SIG notification signal |
| Wallet holds | `wallet_holds` migration + `billing/credit_service.py` | hold placement/top-up/settlement; `wallet_debt` on `CreditWallet` (`billing/billing_models.py` line ~46) |
| Admission seam | where runs are admitted today (`InsufficientCreditsError` path in `billing/credit_service.py` / run start in `ai/service.py`) | hold replaces the bare threshold check; same exception surface |
| Exhaustion path | `ai/core/agent_loop.py` budget handling (`ai/core/budget.py`) | finish-current-step → `PAUSED(insufficient_funds)` → owner notification signal |
| Sheel seeding | data migration | one Sheel LOOP row + `loop_runtime` + default envelope per existing dev tenant (see overview Q3) |

## 3. Task Plan

| # | Task | Deliverable / acceptance |
|---|---|---|
| T1 | `LOOP` enum + root partial index + parent-of-LOOP validation + Sheel data migration | second root Loop insert fails at the DB; Sheel exists for dev tenants |
| T2 | `loop_runtime` + heartbeat steps 2–4 (parked sweep, rollup, stamp) | heartbeat run visibly updates `stats` + `last_beat_at`; cost rollup matches the attribution ledger |
| T3 | Schedule dispatch (step 1): `loop_config.schedules` → `schedule.*` signals with slot dedupe keys | double-fired heartbeat emits one signal per slot; schedule → trigger → Process run end-to-end |
| T4 | Watchdog cron + `incident.platform` emission | stalled heartbeat detected within 3 intervals in a clock-controlled test |
| T5 | `budget_envelopes` + cycle refresh + reserve carve-out + downshift/park-at-100% | exhausted envelope parks non-critical signals; P14/P17-class reserved spend continues; A6 semantics tested |
| T6 | `wallet_holds` + admission under `FOR UPDATE` + top-up + settlement | **exit-demo scene:** two concurrent runs against a wallet that can fund one → exactly one admitted; chaos test: crash after admission leaks no hold (sweeper releases orphans) |
| T7 | Graceful finish + bounded debt + `wallet_debt` settle-first on top-up | mid-run exhaustion pauses after step completion; debt ≤ max($1, 5% of hold); next top-up settles debt first |
| T8 | Cost-amplification + parity gates green; billing docs updated (`docs/current/billing_rates_by_primitive.md` heartbeat SKU) | no run-engine behavior change outside admission/exhaustion paths |

## 4. Testing Notes

The wallet-hold work touches the platform's most sensitive invariant (money). Reuse the existing cost-amplification chaos tests and add hold-specific ones: admission race (two workers), orphaned-hold recovery, debt cap boundary values, and the composition case (envelope allows, wallet can't fund → deny; wallet funds, envelope exhausted → park). All `Decimal`, never float — matching `billing/` conventions.

## 5. Brainstorm Decisions (Rahul, 2026-07-19)

1. **Heartbeat topology** — accepted: one platform cron scanning `loop_runtime` rows whose interval has elapsed, until fleet scale (B14, Inc 7). **Keep it simple but configurable:** the scan interval is a platform config setting (default 60s), and per-Loop pacing stays in `loop_runtime.heartbeat_interval_s` — no per-tenant cron registrations.
2. **Default envelope** — **one uniform, configurable platform default** (single config value applied to every tenant, per-tenant override via API; no per-tier defaults in Inc 1). Placeholder value $100/month, reserve 10%, until the E1 idle-cost model (Inc 2) derives real numbers.
3. **Hold sizing** — accepted: hold = max(planner estimate, tier minimum), capped per tier (PROCESS $5) so a wild estimate can't lock the whole wallet.

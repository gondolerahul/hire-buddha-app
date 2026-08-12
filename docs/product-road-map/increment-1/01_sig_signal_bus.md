# Increment 1 / SIG — Signal Bus & Trigger Registry

> **Status:** Draft — for brainstorm review · **Branch:** `inc1/sig` · **Register findings:** B2 (design closed; this executes it)
> **Design authority:** technical doc §18 (v3.0.2) + Blueprint §3.3 — restated in full below.
> **Depends on:** nothing unbuilt. **Depended on by:** SCH (proposal/conflict signals), LOOP+ENV (schedule signals), everything in Increment 2.

---

## 1. Design (self-contained)

**Principle: Postgres is the bus.** Signals are transactional rows (outbox pattern) claimed with `FOR UPDATE SKIP LOCKED`; Arq is the delivery muscle. No new infrastructure — the same Postgres + Redis/Arq pair the platform already runs.

### 1.1 Schema

```python
class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    source: Mapped[str]        # karuna_gateway | connector | telemetry | schedule | agent | human
    type: Mapped[str]          # dotted taxonomy: "lead.inbound", "payment.failed", "incident.security"
    urgency: Mapped[str] = mapped_column(default="normal")   # low | normal | high | critical
    confidence: Mapped[float] = mapped_column(default=1.0)
    trust: Mapped[str]         # counterparty | external_verified | internal | platform
    object_refs: Mapped[Any] = mapped_column(JSON)           # canonical record ids (SCH §19)
    payload: Mapped[Any] = mapped_column(JSON)
    dedupe_key: Mapped[str | None]        # unique partial index (company_id, dedupe_key)
    status: Mapped[str] = mapped_column(default="PENDING")   # PENDING | CONSUMED | PARKED | ESCALATED | DEAD
    owner_process_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hierarchical_entities.id"))
    consumed_by_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("execution_runs.id"))
    park_review_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(default=0)
    replayed_from: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None]

class TriggerRegistration(Base):
    """Which Process owns which signal types (Blueprint §3.3's registry)."""
    __tablename__ = "trigger_registry"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    process_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hierarchical_entities.id"))
    type_pattern: Mapped[str]             # exact type or prefix glob: "lead.*"
    priority: Mapped[int] = mapped_column(default=100)
    enabled: Mapped[bool] = mapped_column(default=True)
```

Both tables live in the **control plane** (master DB) — settled in §23.4: billing attribution and the SKIP-LOCKED dispatcher need one operational store; tenant portability of business events is served by the export API.

### 1.2 Producing (outbox pattern)

Producers insert the signal row **in the same DB transaction as the business write**, then enqueue `dispatch_signal(id)` after commit. A periodic **sweeper** re-enqueues any `PENDING` signal older than one sweep interval — covering a crash between commit and enqueue. This is what makes "**no dropped signals**" an auditable property rather than a slogan.

Producers (this increment and later): gateway webhooks (this increment), the Loop heartbeat's schedule signals (04), the record service's `object.change_proposed` / `object.write_conflict` (03), Karuna gateways (Inc 2), connectors (Inc 4), agents via SKL-X01 (Inc 2), humans via UI actions (Inc 2).

### 1.3 Dispatching

The dispatcher claims with `SELECT … WHERE status='PENDING' FOR UPDATE SKIP LOCKED` (safe under concurrent Arq workers), resolves the **single owning Process** from `trigger_registry` — best match by priority, deterministic tiebreak: priority DESC then entity id ("exactly one owner" made mechanical) — spawns an ordinary Process run with the signal in `input_data`, and marks `CONSUMED` + `consumed_by_run_id`. `urgency="critical"` signals are claimed ahead of the queue.

* **No matching trigger** → `PARKED` with a `park_review_at` timer; parked past its SLA → `ESCALATED` (HITL card via the existing `human_approvals` flow).
* **Dispatch failure** → `attempts += 1`, exponential backoff; past `max_attempts` (default 5) → `DEAD` + an `incident.governance` signal + ops alert. Every terminal state is visible.

### 1.4 Delivery Semantics (explicit)

* **At-least-once delivery, idempotent consumption:** PENDING→CONSUMED is atomic; the spawned run records `signal_id`, so a re-delivered signal cannot spawn a second run.
* **Deduplication:** unique partial index on `(company_id, dedupe_key)`; producers set `dedupe_key` from the external event id (webhook id, message SID, schedule slot).
* **Ordering:** best-effort FIFO per company (`created_at`); **no global ordering guarantee** — object state (03) is the source of truth; signals are triggers, not state.
* **Replay:** signals are immutable; replay inserts a clone with `replayed_from` set.

### 1.5 Completion & Audit

Run finalization in the AgentLoop (the same seam that already fires the Dreaming outcome trigger) emits `<type>.completed` for the consumed signal. The Blueprint's Arc-VI **signal-coverage KPI** becomes one SQL query over `signals.status` — % of signals neither PENDING nor PARKED beyond SLA.

### 1.6 Trust Hook (down-payment on register D3)

`trust` is stamped by the producer (`counterparty` for anything ingested from the outside world). The GOV PolicyGate may refuse high-impact tool categories on runs whose triggering signal is counterparty-trust. Full taint tracking stays open (D3, Increment 6).

## 2. Code Mapping

| Piece | Where | Notes |
|---|---|---|
| New package | `backend/src/ai/signals/` | `models.py`, `service.py` (emit API), `dispatcher.py` (Arq job), `sweeper.py`, `README.md`; `mypy --strict` |
| Migration | `backend/migrations/versions/` | `signals` + `trigger_registry` + indexes (incl. the dedupe partial unique + `(company_id, status, created_at)` claim index) |
| Emit API | `ai/signals/service.py` | `emit(session, …)` inserts in the caller's transaction; enqueue-after-commit helper mirrors existing post-commit hooks |
| Arq wiring | `ai/worker.py` | register `dispatch_signal` job + sweeper cron (existing cron registration block, `ai/worker.py` ~line 83) |
| Run spawn | reuse the existing run-creation path in `ai/service.py` / `ai/core/arq_jobs.py` | the dispatcher must not invent a second way to start runs |
| Completion hook | `ai/core/agent_loop.py` run-finalization seam | emit `<type>.completed` when the run carries a `signal_id` |
| First channel producer | the inbound **email ingest** path (`ai/email_router.py` + IMAP ingest service) | ingested inbound email emits `email.inbound` with `dedupe_key` = RFC Message-ID (decision 2026-07-19); the gateway webhook dispatcher (`gateway/dispatcher.py`) follows the same emit pattern in Inc 2 for the remaining channels |
| HITL escalation | existing `human_approvals` (`ai/orm/execution.py`) | ESCALATED signals raise an approval row; no new UI |
| Trigger CRUD | small internal router (API-only per the Inc-1 frontend decision) | list/create/enable/disable registrations; admin-scoped |

## 3. Task Plan

| # | Task | Deliverable / acceptance |
|---|---|---|
| T1 | Migration + models + indexes | Alembic revision applies/rolls back cleanly; unique dedupe enforced (insert twice → one row) |
| T2 | `SignalService.emit` + post-commit enqueue + unit tests | emit inside a rolled-back transaction leaves no row (outbox correctness) |
| T3 | Dispatcher Arq job: claim → resolve trigger → spawn run → CONSUMED | two workers + 100 pending signals → each consumed exactly once (SKIP-LOCKED concurrency test); critical-first ordering verified |
| T4 | Trigger resolution: pattern match (exact + prefix glob), priority tiebreak | deterministic-owner unit tests incl. tie cases |
| T5 | Sweeper cron: re-enqueue stale PENDING; PARKED→ESCALATED past SLA; DEAD path + `incident.governance` emission | kill-between-commit-and-enqueue test: signal still dispatches on next sweep ("no dropped signals" proven) |
| T6 | Completion hook in run finalization | consuming run's completion emits `<type>.completed`; idempotent on resume/retry |
| T7 | Email ingest → `email.inbound` signal, `dedupe_key` = RFC Message-ID | re-ingested email (IMAP re-poll) produces no second signal or run |
| T8 | Trigger-registry internal API + seed helper | a dev tenant can register a Process for `lead.*` via API |
| T9 | Coverage audit query + `mypy --strict` + parity/eval gates green | the one-query coverage audit documented in the README |

## 4. Testing Notes

Concurrency tests follow the existing chaos-suite patterns (`backend/tests/`): in-process worker drainer, deterministic clock for the sweeper SLAs. The dispatcher's run-spawn goes through the same code path the parity goldens exercise — no golden changes expected; if any appear, stop and investigate.

## 5. Brainstorm Decisions (Rahul, 2026-07-19)

1. **Sweep interval + park SLA defaults** — agreed: sweeper every 60s; default `park_review_at` = 15 min; ESCALATED after 3 unresolved reviews.
2. **First channel producer** — the **email ingest path** (not WhatsApp): `email.inbound` emitted where IMAP ingest lands messages, `dedupe_key` = RFC Message-ID.
3. **Signal taxonomy seed** — confirmed sufficient for this increment: `schedule.*`, `object.change_proposed`, `object.write_conflict`, `incident.governance`, `incident.platform`, `email.inbound`. The full Blueprint taxonomy arrives with Inc 2.

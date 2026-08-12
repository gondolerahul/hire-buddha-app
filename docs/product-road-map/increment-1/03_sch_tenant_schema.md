# Increment 1 / SCH — Tenant Schema, Records & the Tenant Data Plane

> **Status:** Draft — for brainstorm review · **Branch:** `inc1/sch` · **Register findings:** B3, B6 (write-ownership/CAS/data-plane halves), B8 (scoping half) — designs closed; this executes them.
> **Design authority:** technical doc §10.3–.5, §19, §23.1–.2, §23.4, §24.1–.3 (v3.0.5) — restated in full below.
> **Depends on:** SIG (`object.change_proposed` / `object.write_conflict` signal types), GOV (`before_cross_owner_write` checkpoint, `memory_domains` in the governance block). **Depended on by:** LOOP+ENV (nothing hard), all of Increment 2.
> **Decision (Rahul, 2026-07-18):** the per-tenant Postgres-in-sandbox data plane is **built in this increment**, not staged through the control-plane DB.

---

## 1. Design (self-contained)

### 1.1 Tables

Three tables, living in the **tenant DB** (sandbox-resident, §1.5):

* **`tenant_entity_defs`** — object-type definitions: `name`, evolving JSON `fields`, `version`, `owner_process_id` (write ownership, §1.3), `sor` block (Increment 4; column reserved now).
* **`tenant_records`** — JSONB documents keyed `(company_id, entity_def_id)`, plus `version` (int, CAS §1.4), `updated_by_run_id`, `def_version` stamped at write, `deleted_at` (soft delete).
* **`tenant_record_links`** — the typed edge table that makes the object graph real:

```python
class TenantRecordLink(Base):
    __tablename__ = "tenant_record_links"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(index=True)
    src_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_records.id"), index=True)
    dst_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_records.id"), index=True)
    rel_type: Mapped[str]     # closed seed vocabulary, extensible per tenant
    created_at: Mapped[datetime]
    # unique (src_record_id, dst_record_id, rel_type)
```

Seed `rel_type` vocabulary: `converted_to` (Signal→Lead→Opportunity→Quote→Contract), `belongs_to` (Contact→Account), `attached_to` (Ticket/Risk/Incident→anything), `fulfilled_by` (Order→Project), `billed_by` (Order→Invoice), `paid_by` (Invoice→Payment), `derived_from` (provenance).

**Indexing:** GIN (`jsonb_path_ops`) on `tenant_records.data`; B-tree on the link table's `(company_id, src_record_id)` / `(company_id, dst_record_id)`. Learning-promoted expression indexes (`CREATE INDEX CONCURRENTLY` on hot fields) are specified in §19.3 but deferred until the Learning System observes real traffic — not built this increment.

### 1.2 The HBS Seed — the Predefined HireBuddha Business Schema

Dynamic does not mean empty. Every tenant DB initializes with the **27 canonical objects** (Blueprint §3.2) as the spine — Signal, Campaign, Lead · Account, Contact, Opportunity, Quote, Contract · Order, Project/Engagement, Deliverable, Ticket · Invoice, Payment, Bill, Ledger Entry, Budget · Vendor, Purchase Order, Asset/Inventory Item · Candidate, Employee · Product/SKU · Risk, Incident, Policy/Obligation, Evidence — each with core fields, ref fields, and an owning Process, organized into the seven HBS modules (CRM, Accounting, HRMS, ERP/Operations, Legal, Marketing & PR, Planning). **Spine now; module field-depth in Increment 4.**

The field-level seed is drafted as **[03a_hbs_spine.md](./03a_hbs_spine.md)** (Claude drafts, Rahul reviews — decision 2026-07-18); once approved it is checked in as the seed fixture the initializer loads. Per-tenant evolution (§10.2) extends this baseline — it never starts from a blank page. Evolution *triggers* (agent-proposed fields, learning-driven promotion) are Increment 6; the manual/HBS path is what ships now.

**Schema evolution rules (apply from day one):** fields have a lifecycle `active → deprecated → hidden`; renames are additive aliases (reads resolve, writes normalize); type changes are add-new + backfill + deprecate, never in-place; `tenant_entity_defs.version` increments on any change and records stamp `def_version` at write — validation is write-time against the current def, old records upgrade lazily on their next write. No mass migrations.

### 1.3 One Write Path — Owner Writes, Others Propose

**All record writes go through one record service** — agents included, no direct table writes. The service:

1. Validates `data` against the def's current `fields` (including `ref` fields: `{"name": "account", "type": "ref", "target": "Account"}`) and **materializes every ref into a `tenant_record_links` row** — document and graph stay in sync because there is a single write path.
2. Enforces **write ownership**: agents of the def's `owner_process_id` write directly; any other agent's write is converted into an **`object.change_proposed` signal** (SIG) carrying the delta — the owning Process applies, amends, or rejects (rejection notifies the proposer's run). At A1 the application step is HITL-visible. Emergency direct cross-owner writes require the GOV checkpoint `before_cross_owner_write` — never silent. SoD falls out structurally: the AR agent cannot quietly edit a Vendor record.
3. Enforces **compare-and-set**: a write carries the `version` it read; a stale version triggers one bounded re-read-and-retry, then an `object.write_conflict` signal instead of a blind overwrite.
4. Defaults deletion to **soft delete** (`deleted_at`) so links never dangle; hard deletion exists only on the DSAR path (register D6, Increment 2), which cascades links and leaves a tombstone.

`owner_process_id` is set at HBS initialization from the canonical Process map (Invoices → Order-to-Cash, Vendors → Source-to-Pay, …) — the mapping ships in the 03a appendix.

### 1.4 The Tenant Data Plane — Uniform Postgres-in-Sandbox

Every tenant — including free/Solo — gets a **dedicated PostgreSQL + pgvector container inside their sandbox**, data directory on the persistent volume. One engine, one codepath, uniform hard isolation. The cost consequence is handled by **lifecycle, not architecture**:

* **Hibernation:** the tenant DB container starts lazily on first activity and hibernates after a per-tier idle window (Solo: aggressive, e.g. 15 min; Growth+: always-on). Cold-start latency is acceptable because the SIG dispatcher **parks, never drops**, signals for a waking tenant.
* **Small-footprint config:** capped `shared_buffers`/`work_mem` per tier; per-tenant connection caps with platform-side pooling keyed by tenant.
* **Backup/DR:** nightly encrypted `pg_dump` per tenant to object storage + weekly volume snapshot; restore = provision sandbox, restore dump. The tenant-triggerable **export** (the portability promise) is the same dump path, always available.
* **Segregation (§10.5, as amended v3.0.6):** the control plane holds identity, billing, registries, runs, signals, **and KB + CORTEX memory** (decision 2026-07-19 — control-plane permanent); the tenant DB holds the business's records: HBS records + links, artifacts, reports/exports. Cross-tenant analytics: none by construction.
* Realized idle cost per tier is a **required input to the E1 idle-cost model** (Increment 2) — measure it during this build.

*Scope note (settled 2026-07-19):* KB and CORTEX memory are **control-plane permanent** — no relocation, in this increment or ever (technical doc §10.4/§10.5 v3.0.6). Only HBS records, links, artifacts, and exports live in the tenant DB; the export bundle includes a control-plane KB+memory dump so portability stays whole.

### 1.5 Memory Scoping — Share Knowledge, Not Habits (§24.1–.3)

The four shipped CORTEX domains get explicit scopes:

| Domain | Scope | Written by | Read by |
|---|---|---|---|
| **Knowledge** | Tenant-shared | Ingestion + agents via the knowledge service | All agents, via need-to-know viewports |
| **Episodic** (per counterparty) | Tenant-shared, keyed by counterparty | Channel handlers / gateways | All agents, viewport-filtered |
| **Experience** | Per-entity | The Reflect stage | The owning entity; promotable |
| **Intelligence** | Per-entity, inheritable downward | Reflector + Dreaming | The entity + its descendants |

* **Tier write rules:** at Reflect, durable lessons promote to the **executing entity's** tree (a Skill's lesson lands on the Skill, not whichever Agent invoked it); the Dreaming engine consolidates upward along `parent_id` using the shipped confirmed-rule lifecycle.
* **Need-to-know viewports:** Knowledge/Episodic nodes carry **domain tags** (`payroll`, `legal`, `financial`, `general`, …) stamped at ingestion from the HBS module of origin; the governance block's `memory_domains` allow-list (GOV §1.1) is enforced by the shipped memory assembler's `ScopePolicy` at viewport-assembly time. A support agent's viewport *cannot contain* payroll nodes — prevention by construction, not prompt instruction.
* The §24.4 **retrieval upgrade** (hybrid+RRF, structure-aware chunking, retrieval goldens) is allowed to trail into Increment 2 per the roadmap; not in this workstream's acceptance criteria.

## 2. Code Mapping

| Piece | Where | Notes |
|---|---|---|
| New package | `backend/src/ai/tenant_schema/` | `models.py`, `record_service.py`, `hbs_seed/` (fixture + initializer), `bootstrap.py` (tenant-DB schema creation), README; `mypy --strict` |
| Tenant-DB bootstrap | `ai/tenant_schema/bootstrap.py` | tenant tables are **not** Alembic revisions on the control plane — a versioned bootstrap/upgrade script runs against each tenant DB on provision/wake |
| DB container | `backend/docker/` (new `hb-tenant-db` image: postgres + pgvector, tier config templates) | pinned digest file next to the existing sandbox `image.pin` |
| Lifecycle | `ai/tools/sandbox/tenant_manager.py` (+ `container_runtime.py`) | provision / lazy-start / hibernate / connection-string vending; pooling keyed by tenant |
| Backup jobs | `ai/worker.py` crons | nightly dump, weekly snapshot marker; export API reuses the dump path |
| Proposal/conflict signals | via `ai/signals/service.py` | types `object.change_proposed`, `object.write_conflict` |
| Memory scoping | `ai/memory/scope_policy.py` + ingestion paths | domain tags at ingestion; `memory_domains` enforcement in viewport assembly |
| Internal API | records/links CRUD router (admin + agent-internal; API-only this increment) | agents reach it as the single write path; a record tool wraps it for Inc 2 |

## 3. Task Plan

| # | Task | Deliverable / acceptance |
|---|---|---|
| T1 | **03a HBS spine appendix** — 27 objects × core fields, ref fields, owner Process, module + domain tag | Rahul reviews/approves the appendix; it becomes the seed fixture verbatim |
| T2 | `hb-tenant-db` image + `TenantSandboxManager` lifecycle (provision, lazy start, hibernate, pooled connections) | dev tenant gets a DB container; idle window hibernates it; first query wakes it; measured idle cost recorded for E1 |
| T3 | Tenant-DB bootstrap + models + HBS initializer | fresh tenant provision → 27 defs seeded with owner processes; bootstrap is versioned and re-runnable |
| T4 | Record service: validation, ref materialization, CAS, soft delete | ref write creates its link row atomically; stale-version write → one retry then `object.write_conflict` signal; unit + concurrency tests |
| T5 | Write ownership: owner-direct vs `object.change_proposed`, `before_cross_owner_write` checkpoint | non-owner write emits proposal signal; owner apply/reject path round-trips; SoD demo: AR agent cannot edit Vendor |
| T6 | Links/records internal API + lifecycle-chain traversal query | `Signal→Lead→Opportunity` chain built and traversed via API |
| T7 | Backup/export: nightly dump cron + tenant export endpoint | dump restores into a fresh container; export bundle = tenant-DB dump **+ control-plane KB/memory dump** (v3.0.6 rider) |
| T8 | Memory scoping: domain tags at ingestion + `memory_domains` viewport enforcement + tests | a `memory_domains: ["general"]` entity's viewport provably excludes `payroll`-tagged nodes |
| T9 | Evolution rules: alias resolution, deprecate/hidden lifecycle, lazy `def_version` upgrade | rename-via-alias round-trip test; old-version record upgrades on next write |

## 4. Testing Notes

The record service's CAS and ownership tests need real concurrency (two sessions racing one record) — follow the chaos-suite in-process patterns. Tenant-DB tests should run against a throwaway container in CI where Docker is available and fall back to a schema-per-test Postgres otherwise; the bootstrap script being idempotent is what makes both modes cheap.

## 5. Brainstorm Decisions (Rahul, 2026-07-19)

1. **Tier idle windows & footprint caps** — accepted: Solo 15 min idle / 256 MB shared_buffers; Growth+ always-on / 1 GB. Realized numbers feed the E1 idle-cost model.
2. **Owner-Process mapping before processes exist** — accepted: `owner_process_id` stores the canonical process *code* now, resolved to the entity id when Inc 2 seeds the Solo Pack; unresolvable owner is treated as "platform-owned, HITL on write".
3. **KB/CORTEX placement** — **decided: control plane, permanently** (Rahul, 2026-07-19). Rationale: memory is on the hot path of every run/heartbeat/Dreaming cron (tenant-DB placement would defeat hibernation and add a network hop), the shipped `hb-cortex-memory` + documents storage needs zero migration, and vector indexes stay out of the small-footprint tenant containers. Riders: the tenant export bundle always includes a KB+memory dump (portability stays whole); data residency at fleet scale is served by regional control planes. Technical doc amended to v3.0.6 (§10.4, §10.5, §23.4, §24.4).

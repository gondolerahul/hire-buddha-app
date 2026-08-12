# 04 — Extract CORTEX into a pip-installable Package

> Scope item 4. A detailed extraction plan already exists at
> `docs/CortexResearch/CORTEX_Implementation_Plan.md` (the "needs update" doc
> the brief points to). That plan is **still the spec of record** for the
> package design, the Protocol interfaces, the three-stage cutover, licensing,
> and CI/release. This file is the **Phase-12 delta**: what changed since that
> plan was written (Phase 11 reshaped `memory/`), what decisions to lock, and how
> the extraction sequences against the rest of Phase 12.

Do not re-read the 1460-line plan to act — read this delta first, then that plan
for the mechanical detail.

---

## 1. What the existing plan still gets right (keep)

* **Boundary:** host depends on package; package never imports host. ✔
* **Plugin model:** `LLMProvider`, `EmbeddingProvider`, `UsageReporter`,
  `RunRegistry` Protocols, with reference providers (OpenAI/Anthropic/Vertex/
  LiteLLM; sentence-transformers for tests). ✔
* **Package owns its `Base`** and ships its own Alembic migrations for
  `CortexTree/Node/Edge`. ✔
* **Three stages:** A = decouple in place (Protocols, no host break);
  B = move code into the package + one controlled cutover; C = polish + PyPI
  v0.1.0. ✔
* **Non-goals:** don't ship the engine/planner/governance/billing; pgvector-only;
  async-only v1; Apache-2.0. ✔
* **The seven coupling seams (S1–S7)** are still the real work: LLM, embedding,
  usage, admin config registry, shared `Base`, external FKs, REST auth.

This plan is good. The only reason it "needs update" is that **Phase 11 moved the
furniture** underneath it.

---

## 2. Current-state corrections (Phase 11 changed memory/)

The existing plan's §3 "Current State Snapshot" predates Phase 11. Corrections:

| Plan §3 statement | Reality after Phase 11 | Impact on extraction |
|-------------------|------------------------|----------------------|
| "`MemoryRouter` (v1) is the default; v2 is the future." | **v2 is canonical and default** (`memory.v2_canonical` ON). v1 is rollback-only and slated for deletion (`01` §4 / `05` P-D2). | Package should ship **v2 as the only assembler**; v1 need not move at all. The plan's "move both, default v2" simplifies to "move v2; drop v1." |
| Four domain services are "single-file, single-purpose." | They now share `memory/domains/base.py` (`DomainTreeBase`) with weighted retrieval. | The package gets `DomainTreeBase` for free; each domain service is already ~thin. The retrospective's "DomainTreeBase migration" theme is *part of* this extraction. |
| No mention of scope isolation. | `memory/scope_policy.py` (`ScopePolicy`, `ScopeViolation`) exists. | Move it into the package — it's a core tree primitive, not host logic. |
| Provenance "loose." | `Provenance` schema in `schemas/cortex.py`, plumbed into `CortexService.write`. | Move `Provenance` into the package's model layer. |
| `EmbeddingService` reads a constant. | `resolve_embedding_model(db, company_id)` exists (`memory.embedding_resolver_v2` ON), reading IntegrationRegistry. | This is exactly **seam S4** — the resolver becomes the host's `EmbeddingProvider` adapter; the package takes the provider via injection. |
| 14 back-compat shim files in `src/ai/*.py`. | Already removed/relocated in Phase 11's schema/ORM/memory split. | The plan's §3.3 shim-cleanup step is largely **already done** — verify, don't redo. |
| `CortexRouter` (service class) name collision. | Renamed to `CortexService` in Phase 11 (alias shim pending deletion, `05` P-D4). | Package exports `CortexService` cleanly; drop the host alias as part of `01`. |
| `cortex_models.py` FKs. | `p11t10_cortex_entity_nullable.py` already made the entity FK nullable. | Seam **S6** is partially done — the nullable-opaque-UUID pattern the plan prescribes is started; finish it for `companies/users/execution_runs`. |

Net effect: **Phase 11 did roughly Stage-A-worth of decoupling already**
(canonical v2, `DomainTreeBase`, `ScopePolicy`, `Provenance`,
`resolve_embedding_model`, nullable entity FK). The extraction is *closer* than
the original plan assumes.

---

## 3. Updated boundary — what moves vs stays (post-P11)

**Moves to `cortex-memory` package:**
`cortex_models.py` (→ own `Base`, opaque-UUID FKs), `cortex_service.py`
(`CortexService` + 7 ops), `cortex_ingestion.py`, `graph_service.py`, the four
domain services + `domains/base.py`, `scope_policy.py`, `dreaming_engine.py` +
`dreaming_prompts.py`, `embedding_service.py` (provider-injected),
`memory_assembly_service.py` (v2 assembler), `Provenance` + CORTEX DTOs,
`task_classifier.py` *iff* it is memory-domain (decide in §5).

**Stays in host (thin adapters):**
`cortex_bridge.py` (holds host `LLMRouter`/`UsageService`/Redis; implements the
Protocols), `cortex_router.py` (HTTP API — depends on host auth, seam S7),
`legacy_episodic_reader.py` (host-specific first-run top-up from the legacy
`EpisodicMemory` table), `failure_pattern_service.py` (reads host
`ExecutionRun`), `MemoryRouter` v1 (**not moved — deleted** per `01` §4).

**Does not move:** the AgentLoop, executors, planner, critics, governance,
billing — all host logic (plan §4.3 unchanged).

---

## 4. Decisions to lock before kickoff (plan §19, updated)

| # | Decision | Recommendation |
|---|----------|----------------|
| K1 | Package name | `cortex-memory` (verify on PyPI); import `cortex_memory`. |
| K2 | License | Apache-2.0 (patent grant; enterprise-friendly; dual-license optional later). |
| K3 | Repo strategy | Separate public repo; host consumes via pinned version (or a git submodule during Stage B for fast iteration, then PyPI at C). |
| K4 | `Base` sharing | Package owns its `Base`; host shares the same metadata during cutover via the documented adapter (plan §8). |
| K5 | FK strategy (S6) | Opaque nullable UUIDs in the package; host enforces referential integrity in its own schema. (Already started: entity FK nullable.) |
| K6 | `task_classifier` ownership | **Host**, not package — it depends on host task families / bandit. Package stays memory-only. |
| K7 | Cutover window | One controlled ~1-day cutover at end of Stage B, **scheduled after `01`'s memory deletions land** so the package isn't built around dead v1 code. |

---

## 5. Sequencing against Phase 12

CORTEX extraction is a **parallel track** (it touches `memory/`, which `01`'s
critic/loop deletions mostly don't), but two ordering constraints bind it:

1. **Do `01` §4 (delete MemoryRouter v1 body) BEFORE Stage B cutover.** Extract
   the *canonical* memory layer, not the canary double-stack. Otherwise the
   package inherits v1/v2 branching we're about to delete.
2. **Coordinate `Provenance` trust-score work (`07` §3) with the package model.**
   Trust-score *learning* logic can live host-side; the `trust_score` *field*
   lives in the package's node provenance.

Recommended calendar (maps to `08`):

* **Stage A (weeks 6–8):** finish seams S1–S7 in place behind Protocols
  (most already done — see §2). Add the `LLMProvider`/`EmbeddingProvider`/
  `UsageReporter`/`RunRegistry` Protocols and make `cortex_bridge` implement
  them. No host break. Can start while `01` is mid-flight.
* **Stage B (weeks 9–12):** create the package skeleton (plan §5.2 layout), move
  the code, host consumes via submodule/local path, run the one-day cutover.
  **Gate: `01` memory deletions merged.**
* **Stage C (weeks 12–14):** docs, examples, ≥85% coverage, `mypy --strict`,
  CI/CD, publish **v0.1.0** to PyPI.

---

## 6. What to update in the source plan doc

When this Phase 12 work starts, edit `CORTEX_Implementation_Plan.md`:

* §3 (Current State) — replace with §2 of this file (post-P11 reality).
* §4.4 (What Moves) — drop "move both v1/v2"; v2-only, v1 deleted.
* §3.3 (14 shim files) — mark as "done in Phase 11; verify only."
* §6 (D1–D7 decoupling tasks) — annotate D2/D4 (embedding) and D5 (Base) and the
  nullable-FK part of D6 as **partially complete** (`resolve_embedding_model`,
  `p11t10_cortex_entity_nullable`).
* §19 (Open Decisions) — fold in K1–K7 above.

---

## 7. Exit criteria

* `pip install cortex-memory`; quickstart works on a clean machine in <10 min.
* Host `backend/src/ai/memory/` contains **only** thin adapters
  (`cortex_bridge`, `cortex_router`, `legacy_episodic_reader`,
  `failure_pattern_service`); all primitives come from the package.
* Existing runs replay identically across the cutover (100% smoke pass).
* Package ships ≥3 LLM + ≥3 embedding providers; `mypy --strict` + ≥85% coverage.
* v0.1.0 on PyPI under Apache-2.0; host pins the version.

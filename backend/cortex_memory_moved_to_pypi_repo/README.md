# cortex-memory

A navigable, writable **hierarchical-memory engine for LLM agents** — the agent
never holds "context", it holds a *viewport* onto a persistent cognitive tree
(PostgreSQL + pgvector). Extracted as a host-independent package (Phase 12 track
`04`). **Import:** `cortex_memory`. **Dist:** `cortex-memory`. **License:** Apache-2.0.

## Install

```bash
pip install cortex-memory          # needs a Postgres with the `vector` extension
```

## Quickstart

```python
import asyncio
from uuid import uuid4
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from cortex_memory import CortexService
from cortex_memory.providers_reference import EchoLLMProvider   # swap for your own adapter
from cortex_memory.schema import create_all_schema_async

async def main():
    engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/db")
    await create_all_schema_async(engine)                       # idempotent
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        cortex = CortexService(db, uuid4(), llm=EchoLLMProvider())
        tree = await cortex.create_tree(entity_id=uuid4(), user_id=None,
                                        task_description="Summarise the deck")
        await db.commit()
        working = await cortex.get_working_root(tree.id)
        await cortex.write(parent_id=working.id, node_type="finding",
                           title="Key point", content="…", summary="…")
        await db.commit()
        print((await cortex.navigate(working.id)).to_prompt_text())

asyncio.run(main())
```

A runnable version: `python -m cortex_memory.examples.quickstart`. The host
injects real LLM/embedding adapters via the Protocols (see **The boundary rule**);
the reference providers above let it run with no external services.

## Develop

```bash
pip install -e ".[dev]"
mypy --strict cortex_memory                                     # strict-clean
CORTEX_TEST_DATABASE_URL=postgresql+asyncpg://… coverage run --source=cortex_memory -m pytest
coverage report                                                 # ≥85%
python -m build                                                 # sdist + wheel
```

Pure-logic tests need nothing; the integration tests are skipped unless
`CORTEX_TEST_DATABASE_URL` (or `DATABASE_URL`) points at a Postgres+pgvector. CI:
`.github/workflows/cortex-memory.yml`.

---

> Status: **Stages B + C COMPLETE** (in-repo). The package is self-contained,
> `mypy --strict`-clean, 85%-covered, and builds a wheel; only the move to a
> public repo + PyPI upload remains. Every CORTEX module now lives here,
> with **zero host imports** (a package self-test enforces it): the data layer
> (`db`/`models`/`enums`/`dtos`/`schema`), the provider boundary
> (`providers`/`providers_reference`), and all services — `service` (the 7 tree
> ops), `graph`, `ingestion`, the four domain trees (`knowledge_tree`/
> `episodic_tree`/`experience_tree`/`intelligence_tree`), `dreaming`, and
> `assembly` (the v2 assembler) — plus `scope_policy`, `domains`, `prompts`, and
> the embedding/text helpers. The host's `src/ai/memory/` keeps only thin
> re-export/auto-injection **shims** + the genuine host **adapters**
> (`cortex_providers`, `cortex_bridge`, `cortex_router`, `embedding_service`,
> `legacy_episodic_reader`, `failure_pattern_service`). Remaining: Stage C
> (separate repo + dist packaging, ≥85% coverage, `mypy --strict`, CI, PyPI).

## The boundary rule

The package **never imports the host** (`src.ai.*`). CORTEX needs four things
from its host that are not memory concerns; it takes them via the Protocols in
`cortex_memory.providers`, which the host implements in a thin adapter
(`cortex_bridge`, which stays in `src/ai/memory/`):

| Protocol | Host adapter wraps | Seam |
|----------|--------------------|------|
| `LLMProvider` | `LLMRouter` | S1 |
| `EmbeddingProvider` | `EmbeddingService` + `resolve_embedding_model` | S4 |
| `UsageReporter` | `UsageService` / `CostAttribution` | S3 |
| `RunRegistry` | `ExecutionRun` lookups | S6 |

`cortex_memory.providers_reference` ships deterministic, dependency-free
implementations so the package runs in tests with zero host/DB/LLM.

## Locked decisions (plan `04` §4)

| # | Decision |
|---|----------|
| K1 | Import `cortex_memory`; distribution `cortex-memory`. |
| K2 | Apache-2.0. |
| K3 | Separate public repo; host pins the version (submodule/local path during Stage B). |
| K4 | Package owns its `Base`; host shares metadata during cutover. |
| K5 | Opaque nullable UUID FKs in the package; host enforces referential integrity. |
| K6 | `task_classifier` stays host-side (depends on host task families/bandit). |
| K7 | One controlled cutover at the end of Stage B, after `01`'s memory deletions (C2, done). |

## Done so far

- [x] **Data layer** — own `Base` (`db.py`), ORM (`models.py`, opaque FK-free
      external refs), enums (`enums.py`), DTOs (`dtos.py`), standalone schema
      bootstrap (`schema.py`). Host DB schema migrated (external cortex FK
      constraints dropped). Host shims keep all imports working.
- [x] **Provider boundary** — Protocols (`providers.py`) + reference impls
      (`providers_reference.py`) + the host adapters
      (`src/ai/memory/cortex_providers.py`: `HostLLMProvider` /
      `HostEmbeddingProvider` / `HostUsageReporter` / `HostRunRegistry` +
      `build_cortex_providers`).
- [x] **Tree primitives** — `scope_policy.py`, `domains.py` (`DomainTreeBase` +
      retrieval weights).

- [x] **All service bodies** — `service` / `graph` / `ingestion` / the four
      domain trees / `dreaming` / `assembly`, each converted from host imports
      (`LLMRouter` / `EmbeddingService` / `ExecutionRun` / usage) to **injected
      providers** (LLM via `LLMProvider`; embeddings via `EmbeddingProvider` +
      the node-aware `cortex_memory.embedding` helpers; RECURSE child runs via an
      injected `child_run_factory`). Host shims auto-inject the adapters so
      existing call sites are unchanged.

## Remaining (Stage C — separate repo + release)

1. Extract this directory to its own public repo with a `pyproject.toml`
   (name `cortex-memory`, Apache-2.0, deps: SQLAlchemy + pgvector + pydantic).
2. ≥85% coverage, `mypy --strict`, CI, examples, docs.
3. Publish v0.1.0 to PyPI; the host pins the version and drops the in-repo copy.

`cortex_bridge.py`, `cortex_router.py` (HTTP), `embedding_service.py`,
`legacy_episodic_reader.py`, `failure_pattern_service.py` stay host-side as the
genuine adapters / host-specific code (plan §3).

# Track 0 — Pre-Flight Cleanup (Week 1)

> **Owner:** Agent kernel engineer (or anyone — this is mechanical work).
> **Duration:** 5 working days.
> **Behaviour change:** None. This Track only removes confusion.
> **Risk:** Low. Every change is a `git mv` / `git rm` / one-line edit
>   protected by tests that already exist.
> **Goal mapping:** G6 (clean package layout).

---

## 1. Objectives (functional)

After Track 0:

1. A new contributor cloning the repo sees **one** location for every
   module. No more "is `cortex_service.py` in `ai/` or `ai/memory/`?"
2. `git status` is clean of phantom deletions.
3. CI fails any future PR that introduces a top-level file under
   `backend/src/ai/` that doesn't belong there.
4. The string `from src.ai.worker import …` does not appear anywhere in
   the repo (except `worker.py`'s own module-level Arq settings).
5. `CortexRouter` (the *class*) is renamed to `CortexService` everywhere;
   `CortexRouter` only refers to the FastAPI HTTP router file.

---

## 2. Scope

### In scope

* Remove all 20 ghost duplicate files from the git index (deleted on
  disk, still tracked).
* Move all migration scripts under `backend/scripts/migrations/`.
* Move all seed scripts (`SeedEntities/`, `DeepResearchSetup/`) under
  `backend/scripts/seeds/`.
* Rename `memory/cortex_service.py::CortexRouter` → `CortexService`;
  drop the `as CortexService` aliases.
* Delete the backwards-compat re-exports in `worker.py:48-67`.
* Add a CI layout-lint script that enforces the package shape.

### Out of scope

* Any refactor inside the surviving files. Not even formatting.
* Any rename other than the `CortexRouter` → `CortexService` one above.
* Any DB / schema change.
* Any new tests beyond the layout-lint smoke test (existing tests must
  pass).

---

## 3. Architecture (technical)

There is no new architecture. The mechanical changes:

```
BEFORE                                         AFTER
backend/src/ai/                                backend/src/ai/
├── cortex_service.py            (deleted)    ├── memory/cortex_service.py  ← unchanged
├── memory/cortex_service.py     (kept)       │   class CortexService       ← renamed
├── ai/.. ghost duplicates       (rm'd)       ├── … all other code unchanged
├── migrate_*.py                 (moved)
└── worker.py (with re-exports)               worker.py (without re-exports)
                                              backend/scripts/migrations/*  ← new home
                                              backend/scripts/seeds/*       ← new home
```

CI gains one new check:

```
backend/scripts/lint_ai_layout.py    ← invoked by pre-commit + CI
```

That script enforces the file-layout rules listed in
[`../07_folder_restructure.md` §5](../07_folder_restructure.md).

---

## 4. Detailed deliverables

### 4.1 Item T0-1 — Git index cleanup (Day 1, morning)

**Action:** one commit, one PR.

```bash
git rm \
  backend/src/ai/cortex_bridge.py \
  backend/src/ai/cortex_ingestion.py \
  backend/src/ai/cortex_models.py \
  backend/src/ai/cortex_router.py \
  backend/src/ai/cortex_service.py \
  backend/src/ai/dreaming_engine.py \
  backend/src/ai/dreaming_prompts.py \
  backend/src/ai/embedding_service.py \
  backend/src/ai/episodic_tree_service.py \
  backend/src/ai/experience_tree_service.py \
  backend/src/ai/goal_alignment.py \
  backend/src/ai/governance_service.py \
  backend/src/ai/graph_service.py \
  backend/src/ai/intelligence_tree_service.py \
  backend/src/ai/knowledge_tree_service.py \
  backend/src/ai/llm_router.py \
  backend/src/ai/memory_assembly_service.py \
  backend/src/ai/memory_service.py \
  backend/src/ai/planner_service.py \
  backend/src/ai/rate_limiter.py
```

**Verify before commit:** none of the deleted files is imported.

```bash
for f in cortex_bridge cortex_ingestion cortex_models cortex_router \
         cortex_service dreaming_engine dreaming_prompts embedding_service \
         episodic_tree_service experience_tree_service goal_alignment \
         governance_service graph_service intelligence_tree_service \
         knowledge_tree_service llm_router memory_assembly_service \
         memory_service planner_service rate_limiter; do
  echo "=== $f ==="
  grep -RIn "from src\.ai\.${f} \|from src\.ai import ${f}\|src\.ai\.${f}" \
       backend/src/ frontend/ tests/ | grep -v "^backend/src/ai/${f}" | head -5
done
```

If any hits appear, fix the import to the canonical location *before*
running `git rm`.

**Commit message:**

```
phase11(track-0): remove ghost duplicate modules from index

These 20 modules were deleted on disk during the Phase 10A move
but remained tracked in the git index. Anyone running
`git reset --hard` would resurrect them. Canonical replacements live
under ai/{core,memory,planning,governance,llm}/.

No behaviour change.
```

### 4.2 Item T0-2 — Move migrations & seeds (Day 1, afternoon)

```bash
mkdir -p backend/scripts/migrations
mkdir -p backend/scripts/seeds/deep_research
mkdir -p backend/scripts/seeds/default_entities

git mv backend/src/ai/migrate_documents_to_knowledge_trees.py \
       backend/scripts/migrations/documents_to_knowledge_trees.py

git mv backend/src/ai/migrate_episodic_to_trees.py \
       backend/scripts/migrations/episodic_to_trees.py

# DeepResearchSetup/ — currently tracked but deleted on disk
git rm -r DeepResearchSetup/

# SeedEntities/ — currently untracked
git mv SeedEntities/* backend/scripts/seeds/default_entities/
```

**Update**:
* `backend/scripts/migrations/__init__.py` (new empty file).
* `backend/scripts/seeds/__init__.py` (new empty file).
* `backend/scripts/migrations/README.md` — explains "one-off migrations
  intended for `.venv/bin/python -m backend.scripts.migrations.<name>`."
* Any cron job or Makefile reference pointing to the old paths is
  updated.

**Verify:**

```bash
grep -RIn "src.ai.migrate_\|SeedEntities/\|DeepResearchSetup/" \
     backend/ frontend/ deploy/ | head
```

### 4.3 Item T0-3 — `CortexRouter` → `CortexService` rename (Day 2)

The file `memory/cortex_service.py` defines `class CortexRouter`. The
file `memory/cortex_router.py` defines the FastAPI router. The codebase
disambiguates with `from … import CortexRouter as CortexService` at every
import site (7 occurrences).

**Action:**

```bash
# 1. Rename the class
sed -i 's/^class CortexRouter:/class CortexService:/' \
      backend/src/ai/memory/cortex_service.py

# 2. Add a backwards-compat alias for one PR cycle only
echo "" >> backend/src/ai/memory/cortex_service.py
echo "# Backwards-compat alias — DEPRECATED, scheduled for removal in Track 9" >> backend/src/ai/memory/cortex_service.py
echo "CortexRouter = CortexService" >> backend/src/ai/memory/cortex_service.py

# 3. Replace import sites
grep -rln "from src.ai.memory.cortex_service import CortexRouter as CortexService" backend/ \
  | xargs sed -i 's/from src\.ai\.memory\.cortex_service import CortexRouter as CortexService/from src.ai.memory.cortex_service import CortexService/g'

grep -rln "from src.ai.memory.cortex_service import CortexRouter\b" backend/ \
  | xargs sed -i 's/from src\.ai\.memory\.cortex_service import CortexRouter\b/from src.ai.memory.cortex_service import CortexService/g'
```

**Files touched (expected):**

* `backend/src/ai/memory/cortex_service.py` — class renamed.
* `backend/src/ai/memory/cortex_router.py` — import updated.
* `backend/src/ai/memory/cortex_bridge.py` — import updated.
* `backend/src/ai/memory/memory_service.py` — import updated.
* `backend/src/ai/memory/memory_assembly_service.py` — import updated.
* `backend/src/ai/core/execution_engine.py:44` — import + usage.
* `backend/src/ai/core/recursive_engine.py:303` — import + usage.

**Verify (must be 0):**

```bash
grep -RIn "CortexRouter as CortexService\|class CortexRouter\b" \
     backend/src/ai/ | wc -l
```

(Should be 0; the only remaining `CortexRouter` symbol is the backwards-
compat alias added in step 2.)

### 4.4 Item T0-4 — Remove `worker.py` re-exports (Day 2, afternoon)

**Current** `backend/src/ai/worker.py:48-67`:

```python
from src.ai.core.execution_engine import ExecutionEngine  # noqa: F401
from src.ai.core.recursive_engine import RecursiveReasoningEngine  # noqa: F401
from src.ai.core.exceptions import UncertaintySignal  # noqa: F401
from src.ai.core.prompt_utils import (...)
from src.ai.core.context_utils import (...)
from src.ai.schemas import GoalNode  # noqa: F401
from src.ai.schemas import DEFAULT_REVIEW_SYSTEM_PROMPT as DEFAULT_REVIEW_PROMPT  # noqa: F401
from src.ai.schemas import DEFAULT_PLANNING_SYSTEM_PROMPT as DYNAMIC_PLANNER_PROMPT  # noqa: F401
```

**Find call sites:**

```bash
grep -RIn "from src.ai.worker import \(ExecutionEngine\|RecursiveReasoningEngine\|UncertaintySignal\|parse_variables\|build_sandwich_prompt\|filter_context_for_step\|_store_step_output\|_sanitize_context_for_persistence\|GoalNode\|DEFAULT_REVIEW_PROMPT\|DYNAMIC_PLANNER_PROMPT\)" backend/
```

Each call site moves to the canonical import:

| Old | New |
|-----|-----|
| `from src.ai.worker import ExecutionEngine` | `from src.ai.core.execution_engine import ExecutionEngine` |
| `from src.ai.worker import RecursiveReasoningEngine` | `from src.ai.core.recursive_engine import RecursiveReasoningEngine` |
| `from src.ai.worker import UncertaintySignal` | `from src.ai.core.exceptions import UncertaintySignal` |
| `from src.ai.worker import GoalNode` | `from src.ai.schemas import GoalNode` |
| `from src.ai.worker import DEFAULT_REVIEW_PROMPT` | `from src.ai.schemas import DEFAULT_REVIEW_SYSTEM_PROMPT as DEFAULT_REVIEW_PROMPT` (or just import the original name) |
| `from src.ai.worker import DYNAMIC_PLANNER_PROMPT` | `from src.ai.schemas import DEFAULT_PLANNING_SYSTEM_PROMPT as DYNAMIC_PLANNER_PROMPT` |

After fixing call sites, delete lines 48-67 of `worker.py`. The file
shrinks to ~30 lines of Arq config.

**Verify:**

```bash
grep -RIn "from src.ai.worker import " backend/ | grep -v "noqa: F401"
# Expected: empty
```

### 4.5 Item T0-5 — Layout-lint script (Days 3-4)

Create `backend/scripts/lint_ai_layout.py`. It MUST be executable as both
a CLI and a pre-commit hook.

```python
#!/usr/bin/env python3
"""
lint_ai_layout.py — Enforces the AI package shape defined in
docs/phase11/07_folder_restructure.md.

Exits non-zero on violation; prints a single-line error per violation.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = REPO_ROOT / "backend" / "src" / "ai"

# Top-level files allowed directly under backend/src/ai/
ALLOWED_TOPLEVEL = {
    "__init__.py",
    "worker.py",
    "README.md",
}

# Maximum line counts per package
MAX_LINES = {
    "core": 600,
    "planning": 600,
    "memory": 800,             # cortex_service is justifiedly large
    "meta": 800,
    "governance": 600,
    "tools": 1000,             # tools may be long (provider-driven)
    "llm": 800,
}

# Forbidden patterns inside source files
FORBIDDEN_IMPORT_PATTERNS = [
    "from src.ai.worker import ",
    "import src.ai.worker",
]

# Forbidden cross-package aliases that mask name collisions
FORBIDDEN_ALIAS_PATTERNS = [
    " as CortexService",       # the CortexRouter alias dance
]


def lint() -> int:
    violations: list[str] = []

    # 1. Top-level file whitelist
    for p in AI_ROOT.iterdir():
        if p.is_file() and p.name not in ALLOWED_TOPLEVEL:
            violations.append(
                f"LAYOUT: top-level file not allowed: backend/src/ai/{p.name}"
            )

    # 2. File size caps per package
    for pkg, cap in MAX_LINES.items():
        pkg_root = AI_ROOT / pkg
        if not pkg_root.exists():
            continue
        for py in pkg_root.rglob("*.py"):
            n = sum(1 for _ in py.read_text().splitlines())
            if n > cap:
                violations.append(
                    f"SIZE: {py.relative_to(REPO_ROOT)} has {n} lines "
                    f"(cap for {pkg}/ is {cap})"
                )

    # 3. Forbidden import / alias patterns
    for py in AI_ROOT.rglob("*.py"):
        text = py.read_text()
        for pat in FORBIDDEN_IMPORT_PATTERNS:
            if pat in text:
                violations.append(
                    f"IMPORT: {py.relative_to(REPO_ROOT)} contains forbidden "
                    f"pattern '{pat}'"
                )
        for pat in FORBIDDEN_ALIAS_PATTERNS:
            if pat in text and "Backwards-compat alias" not in text:
                violations.append(
                    f"ALIAS: {py.relative_to(REPO_ROOT)} contains forbidden "
                    f"pattern '{pat}'"
                )

    # 4. No "Phase N" or "Fix X:" narration in NEW files (heuristic: skip
    #    files in legacy paths to avoid noise; CI will hit new code only)
    # Optional, controlled by env var, skipped here for brevity.

    for v in violations:
        print(v)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(lint())
```

**Wire into CI:** add to GitHub Actions / GitLab CI as a step that runs
before the Python test job.

**Wire into pre-commit:** add to `.pre-commit-config.yaml`:

```yaml
  - repo: local
    hooks:
      - id: ai-layout-lint
        name: AI package layout lint
        entry: backend/scripts/lint_ai_layout.py
        language: python
        pass_filenames: false
        always_run: true
```

### 4.6 Item T0-6 — `backend/src/ai/README.md` (Day 5)

A single 80-line README that explains the package shape and points to
`docs/phase11/plan/`.

```markdown
# backend/src/ai/ — Agent Kernel

This package implements the HireBuddha agent kernel. Its shape is
governed by `docs/phase11/07_folder_restructure.md` and enforced by
`backend/scripts/lint_ai_layout.py`.

## Subpackages

| Path | Purpose | See |
|------|---------|-----|
| `api/` | HTTP / SSE endpoints | docs/phase11/plan/13_… |
| `services/` | Long-running services not part of the loop | docs/phase11/plan/01_… §7 |
| `schemas/` | Pydantic DTOs split per domain | docs/phase11/plan/03_… |
| `orm/` | SQLAlchemy ORM split per domain | docs/phase11/plan/03_… |
| `core/` | The AgentLoop + executors + reasoning modes | docs/phase11/plan/04_… |
| `planning/` | Plan generation, invariants, critic pipeline | docs/phase11/plan/05_…, 09_… |
| `memory/` | CORTEX + the four memory domains + dreaming | docs/phase11/plan/08_… |
| `meta/` | Meta-Agent board + sprawl mgmt + skill library | docs/phase11/plan/07_… |
| `governance/` | Cost gating, HITL, rate limiting, tool cost resolver | docs/phase11/plan/10_… |
| `llm/` | Provider adapters + the LLM router | (stable) |
| `tools/` | Tool registry + tool implementations | docs/phase11/plan/10_… |

## Rules (enforced by lint)

* No new top-level files in `src/ai/` other than `__init__.py`,
  `worker.py`, and this README.
* No `from src.ai.worker import …`.
* No cross-package import aliasing like `… as X` that masks a name
  collision.
* File-size caps per package (see lint script).
```

---

## 5. Database / schema changes

**N/A — unaffected.**

---

## 6. API changes

**N/A — unaffected.**

---

## 7. Telemetry events

**N/A — Track 0 introduces no events.**

---

## 8. Feature flags

**N/A — Track 0 has nothing to gate.**

---

## 9. Tests

### 9.1 Existing tests

All pre-existing tests MUST pass. Specifically:

* `pytest backend/tests/` — full suite.
* `pytest backend/tests/test_smoke.py` if it exists; a smoke run of the
  worker against a known entity.

### 9.2 New tests

| Test | File | What it asserts |
|------|------|-----------------|
| `test_layout_lint_passes` | `backend/tests/test_layout.py` | `python backend/scripts/lint_ai_layout.py` exits 0 on `HEAD` |
| `test_cortex_service_rename` | `backend/tests/test_imports.py` | `from src.ai.memory.cortex_service import CortexService` works; the bw-compat `CortexRouter` alias also resolves |
| `test_no_worker_re_exports` | `backend/tests/test_imports.py` | `from src.ai.worker import ExecutionEngine` raises `ImportError` |

### 9.3 Manual smoke

* Boot the Arq worker. Confirm `start_services.sh` runs clean.
* Trigger one entity execution end-to-end (e.g. the Meta-Agent against
  "make me a web-search agent"). Confirm it completes.

---

## 10. Acceptance criteria

Track 0 is **done** when ALL of these are true:

1. `git status` is clean.
2. `git ls-files backend/src/ai/ | grep -E "cortex_|memory_service\.py$|llm_router\.py$|planner_service\.py$|goal_alignment\.py$|governance_service\.py$|rate_limiter\.py$|graph_service\.py$|dreaming|episodic_tree|experience_tree|intelligence_tree|knowledge_tree|memory_assembly" | grep -v "^backend/src/ai/\(memory\|planning\|governance\|llm\)/"` returns empty.
3. `python backend/scripts/lint_ai_layout.py` exits 0 on `HEAD`.
4. `grep -RIn "from src.ai.worker import " backend/` returns empty.
5. `grep -RIn "as CortexService" backend/src/ai/` returns empty.
6. The Arq worker boots and runs a smoke execution.
7. CI is green.

---

## 11. Effort breakdown (single engineer, 5 working days)

| Day | Work |
|-----|------|
| 1 AM | T0-1: ghost-file removal commit + PR |
| 1 PM | T0-2: migration / seed moves |
| 2 AM | T0-3: `CortexRouter` → `CortexService` rename |
| 2 PM | T0-4: remove `worker.py` re-exports + fix call sites |
| 3 | T0-5: layout-lint script + CI / pre-commit wiring |
| 4 | T0-5 continued: tests + tune caps + run on full codebase |
| 5 AM | T0-6: package README |
| 5 PM | Buffer / final QA / PR merge |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| A ghost file is still imported somewhere obscure | M | Worker fails to boot | The pre-rm `grep` pass in §4.1; CI runs the smoke test |
| `CortexRouter` rename breaks a third-party caller | L | API consumer breaks | Backwards-compat alias retained until Track 9 |
| Layout lint is too strict and blocks a legitimate file | M | PRs blocked | Caps & whitelist are tunable; add allow-listed exceptions inline |
| `worker.py` re-export removal misses an import site | M | Runtime ImportError | Add the explicit `test_no_worker_re_exports` test (§9.2) — fails the build before merge |

---

## 13. Dependencies

* **Upstream:** none. Track 0 is the entry point.
* **Downstream:** every other Track. Specifically:
  * Track 1 requires the cleaned package to do the `schemas/` split.
  * Track 9 deletes the backwards-compat `CortexRouter` alias added in
    §4.3.

---

## 14. Open questions

* None. This Track is fully specified.

# Phase A: Schema Evolution — Foundation Layer

**Timeline**: Week 1–2  
**Risk Level**: LOW  
**Dependencies**: None (first phase)  
**Goal**: Extend the database schema to support the Unified CORTEX Memory Architecture v2.0 without breaking any existing functionality.

---

## A.1 Executive Summary

This phase adds all new database columns, enum values, tables, and indexes required by the v2.0 architecture. Critically, **no application code changes** — existing trees and nodes continue to work with sensible defaults. This "schema first, code later" approach ensures zero-downtime migration and rollback safety.

---

## A.2 Prerequisites

| Prerequisite | Current Status | Action Required |
|---|---|---|
| PostgreSQL pgvector extension | ✅ Installed (migration `093ffa970086`) | Verify `vector(768)` type available |
| Alembic migration chain | ✅ Active (latest: `w1x2y3z4a5b6`) | New migration must chain from latest head |
| Production DB backup | ❌ Not automated | **Take manual backup before running migration** |

---

## A.3 Detailed Changes

### A.3.1 New Enum Types

Create two new PostgreSQL enum types:

```sql
CREATE TYPE memory_domain AS ENUM ('knowledge', 'experience', 'intelligence', 'episodic');
CREATE TYPE scope_level AS ENUM ('app', 'partner', 'tenant', 'user', 'entity', 'runtime');
```

**Python Model (cortex_models.py)**:
```python
class MemoryDomain(str, enum.Enum):
    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"
    INTELLIGENCE = "intelligence"
    EPISODIC = "episodic"

class ScopeLevel(str, enum.Enum):
    APP = "app"
    PARTNER = "partner"
    TENANT = "tenant"
    USER = "user"
    ENTITY = "entity"
    RUNTIME = "runtime"
```

### A.3.2 Extend `cortex_node_type` Enum

Add the following values to the existing `cortex_node_type` PostgreSQL enum:

| New Value | Domain | Purpose |
|---|---|---|
| `group` | Structural | Re-clustering group container |
| `document` | Knowledge | Represents an ingested document |
| `section` | Knowledge | A section/chapter within a document |
| `chunk` | Knowledge | Leaf-level text chunk with embedding |
| `observation` | Experience | A specific observation from execution analysis |
| `pattern` | Experience | A recurring pattern across multiple observations |
| `suggestion` | Experience | A suggested approach based on patterns |
| `instruction` | Intelligence | A distilled actionable rule |
| `strategy` | Intelligence | A high-level strategic approach |
| `preference` | Intelligence | A user/entity behavioral preference |
| `episode` | Episodic | A single execution episode record |
| `episode_group` | Episodic | Grouped episodes (by date, topic, etc.) |

**SQL** (must be done via individual ALTER TYPE statements):
```sql
ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS 'group';
ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS 'document';
ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS 'section';
ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS 'chunk';
ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS 'observation';
ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS 'pattern';
ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS 'suggestion';
ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS 'instruction';
ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS 'strategy';
ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS 'preference';
ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS 'episode';
ALTER TYPE cortex_node_type ADD VALUE IF NOT EXISTS 'episode_group';
```

> **⚠️ IMPORTANT**: PostgreSQL's `ALTER TYPE ... ADD VALUE` cannot run inside a transaction block. The Alembic migration must use `op.execute()` with `autocommit=True` or use `connection.execution_options(isolation_level="AUTOCOMMIT")`.

### A.3.3 Extend `cortex_trees` Table

Add the following columns with safe defaults:

| Column | Type | Default | Nullable | Purpose |
|---|---|---|---|---|
| `memory_domain` | `memory_domain` ENUM | `'knowledge'` | NO | Which memory domain this tree belongs to |
| `scope_level` | `scope_level` ENUM | `'runtime'` | NO | Hierarchical scope level |
| `app_id` | UUID FK → `companies.id` | NULL | YES | L0 scope key |
| `partner_id` | UUID FK → `companies.id` | NULL | YES | L1 scope key |
| `run_id` | UUID FK → `execution_runs.id` | NULL | YES | L5 scope key |
| `tree_category` | VARCHAR(100) | NULL | YES | Categorization (e.g., "hr_policies") |
| `expires_at` | TIMESTAMP | NULL | YES | Expiration time (NULL = never) |
| `is_persistent` | BOOLEAN | TRUE | NO | Whether tree survives archival |
| `last_consolidated_at` | TIMESTAMP | NULL | YES | Last dreaming process timestamp |
| `consolidation_generation` | INTEGER | 0 | NO | Number of consolidation cycles |
| `source_run_ids` | JSONB | NULL | YES | Which runs contributed (for Experience/Intelligence) |

**Default strategy for existing rows**:
```sql
UPDATE cortex_trees SET memory_domain = 'knowledge', scope_level = 'runtime'
    WHERE memory_domain IS NULL;
```

This default is correct: all existing trees are runtime-scoped knowledge/working trees.

### A.3.4 Extend `cortex_nodes` Table

| Column | Type | Default | Nullable | Purpose |
|---|---|---|---|---|
| `embedding` | `vector(768)` | NULL | YES | pgvector semantic vector |
| `embedding_model` | VARCHAR(100) | NULL | YES | Which model generated the embedding |
| `cross_refs` | JSONB | NULL | YES | Pointers to related nodes in OTHER trees |
| `access_count` | INTEGER | 0 | NO | How many times this node was READ |
| `last_accessed_at` | TIMESTAMP | NULL | YES | Last access timestamp |
| `importance_score` | NUMERIC(5,3) | 0.500 | NO | 0.0–1.0, updated by learning algorithm |

### A.3.5 New Table: `cortex_edges`

```sql
CREATE TABLE cortex_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_node_id UUID NOT NULL REFERENCES cortex_nodes(id) ON DELETE CASCADE,
    target_node_id UUID NOT NULL REFERENCES cortex_nodes(id) ON DELETE CASCADE,
    edge_type VARCHAR(50) NOT NULL,
    weight NUMERIC(5,4) DEFAULT 0.5000,
    traversal_count INTEGER DEFAULT 0,
    last_traversed_at TIMESTAMP,
    created_by VARCHAR(50),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(source_node_id, target_node_id, edge_type)
);
```

### A.3.6 New Indexes

```sql
-- cortex_trees (new columns)
CREATE INDEX ix_cortex_trees_domain_scope ON cortex_trees(memory_domain, scope_level);
CREATE INDEX ix_cortex_trees_scope_entity ON cortex_trees(scope_level, entity_id)
    WHERE entity_id IS NOT NULL;
CREATE INDEX ix_cortex_trees_scope_user ON cortex_trees(scope_level, user_id)
    WHERE user_id IS NOT NULL;
CREATE INDEX ix_cortex_trees_scope_company ON cortex_trees(scope_level, company_id);

-- cortex_nodes (embeddings + importance)
CREATE INDEX ix_cortex_nodes_embedding ON cortex_nodes
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ix_cortex_nodes_importance ON cortex_nodes(importance_score DESC);
CREATE INDEX ix_cortex_nodes_tree_type_status ON cortex_nodes(tree_id, node_type, status);
CREATE INDEX ix_cortex_nodes_created_at ON cortex_nodes(created_at);

-- cortex_edges
CREATE INDEX ix_cortex_edges_source ON cortex_edges(source_node_id);
CREATE INDEX ix_cortex_edges_target ON cortex_edges(target_node_id);
CREATE INDEX ix_cortex_edges_type_weight ON cortex_edges(edge_type, weight DESC);
```

> **NOTE**: The `ivfflat` index requires at least some rows with non-NULL embeddings to be effective. Initially it will be empty. Consider switching to `hnsw` index type for better performance with incremental inserts: `USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)`.

---

## A.4 Implementation Steps

### Step 1: Create Alembic Migration File

**File**: `backend/migrations/versions/x1y2z3a4b5c6_add_unified_cortex_memory_v2.py`

```
Chain from: w1x2y3z4a5b6_add_deleted_at_to_hierarchical_entities
```

The migration must be split into two operations:
1. **Non-transactional**: `ALTER TYPE ... ADD VALUE` statements (require AUTOCOMMIT)
2. **Transactional**: All `ALTER TABLE`, `CREATE TABLE`, `CREATE INDEX` statements

### Step 2: Update Python ORM Models

**File**: `backend/src/ai/cortex_models.py`

Changes:
1. Add `MemoryDomain` and `ScopeLevel` enum classes
2. Extend `CortexNodeType` enum with 12 new values
3. Add new columns to `CortexTree` class
4. Add new columns to `CortexNode` class
5. Add new `CortexEdge` ORM model
6. Update `__table_args__` with new indexes

### Step 3: Update Constants

**File**: `backend/src/ai/constants.py`

Add new internal context keys for v2:
```python
INTERNAL_CONTEXT_KEYS.update({
    "__intelligence__",
    "__experience__",
    "__episodic__",
    "__knowledge_refs__",
})
```

### Step 4: Validate Migration

```bash
# Generate migration
cd backend
alembic revision --autogenerate -m "add_unified_cortex_memory_v2"

# Review generated migration file
# Verify it includes ALL columns, tables, indexes

# Test upgrade
alembic upgrade head

# Test downgrade
alembic downgrade -1

# Re-upgrade
alembic upgrade head
```

### Step 5: Verify Existing Functionality

```bash
# Run existing test suite
pytest tests/ -v

# Verify existing trees still load correctly
# (memory_domain defaults to 'knowledge', scope_level defaults to 'runtime')
```

---

## A.5 Files Changed

| File | Action | Changes |
|---|---|---|
| `backend/src/ai/cortex_models.py` | MODIFY | Add enums, columns, CortexEdge model |
| `backend/src/ai/constants.py` | MODIFY | Add new internal context keys |
| `backend/migrations/versions/x1y2z3a4b5c6_*.py` | NEW | Migration file |

---

## A.6 Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| `ALTER TYPE ADD VALUE` requires AUTOCOMMIT | Medium | Split migration into two phases; test on staging first |
| ivfflat index with empty data | Low | Use HNSW index type instead, or defer index creation to Phase B |
| Large migration on production DB | Medium | Take backup; run during low-traffic window; test timing on staging |
| Foreign key constraint for `app_id`, `partner_id` on `companies` | Low | Both are nullable; existing rows unaffected |

---

## A.7 Validation Criteria

- [ ] Migration runs successfully (upgrade AND downgrade)
- [ ] All existing CORTEX trees load with `memory_domain='knowledge'`, `scope_level='runtime'`
- [ ] Existing operations (CREATE, NAVIGATE, READ, WRITE, RECURSE, CHECKPOINT) work unchanged
- [ ] New `cortex_edges` table exists and is empty
- [ ] New columns on `cortex_nodes` (embedding, importance_score, etc.) are NULL/default for existing rows
- [ ] All new indexes are created
- [ ] Application starts without errors

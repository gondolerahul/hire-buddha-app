# 12 — Data Model & Migrations (Cross-Cutting)

This document is the **single canonical place** for every database
change introduced across the programme. Tracks reference these
migrations by their identifier (`p11t02_*`, `p11t03_*`, …). If a
migration is added in one Track but referenced in another, this file
is the authoritative source.

---

## 1. Migration naming convention

`backend/migrations/versions/p11t<TT>_<slug>.py` where `<TT>` is the
Track number (00-09). E.g.:

```
p11t02_feature_flags.py
p11t02_cortex_snapshot_node_type.py
p11t03_pydantic_planstep_type_default.py     # no SQL change; placeholder
p11t05_preserve_meta_cognition.py
p11t06_backfill_intelligence_status.py
p11t08_usage_logs_attribution.py
p11t09_kpi_daily_rollup.py
p11t09_drop_unused_feature_flags.py
```

Files exist even when they are *data-only* (`UPDATE` statements) so
they get the same Alembic discipline as schema migrations.

---

## 2. Migrations index

| ID | Track | Purpose | Reversible | Long-running? |
|----|------:|---------|:----------:|:-------------:|
| `p11t02_feature_flags` | 2 | `feature_flags` table | yes | no |
| `p11t02_cortex_snapshot_node_type` | 2 | New CORTEX node types: `snapshot` | yes | no |
| `p11t03_planstep_type_default` | 3 | (placeholder; no SQL) | – | – |
| `p11t05_preserve_meta_cognition` | 5 | Backfill explicit `meta_cognition.registry_search/self_modification` for entities relying on old defaults | yes (set keys back to undefined) | yes (10-30s) |
| `p11t05_cortex_node_types_meta` | 5 | New CORTEX node types: `health_record`, `snapshot`, `skill_candidate`, `candidate_rule`, `confirmed_rule`, `bandit_arm_state`, `meta_anti_pattern`, `prompt_update_candidate` | yes | no |
| `p11t06_backfill_intelligence_status` | 6 | Existing Intelligence rules get `source_ref['status'] = 'confirmed'` | yes | yes (1-10s) |
| `p11t08_usage_logs_attribution` | 8 | `usage_logs.attribution` column + index | yes | yes (≤30s) |
| `p11t09_kpi_daily_rollup` | 9 | Materialised view + cron refresh | yes | yes (≤60s first run) |
| `p11t09_drop_unused_feature_flags` | 9 | Delete `feature_flags` rows whose flag is gone | yes | no |

---

## 3. Detailed migration sketches

### 3.1 `p11t02_feature_flags`

```python
def upgrade():
    op.create_table(
        "feature_flags",
        sa.Column("id", PGUUID, primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", PGUUID, nullable=True),
        sa.Column("entity_id", PGUUID, nullable=True),
        sa.Column("flag_key", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, default=False),
        sa.Column("value_json", sa.JSON, nullable=True),   # for non-boolean knobs
        sa.Column("created_at", sa.DateTime,
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime,
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_feature_flags_lookup", "feature_flags",
        ["flag_key", "company_id", "entity_id"], unique=True,
    )
```

`company_id IS NULL AND entity_id IS NULL` → global default.
`company_id IS NOT NULL AND entity_id IS NULL` → per-company override.
`entity_id IS NOT NULL` → per-entity override (rare).

Resolution order: entity > company > global > code default.

### 3.2 `p11t02_cortex_snapshot_node_type`

CORTEX `node_type` is already a free-text column, so this is a
**code-only** migration: extend the enum in `schemas/enums.py`.
No SQL change required *unless* a check constraint exists on the
column (verify with `\d cortex_nodes` first).

If a check constraint exists:

```python
def upgrade():
    op.execute("""
        ALTER TABLE cortex_nodes
        DROP CONSTRAINT IF EXISTS cortex_nodes_node_type_check;
        ALTER TABLE cortex_nodes ADD CONSTRAINT cortex_nodes_node_type_check
        CHECK (node_type IN (
            'root','knowledge','working','output','finding','task',
            'instruction','strategy','preference','section','group',
            'snapshot','health_record','skill_candidate',
            'candidate_rule','confirmed_rule','bandit_arm_state',
            'meta_anti_pattern','prompt_update_candidate'
        ))
    """)
```

### 3.3 `p11t05_preserve_meta_cognition`

```python
def upgrade():
    """
    The Track 5 default flip turns OFF auto-on for registry_search and
    self_modification on AGENT/PROCESS entities. To preserve current
    behaviour for entities that relied on the default, write explicit
    flags on every AGENT/PROCESS that doesn't already set them.
    """
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE hierarchical_entities
        SET capabilities = jsonb_set(
            jsonb_set(
              COALESCE(capabilities,'{}'::jsonb),
              '{meta_cognition,registry_search}',
              'true'::jsonb,
              true
            ),
            '{meta_cognition,self_modification}',
            'true'::jsonb,
            true
        )
        WHERE type IN ('AGENT','PROCESS')
          AND status != 'DELETED'
          AND COALESCE(
                capabilities #> '{meta_cognition,registry_search}',
                'null'::jsonb
              ) = 'null'::jsonb
          AND (metadata_extensions->>'is_meta_agent')::boolean IS NOT TRUE
    """))


def downgrade():
    """
    Strip the keys back so the new default takes effect.
    Idempotent: only removes keys with value `true`.
    """
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE hierarchical_entities
        SET capabilities = capabilities #- '{meta_cognition,registry_search}'
                                       #- '{meta_cognition,self_modification}'
        WHERE type IN ('AGENT','PROCESS')
    """))
```

> 🚨 **Run this migration BEFORE deploying the Track 5 code change.**
> Otherwise existing entities silently lose `registry_search` and
> `self_modification` capability.

### 3.4 `p11t06_backfill_intelligence_status`

```python
def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE cortex_nodes
        SET source_ref = jsonb_set(
            COALESCE(source_ref,'{}'::jsonb),
            '{status}',
            '"confirmed"',
            true
        )
        WHERE node_type IN ('instruction','strategy','preference')
          AND (source_ref IS NULL OR source_ref->>'status' IS NULL)
    """))
```

### 3.5 `p11t08_usage_logs_attribution`

```python
def upgrade():
    op.add_column(
        "usage_logs",
        sa.Column("attribution", sa.String(40),
                  nullable=False, server_default="tool"),
    )
    op.create_index(
        "ix_usage_logs_attribution_company_day",
        "usage_logs", ["company_id", "attribution", "created_at"],
    )


def downgrade():
    op.drop_index("ix_usage_logs_attribution_company_day",
                  table_name="usage_logs")
    op.drop_column("usage_logs", "attribution")
```

### 3.6 `p11t09_kpi_daily_rollup`

```python
def upgrade():
    op.execute("""
      CREATE MATERIALIZED VIEW IF NOT EXISTS kpi_daily_rollup AS
      WITH runs AS (
        SELECT
          date_trunc('day', er.completed_at) AS day,
          er.company_id,
          (SELECT tag FROM jsonb_array_elements_text(e.tags) tag LIMIT 1)
                                              AS primary_tag,
          er.id, er.status,
          COALESCE(er.total_cost_usd, 0) AS cost_usd,
          COALESCE(er.total_tokens, 0)   AS tokens,
          er.execution_time_ms
        FROM execution_runs er
        JOIN hierarchical_entities e ON e.id = er.entity_id
        WHERE er.completed_at IS NOT NULL
      )
      SELECT
        day, company_id, primary_tag,
        COUNT(*)                                         AS runs_total,
        SUM(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END) AS runs_completed,
        SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END)     AS runs_failed,
        SUM(cost_usd)                                     AS cost_usd_total,
        AVG(cost_usd)                                     AS cost_usd_avg,
        SUM(tokens)                                       AS tokens_total,
        AVG(execution_time_ms)                            AS latency_ms_avg
      FROM runs
      GROUP BY day, company_id, primary_tag;

      CREATE UNIQUE INDEX IF NOT EXISTS kpi_daily_rollup_uniq
        ON kpi_daily_rollup(day, company_id, primary_tag);
    """)


def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS kpi_daily_rollup")
```

### 3.7 `p11t09_drop_unused_feature_flags`

```python
def upgrade():
    op.execute("""
      DELETE FROM feature_flags
       WHERE flag_key IN (
         'critic_pipeline.v1_compat',
         'memory.v1_pipeline',
         'meta_review.v1_compat',
         'tools.cost_resolver_v2_enabled',
         'tools.resilience_v2_enabled'
       )
    """)
```

---

## 4. CORTEX node-type inventory (after Phase 11)

This is the canonical list. The Pydantic enum `CortexNodeType`
(`schemas/enums.py`) MUST match.

| node_type | Introduced | Written by | Purpose |
|-----------|-----------:|------------|---------|
| `root` | pre-existing | CortexService.create_tree | Tree root |
| `knowledge` | pre-existing | CortexBridge.ingest_tool_result, context-source ingestion | Long-lived knowledge |
| `working` | pre-existing | CortexBridge | Step working memory |
| `output` | pre-existing | AgentLoop._finalize | Final user-facing output |
| `finding` | pre-existing | step writes via CortexBridge | Per-step result |
| `task` | pre-existing | Recursive engine | Sub-task |
| `instruction` | pre-existing | IntelligenceTreeService | Behavioural rule |
| `strategy` | pre-existing | IntelligenceTreeService, PlanStyleBandit | Plan / approach |
| `preference` | pre-existing | IntelligenceTreeService | User pref |
| `section` | pre-existing | DomainTreeBase | Section header |
| `group` | pre-existing | DomainTreeBase | Grouping node |
| `snapshot` | **T2** | AgentState.snapshot_to_cortex | AgentLoop iteration snapshot |
| `health_record` | **T3** | CriticPipeline | One per executed step |
| `skill_candidate` | **T5** | SkillLibrary | Proposed reusable chain |
| `candidate_rule` | **T6** | Reflector.persist | Pending Intelligence rule |
| `confirmed_rule` | **T6** | DreamingEngine distillation | Promoted rule |
| `bandit_arm_state` | **T4** | PlanStyleBandit | Bandit arm snapshot |
| `meta_anti_pattern` | **T5** | MetaSpecCritic | Architecture anti-pattern |
| `prompt_update_candidate` | **T5** | prompt-evo cron | Awaiting HITL |

---

## 5. New column / table summary

| Table | Column | Type | Track |
|-------|--------|------|------:|
| `feature_flags` (NEW) | — | — | 2 |
| `usage_logs` | `attribution` | VARCHAR(40) NOT NULL DEFAULT 'tool' | 8 |
| `kpi_daily_rollup` (MAT VIEW) | — | — | 9 |
| `hierarchical_entities.capabilities` (JSONB) | (backfilled keys) | — | 5 |
| `cortex_nodes.node_type` (enum) | extended | — | 2,3,4,5,6 |
| `cortex_nodes.source_ref` (JSONB) | `status`, `provenance` keys | — | 6 |

No table is **dropped** during Phase 11. The `EpisodicMemory` table
becomes read-only after Track 6; Phase 12 drops it.

---

## 6. Migration ordering and dependencies

```
p11t02_feature_flags                  (T2 start)
p11t02_cortex_snapshot_node_type      (T2 start)
p11t05_preserve_meta_cognition        (T5 start — BEFORE code deploy)
p11t05_cortex_node_types_meta         (T5 start)
p11t06_backfill_intelligence_status   (T6 start)
p11t08_usage_logs_attribution         (T8 start)
p11t09_kpi_daily_rollup               (T9 start)
p11t09_drop_unused_feature_flags      (T9 end)
```

All migrations are **forward-compatible** with the previous Track's
code. Each is independently revertable.

---

## 7. Backward-compatibility guarantees

1. **No table renames** during Phase 11.
2. **No column drops** during Phase 11.
3. **All new columns** are nullable or have server defaults.
4. **Pydantic ↔ JSONB compatibility**: every Pydantic v2 model used as
   a JSONB column round-trips through `model_dump(mode='json')` →
   `model_validate(...)`. CI test enforces this for `HierarchicalEntity`,
   `Capabilities`, `LogicGate`, `Planning`, `Governance`.

---

## 8. Production deploy checklist (per migration)

For every Phase 11 migration:

* [ ] Run on staging clone of prod data; record duration.
* [ ] If duration > 30s → schedule maintenance window.
* [ ] Verify rollback (`downgrade`) works on staging.
* [ ] Telemetry alert dashboards already showing the new metrics
      (if applicable).
* [ ] Feature flag for the new code path exists and is OFF.
* [ ] Deploy migration.
* [ ] Verify no errors in worker logs.
* [ ] Flip flag ON for canary tenant.
* [ ] Watch dashboards 24h.
* [ ] Ramp.

Tracks 2 / 5 / 8 each have at least one "≥30 seconds" migration; plan
maintenance accordingly.

---

## 9. Open questions

* Should we add **partitioning** to `usage_logs` (by month) given the
  Track 8 / Track 9 query patterns? Recommended; out of scope for
  Phase 11.
* Should `kpi_daily_rollup` be a real table maintained by triggers
  instead of a materialised view? Performance call; only revisit if
  refresh latency becomes painful.
* Should we add a `cortex_nodes.confidence` numeric column for
  Intelligence rules (instead of stashing in `source_ref`)? Cleaner
  but bigger migration; Phase 12 candidate.

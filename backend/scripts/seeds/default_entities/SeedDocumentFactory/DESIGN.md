# Document Factory Engine — Design Document

## Overview

The Document Factory Engine is a hierarchical agentic system that converts
open-source Claude Skills knowledge into model-agnostic autonomous agents.
Each agent specializes in a single document type (DOCX, PPTX, XLSX, PDF)
and contains the full domain expertise distilled from the original skill
definitions — embedded directly into system prompts and behavioral constraints
so any LLM backend can execute them.

## Tools Used

| Tool | Purpose |
|------|---------|
| `sandbox_code` | Python/Node.js code execution (openpyxl, pandas, docx-js, PptxGenJS, reportlab) |
| `terminal` | Shell commands (unpack/pack scripts, pandoc, LibreOffice, pdftoppm) |

## Entity Hierarchy (~50 entities)

```
PROCESS: 📄 Document Factory Engine
├── AGENT: 📝 DOCX Document Agent
│   ├── SKILL: DOCX Creator
│   │   └── ACTION: Generate DOCX (docx-js)                [sandbox_code]
│   ├── SKILL: DOCX Editor
│   │   ├── ACTION: Unpack DOCX                             [terminal]
│   │   ├── ACTION: Edit DOCX XML                           [sandbox_code]
│   │   └── ACTION: Pack DOCX                               [terminal]
│   ├── SKILL: DOCX Reader
│   │   └── ACTION: Extract DOCX Content                    [terminal]
│   └── SKILL: DOCX Validator
│       └── ACTION: Validate DOCX                           [terminal]
├── AGENT: 📊 PPTX Presentation Agent
│   ├── SKILL: PPTX Creator (from scratch)
│   │   └── ACTION: Generate PPTX (PptxGenJS)              [sandbox_code]
│   ├── SKILL: PPTX Template Editor
│   │   ├── ACTION: Analyze Template                        [terminal]
│   │   ├── ACTION: Unpack PPTX                             [terminal]
│   │   ├── ACTION: Manipulate Slides                       [sandbox_code]
│   │   └── ACTION: Pack PPTX                               [terminal]
│   ├── SKILL: PPTX Reader
│   │   └── ACTION: Extract PPTX Content                    [terminal]
│   └── SKILL: PPTX Visual QA
│       ├── ACTION: Convert Slides to Images                [terminal]
│       └── ACTION: Visual Inspection                       [sandbox_code]
├── AGENT: 📈 XLSX Spreadsheet Agent
│   ├── SKILL: XLSX Creator
│   │   └── ACTION: Generate XLSX (openpyxl)                [sandbox_code]
│   ├── SKILL: XLSX Editor
│   │   └── ACTION: Edit XLSX (openpyxl)                    [sandbox_code]
│   ├── SKILL: XLSX Data Analyzer
│   │   └── ACTION: Analyze Data (pandas)                   [sandbox_code]
│   ├── SKILL: XLSX Formula Engine
│   │   ├── ACTION: Recalculate Formulas                    [terminal]
│   │   └── ACTION: Verify & Fix Errors                     [sandbox_code]
│   └── SKILL: XLSX Financial Formatter
│       └── ACTION: Apply Financial Standards               [sandbox_code]
├── AGENT: 📕 PDF Document Agent
│   ├── SKILL: PDF Creator
│   │   └── ACTION: Generate PDF (reportlab)                [sandbox_code]
│   ├── SKILL: PDF Manipulator
│   │   ├── ACTION: Merge/Split PDFs                        [sandbox_code]
│   │   └── ACTION: Rotate/Crop Pages                       [sandbox_code]
│   ├── SKILL: PDF Reader
│   │   ├── ACTION: Extract Text                            [sandbox_code]
│   │   └── ACTION: Extract Tables                          [sandbox_code]
│   ├── SKILL: PDF Form Filler
│   │   ├── ACTION: Detect Form Fields                      [terminal]
│   │   └── ACTION: Fill Form                               [terminal]
│   └── SKILL: PDF Security
│       └── ACTION: Encrypt/Decrypt PDF                     [sandbox_code]
└── AGENT: ✅ Document QA & Delivery
    └── SKILL: Document QA Pipeline
        ├── ACTION: Content Validation                      [sandbox_code]
        └── ACTION: Archive & Deliver                       [terminal]
```

## Execution Flow

1. **Request Analysis**: Process analyzes user request to determine document type(s) needed
2. **Dynamic Routing**: Invokes only the relevant document agent(s)
3. **Agent Orchestration**: Each agent decides which skills to invoke based on the task
4. **QA & Delivery**: Validates generated documents and archives outputs

## Setup

```bash
# Create all entities
python create_doc_entities.py

# Trigger an execution
python trigger_doc_execution.py

# Trigger with custom request
python trigger_doc_execution.py --request "Create a quarterly sales report as PPTX"

# Cleanup and recreate
python create_doc_entities.py --cleanup
```

## Files

| File | Purpose |
|------|---------|
| `config.py` | API client, auth, and shared configuration |
| `actions_docx.py` | DOCX ACTION entity definitions |
| `actions_pptx.py` | PPTX ACTION entity definitions |
| `actions_xlsx.py` | XLSX ACTION entity definitions |
| `actions_pdf.py` | PDF ACTION entity definitions |
| `actions_qa.py` | QA & Delivery ACTION entity definitions |
| `skills.py` | All SKILL entity definitions |
| `agents.py` | All AGENT entity definitions |
| `create_doc_entities.py` | Main setup script — creates all entities and links hierarchy |
| `trigger_doc_execution.py` | Trigger script — fires document generation with sample request |
| `phase11.py` | **Phase 11 enrichment layer** — injects the new agent-kernel config into every payload at creation time |
| `scripts/` | Helper scripts bundled from Claude Skills (docx, pptx, xlsx, pdf) |
| `entity_ids.json` | Generated — maps entity keys to UUIDs (created by setup) |

---

## Phase 11 Feature Coverage

The original entities were authored against the **pre-Phase-11** kernel. They are
now enriched (in `phase11.py`, applied by `create_doc_entities.py`) so a single
run of the `📄 Document Factory Engine` PROCESS exercises every Phase 11 track.
No global feature-flag flip is required: the two canary master switches
(`agent_loop.enabled`, `meta_agent.board_routing`, both default OFF) — plus all
the other v2 flags pinned for reproducibility — are written into every entity's
`metadata_extensions.feature_flags`. That is the per-entity tier of the
feature-flag resolver; the execution gate (`core/execution_engine.py::execute_run`)
reads it via `entity_extras`, so every entity in the hierarchy routes through the
new agent kernel automatically.

> **Why `metadata_extensions` and not a top-level field?** The entity
> create/update schema (`src/ai/schemas/entity.py`) is a *closed* Pydantic model
> (no `extra = "allow"`), so invented keys like `feature_flag_overrides`,
> `logic_gate.task_class`, `governance.budget`, `memory.domains` or
> `dynamic_planning.n_candidates` are **silently dropped on create**. The kernel
> reads per-entity Phase 11 config only from `metadata_extensions.feature_flags`
> (flags), `metadata_extensions.task_class` (bandit class), and the real
> `logic_gate.reasoning_config.reasoning_mode` field.

| Track | Phase 11 feature | How these entities exercise it |
|------:|------------------|--------------------------------|
| T2 | **AgentLoop** (perceive→…→decide) | `agent_loop.enabled` ON via `metadata_extensions.feature_flags` on **every** entity (parent + each child re-resolve flags with `entity_extras`). |
| T2 | **Reasoning modes** | All four used (real `reasoning_config.reasoning_mode` field): PROCESS → `TREE_OF_THOUGHTS`; agents → `REFLECTION` / `REACT`; tool skills+actions → `REACT`; read/validate skills+actions → `CHAIN_OF_THOUGHT`. |
| T2 | **Executors** | PROCESS→agents are `PARALLEL` (DAG executor); SKILL→ACTION chains are `SEQUENTIAL` (ChildEntity); atomic ACTIONs (SingleStep). |
| T2 | **Budget envelope** | Covered by existing `governance.max_cost_usd` + `governance.timeout_ms` per entity → `core/budget.py::Budget.from_governance` derives token/iteration axes. |
| T3 | **Critic pipeline v2** | `critic_pipeline.v2_enabled` (+ pre-critic, different-model, calibration) pinned ON per entity; agents keep `review_mechanism` + tight goals to drive pre/post/alignment/supervisor critics. |
| T4 | **Meta-review + Bandit** | `meta_review.v2_enabled` + `bandit.enabled` pinned ON; `metadata_extensions.task_class` per family (`document_orchestration`, `docx_authoring`, `pptx_design`, `xlsx_modeling`, `pdf_processing`, `document_qa`). |
| T5 | **Meta-Agent board** | `meta_agent.board_routing` (+ spec-critic, draft-lifecycle gates) pinned ON via `metadata_extensions.feature_flags`. |
| T6 | **Memory v2 + scope** | `memory.v2_canonical` + `memory.scope_policy_enforced` + `memory.dreaming_outcome_trigger` pinned ON; entities already use `mode: "CORTEX"`. |
| T7 | **Planner v2** | `planner.v2_enabled` + `invariants_enforced` + `judge_enabled` + `priors_enabled` pinned ON; candidate count from the global numeric flag `planner.n_candidates` (=3). |
| T8 | **Tool + cost** | `tools.cost_resolver_v2_enabled` + `tools.resilience_v2_enabled` pinned ON; real `sandbox_code`/`terminal` calls drive resilience + cost attribution. |
| T9 | **KPI / telemetry** | Populated automatically once the run completes. |

> **Manual step for EXPERIMENTAL-tool gating (T8):** mark a tool EXPERIMENTAL in
> the admin Tool Registry to see status badges + opt-in gating — that path is
> registry/admin-scoped, not expressible in a seed payload.

### Re-create with the Phase 11 config

```bash
python create_doc_entities.py --cleanup   # delete old set + recreate enriched
python trigger_doc_execution.py           # multi-format run → DAG routing + QA
```

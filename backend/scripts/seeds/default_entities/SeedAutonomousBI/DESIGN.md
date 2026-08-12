# Autonomous BI Engine — Design Document

## Overview

The Autonomous Business Intelligence Engine is a long-running agentic process
designed to stress-test the HireBuddha hierarchical entity framework. It takes
raw data parameters and produces a complete suite of business intelligence
deliverables: Excel workbooks, DOCX narrative reports, PPTX executive decks,
and PDF final packages.

## Tools Used

| Tool | Purpose |
|------|---------|
| `terminal_tool` | Data fetching (curl, psql, cat), file archiving |
| `sandbox_executor` | Python analytics (pandas, numpy, matplotlib, scipy) |
| `excel_tool` | Multi-sheet Excel workbooks with KPI dashboards |
| `docx_tool` | Narrative business reports |
| `pptx_tool` | Executive presentation decks |
| `pdf_generator` | Finalized PDF report packages |

## Entity Hierarchy (23 entities)

```
PROCESS: 📊 Autonomous BI Engine
├── AGENT: Data Processor & Analyst
│   ├── SKILL: Data Pipeline
│   │   ├── ACTION: Fetch Data              [terminal_tool]
│   │   └── ACTION: Clean & Transform       [sandbox_executor]
│   ├── SKILL: Analytics Engine
│   │   ├── ACTION: Statistical Analysis    [sandbox_executor]
│   │   └── ACTION: Anomaly & Forecasting   [sandbox_executor]
│   └── SKILL: Chart Generator
│       └── ACTION: Generate Charts         [sandbox_executor]
├── AGENT: Report Builder
│   ├── SKILL: Excel Builder
│   │   └── ACTION: Build Workbook          [excel_tool]
│   ├── SKILL: Narrative Writer
│   │   └── ACTION: Write DOCX Report       [docx_tool]
│   ├── SKILL: Deck Builder
│   │   └── ACTION: Build Exec Deck         [pptx_tool]
│   └── SKILL: PDF Finalizer
│       └── ACTION: Compile PDF             [pdf_generator]
└── AGENT: QA & Delivery
    └── SKILL: QA Pipeline
        ├── ACTION: Consistency Check       [sandbox_executor]
        └── ACTION: Archive Outputs         [terminal_tool]
```

## Execution Flow

1. **Data Processing Phase**: Data Processor fetches raw data → cleans/transforms → 
   runs statistical analysis → detects anomalies → generates forecasts → creates charts
2. **Quality Gate**: Process evaluates analytics completeness before proceeding
3. **Report Generation Phase**: Report Builder creates Excel → DOCX → PPTX → PDF
4. **QA & Delivery Phase**: QA Agent validates cross-document consistency → archives outputs

## Setup

```bash
# Create all entities
python create_bi_entities.py

# Trigger an execution
python trigger_bi_execution.py

# Trigger with custom topic
python trigger_bi_execution.py --topic "Q2 2026 Revenue Analysis"

# Cleanup and recreate
python create_bi_entities.py --cleanup
```

## Files

| File | Purpose |
|------|---------|
| `config.py` | API client, auth, and shared configuration |
| `actions.py` | Layer 1: 11 ACTION entity definitions |
| `skills.py` | Layer 2: 8 SKILL entity definitions |
| `agents.py` | Layer 3: 3 AGENT entity definitions |
| `create_bi_entities.py` | Main setup script — creates all entities and links hierarchy |
| `trigger_bi_execution.py` | Trigger script — fires the BI process with sample data |
| `entity_ids.json` | Generated — maps entity keys to UUIDs (created by setup) |

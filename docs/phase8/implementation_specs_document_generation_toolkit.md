# Phase 8: Document Generation Toolkit — Implementation Specifications

**Status:** Detailed Specs — Ready for Development  
**Date:** 2026-05-12  
**Architecture Reference:** [architecture_document_generation_toolkit.md](./architecture_document_generation_toolkit.md)

---

## 1. Entity Hierarchy Design

Per the architecture document, the Document Director is designed as a **PROCESS** entity that orchestrates 5 child entities via `CHILD_ENTITY_INVOCATION` steps.

Child entities use **AGENT** type for multi-turn REACT reasoning with tool orchestration. The Revision Agent uses **SKILL** type (simpler, one-cycle fix).

```
Document Director (PROCESS)
│
├── Step 1: Content Architect (AGENT)
│   └── Pure LLM reasoning → produces Document Blueprint JSON
│
├── Step 2: Visual Asset Creator (AGENT)
│   └── Tools: sandbox_code, image_generation, terminal
│   └── Produces: Asset manifest with file paths
│
├── Step 3: Document Renderer (AGENT)
│   └── Tools: sandbox_code, terminal, document_save
│   └── Produces: Final document file (pptx/docx/xlsx/pdf)
│
├── Step 4: Quality Inspector (AGENT)
│   └── Tools: terminal, sandbox_code
│   └── Produces: QA Report (pass/fail with defects)
│
└── Step 5: Revision Agent (SKILL, CONDITIONAL)
    └── Tools: sandbox_code, terminal, document_save
    └── Only runs if Quality Inspector finds defects
```

---

## 2. New Tool: `document_save`

### Purpose
Bridges sandbox-generated document files to the platform's artifact system. Used by Document Renderer and Revision Agent after `sandbox_code` creates the file.

### Input Schema
```json
{
  "source_path": "/tmp/sandbox/<company_id>/pitch_deck.pptx",
  "filename": "pitch_deck.pptx",
  "format": "pptx",
  "purpose": "AI-generated investor pitch deck"
}
```

### Output Schema
```json
{
  "status": "success",
  "artifact_id": "uuid",
  "file_path": "/absolute/path/to/artifact",
  "file_size": 245760,
  "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation"
}
```

### MIME Type Map
| Format | MIME Type |
|--------|-----------|
| pptx | `application/vnd.openxmlformats-officedocument.presentationml.presentation` |
| docx | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| xlsx | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| pdf | `application/pdf` |

### Implementation Location
`backend/src/ai/tools/document_save.py`

### Registration
- `backend/src/ai/tools/__init__.py` — import and register
- `backend/src/ai/tool_management_service.py` — add `"document_save": "document"` to `_BUILTIN_CATEGORIES`

---

## 3. Entity Definitions (Detailed)

### 3.1 Document Director (PROCESS)

```json
{
  "name": "document-director",
  "display_name": "Document Director",
  "description": "Orchestrates world-class document generation across PPTX, DOCX, XLSX, PDF by coordinating specialized child agents through a 5-step production pipeline.",
  "goal": "Produce visually stunning, publication-quality documents by coordinating Content Architect, Visual Asset Creator, Document Renderer, Quality Inspector, and Revision Agent.",
  "type": "PROCESS",
  "version": "1.0.0",
  "status": "ACTIVE",
  "tags": ["document-generation", "system", "premium"],
  "identity": {
    "role": "Creative Director & Production Manager",
    "system_prompt": "<<DOCUMENT_DIRECTOR_PROMPT>>",
    "personality": {
      "tone": "professional",
      "verbosity": "concise",
      "formality": "semi-formal"
    }
  },
  "hierarchy": {
    "children": [
      {"child_id": "{{content_architect_id}}", "relationship": "SEQUENTIAL"},
      {"child_id": "{{visual_asset_creator_id}}", "relationship": "SEQUENTIAL"},
      {"child_id": "{{document_renderer_id}}", "relationship": "SEQUENTIAL"},
      {"child_id": "{{quality_inspector_id}}", "relationship": "SEQUENTIAL"},
      {"child_id": "{{revision_agent_id}}", "relationship": "CONDITIONAL",
       "condition": {"enabled": true, "expression": "quality_inspector.defects_found == true"}}
    ]
  },
  "planning": {
    "static_plan": {
      "enabled": true,
      "steps": [
        {
          "step_id": "step_1", "order": 1,
          "name": "Content Architecture",
          "description": "Analyze the document request and produce a structured Document Blueprint JSON",
          "type": "CHILD_ENTITY_INVOCATION",
          "target": {"entity_id": "{{content_architect_id}}"}
        },
        {
          "step_id": "step_2", "order": 2,
          "name": "Visual Asset Creation",
          "description": "Generate all charts, diagrams, and images specified in the Blueprint",
          "type": "CHILD_ENTITY_INVOCATION",
          "target": {"entity_id": "{{visual_asset_creator_id}}", "input_dependencies": ["step_1"]}
        },
        {
          "step_id": "step_3", "order": 3,
          "name": "Document Rendering",
          "description": "Write and execute Python code to create the final document file",
          "type": "CHILD_ENTITY_INVOCATION",
          "target": {"entity_id": "{{document_renderer_id}}", "input_dependencies": ["step_1", "step_2"]}
        },
        {
          "step_id": "step_4", "order": 4,
          "name": "Quality Inspection",
          "description": "Convert document to images and inspect for visual defects",
          "type": "CHILD_ENTITY_INVOCATION",
          "target": {"entity_id": "{{quality_inspector_id}}", "input_dependencies": ["step_3"]}
        },
        {
          "step_id": "step_5", "order": 5,
          "name": "Revision",
          "description": "Apply targeted fixes for defects found by Quality Inspector",
          "type": "CHILD_ENTITY_INVOCATION",
          "target": {"entity_id": "{{revision_agent_id}}", "input_dependencies": ["step_3", "step_4"]},
          "required": false
        }
      ]
    },
    "dynamic_planning": {"enabled": false}
  },
  "capabilities": {
    "tools": [
      {"tool_id": "sandbox_code"},
      {"tool_id": "terminal"},
      {"tool_id": "image_generation"},
      {"tool_id": "document_save"}
    ],
    "meta_cognition": {
      "platform_awareness": false,
      "registry_search": false,
      "self_modification": false
    }
  },
  "logic_gate": {
    "reasoning_config": {
      "reasoning_mode": "REACT",
      "temperature": 0.3,
      "task_type": "text_generation"
    },
    "context_policy": {"type": "FULL"}
  },
  "governance": {
    "max_cost_usd": 5.00,
    "timeout_ms": 900000,
    "max_recursion_depth": 3
  }
}
```

### 3.2 Content Architect (AGENT)

**Tools:** None (pure LLM reasoning)  
**Reasoning:** REACT mode  
**Cost Cap:** $0.50  
**Timeout:** 60s

**Key system prompt directives:**
- Analyze the user's document request
- Determine format (PPTX/DOCX/XLSX/PDF)
- Produce a structured Document Blueprint JSON
- Include `visual_assets_needed` array for downstream Visual Asset Creator
- For PPTX: determine slide count, narrative arc, chart vs text vs image per slide
- For DOCX: determine chapter structure, tables, diagrams, callouts
- For XLSX: determine sheet structure, formula relationships, chart types
- For PDF: determine layout style, section flow, visual balance
- Select a theme from: `midnight_executive`, `forest_moss`, `coral_energy`, `charcoal_minimal`

**Output format:** Document Blueprint JSON (see architecture doc Section 3.2)

### 3.3 Visual Asset Creator (AGENT)

**Tools:** `sandbox_code`, `image_generation`, `terminal`  
**Reasoning:** REACT mode  
**Cost Cap:** $1.50  
**Timeout:** 300s

**Key system prompt directives:**
- Read `visual_assets_needed` array from Document Blueprint
- For `chart` type: write matplotlib/plotly Python code with theme colors, execute via sandbox
- For `diagram` type: write graphviz/matplotlib code for flowcharts, process diagrams, Gantt charts
- For `ai_image` type: call `image_generation` with detailed prompt
- For `icon` type: generate via `image_generation` or draw SVG via matplotlib
- Apply theme colors consistently across ALL assets
- Save all assets to sandbox temp dir with descriptive filenames
- Output: Asset manifest JSON with file paths

**Color palette injection per theme:**
```
midnight_executive: chart_colors = ['#7C3AED', '#3B82F6', '#10B981', '#F59E0B', '#EF4444']
forest_moss: chart_colors = ['#97BC62', '#4A7C4B', '#8FBC8F', '#556B2F', '#228B22']
coral_energy: chart_colors = ['#F96167', '#F9E795', '#FCB69F', '#FF6B6B', '#FFA07A']
charcoal_minimal: chart_colors = ['#36454F', '#5F6B7C', '#87919E', '#B0B8C1', '#D3D8DE']
```

### 3.4 Document Renderer (AGENT)

**Tools:** `sandbox_code`, `terminal`, `document_save`  
**Reasoning:** REACT mode  
**Cost Cap:** $1.50  
**Timeout:** 600s (user-specified `max_execution_seconds`)

**Key system prompt directives:**
- Receive Document Blueprint + Asset Manifest as input
- Write Python code using the appropriate library (python-pptx / python-docx / openpyxl / WeasyPrint)
- Apply design system rules strictly
- Embed visual assets from manifest paths
- For XLSX: use native charts for simple visuals, image fallback for complex ones
- Call `document_save` tool after successful generation

**Context Sources (DOCUMENT type) attached to this entity:**
1. `python_pptx_reference.md`
2. `python_docx_reference.md`
3. `openpyxl_reference.md`
4. `weasyprint_reference.md`

**Sandbox tool configuration:**
```json
{
  "tool_id": "sandbox_code",
  "max_execution_seconds": 600
}
```

### 3.5 Quality Inspector (AGENT)

**Tools:** `terminal`, `sandbox_code`  
**Reasoning:** REACT mode  
**Cost Cap:** $0.50  
**Timeout:** 120s

**Workflow:**
1. Determine file format from document path extension
2. Try LibreOffice conversion: `soffice --headless --convert-to pdf <file>`
3. Rasterize: `pdftoppm -jpeg -r 150 <pdf> slide`
4. Analyze images via Python heuristics:
   - Check dimensions consistency
   - Detect text overflow (large text near edges)
   - Detect empty placeholder areas
   - Check for missing visual elements
   - Verify all slides/pages have content
5. Produce QA Report JSON

**QA Report format:**
```json
{
  "status": "PASSED" | "FAILED",
  "defects_found": false | true,
  "defects": [
    {
      "page": 3,
      "type": "text_overflow",
      "description": "Title text extends beyond slide boundary on slide 3",
      "severity": "HIGH",
      "fix_suggestion": "Reduce title font size to 36pt or shorten text"
    }
  ],
  "document_stats": {
    "pages": 10,
    "file_size_bytes": 245760,
    "format": "pptx"
  }
}
```

**Fallback (no LibreOffice):** Structural validation only — file size > 0, verify expected sheets/slides/pages via library introspection.

### 3.6 Revision Agent (SKILL)

**Tools:** `sandbox_code`, `terminal`, `document_save`  
**Reasoning:** CHAIN_OF_THOUGHT  
**Cost Cap:** $0.50  
**Timeout:** 300s

**Key behaviors:**
- Receive document path + QA defect report as input
- Write Python code that opens the document and applies targeted fixes
- Common fix patterns:
  - Text overflow → reduce font size, truncate text
  - Missing image → re-embed or use placeholder
  - Empty slide → add descriptive content
  - Formatting inconsistency → apply theme colors
- Save updated file via `document_save`
- **One fix cycle only — never loop**

---

## 4. Design System Specification

### 4.1 Color Themes

```python
THEMES = {
    "midnight_executive": {
        "primary": "#1E2761",
        "accent": "#7C3AED",
        "text": "#1A1A2E",
        "bg": "#FFFFFF",
        "chart_colors": ["#7C3AED", "#3B82F6", "#10B981", "#F59E0B", "#EF4444"],
        "table_header_bg": "#1E2761",
        "table_header_text": "#FFFFFF",
        "table_band_color": "#F3F0FF",
    },
    "forest_moss": {
        "primary": "#2C5F2D",
        "accent": "#97BC62",
        "text": "#1B1B1B",
        "bg": "#FFFFFF",
        "chart_colors": ["#97BC62", "#4A7C4B", "#8FBC8F", "#556B2F", "#228B22"],
        "table_header_bg": "#2C5F2D",
        "table_header_text": "#FFFFFF",
        "table_band_color": "#F0F5E8",
    },
    "coral_energy": {
        "primary": "#F96167",
        "accent": "#F9E795",
        "text": "#2F3C7E",
        "bg": "#FFFFFF",
        "chart_colors": ["#F96167", "#F9E795", "#FCB69F", "#FF6B6B", "#FFA07A"],
        "table_header_bg": "#2F3C7E",
        "table_header_text": "#FFFFFF",
        "table_band_color": "#FFF5F5",
    },
    "charcoal_minimal": {
        "primary": "#36454F",
        "accent": "#F2F2F2",
        "text": "#212121",
        "bg": "#FFFFFF",
        "chart_colors": ["#36454F", "#5F6B7C", "#87919E", "#B0B8C1", "#D3D8DE"],
        "table_header_bg": "#36454F",
        "table_header_text": "#FFFFFF",
        "table_band_color": "#F5F5F5",
    },
}
```

### 4.2 Typography Rules

#### PPTX
| Element | Font | Size | Weight | Max Lines |
|---------|------|------|--------|-----------|
| Title | Inter/Arial | 44pt | Bold | 2 |
| Subtitle | Inter/Arial | 24pt | Regular | 2 |
| Body | Inter/Arial | 18pt | Regular | 6 |
| Caption | Inter/Arial | 14pt | Regular | 2 |
| Chart Labels | Inter/Arial | 12pt | Regular | — |

#### DOCX
| Style | Font | Size | Color |
|-------|------|------|-------|
| Title | Inter/Arial | 28pt | Theme primary |
| Heading 1 | Inter/Arial | 20pt | Theme primary |
| Heading 2 | Inter/Arial | 16pt | Theme accent |
| Heading 3 | Inter/Arial | 13pt | Theme text |
| Body Text | Georgia/Serif | 11pt | Theme text |
| Quote | Georgia/Serif | 11pt italic | Muted |
| Callout | Inter/Arial | 11pt | Theme accent bg |
| Table Header | Inter/Arial | 11pt bold | White on primary |

#### XLSX
| Element | Font | Size | Style |
|---------|------|------|-------|
| Header Row | Inter/Arial | 11pt | Bold, white on primary bg |
| Data Cells | Inter/Arial | 10pt | Regular |
| KPI Values | Inter/Arial | 24pt | Bold |
| Sheet Tab | — | — | Theme primary underline |

#### PDF (CSS)
| Element | Font Family | Size | Line Height |
|---------|------------|------|-------------|
| Body | Georgia, serif | 11pt | 1.6 |
| H1 | Inter, sans-serif | 20pt | 1.3 |
| H2 | Inter, sans-serif | 16pt | 1.3 |
| H3 | Inter, sans-serif | 13pt | 1.3 |
| Blockquote | Georgia, serif italic | 11pt | 1.5 |
| Code | DejaVu Sans Mono | 9pt | 1.4 |

### 4.3 Anti-Patterns (Enforced via System Prompts)

1. **No accent lines under titles** — looks dated
2. **No cream/beige default backgrounds** — use white or theme primary
3. **No text-only slides** — every slide needs a visual element (chart, image, icon, diagram)
4. **No repeating layouts** — consecutive slides must use different layout types
5. **Max 6 bullets per slide** — max 12 words per bullet
6. **No default library styling** — always apply custom colors, fonts, and spacing
7. **No tiny charts** — charts should fill at least 60% of slide area
8. **No unstyled Word tables** — always apply banded rows, header colors, borders
9. **No raw formula display in XLSX** — format numbers properly (`$#,##0`, `0.0%`)
10. **No orphan pages** — heading and following content must stay together

---

## 5. Document Blueprint JSON Schema

The Content Architect produces this schema. It's the contract between all downstream agents.

### PPTX Blueprint
```json
{
  "format": "pptx",
  "document_type": "pitch_deck",
  "theme": "midnight_executive",
  "slides": [
    {
      "order": 1,
      "type": "cover",
      "title": "Title Text",
      "subtitle": "Subtitle Text",
      "visual_need": {"type": "ai_image", "prompt": "Abstract AI neural network, dark navy gradient background"}
    },
    {
      "order": 2,
      "type": "data_chart",
      "title": "Revenue Trajectory",
      "chart": {"type": "bar", "data": {"Q1": 2.4, "Q2": 3.1, "Q3": 3.8, "Q4": 4.5}, "unit": "$M"},
      "talking_points": ["87.5% YoY growth", "Accelerating quarterly momentum"]
    },
    {
      "order": 3,
      "type": "kpi_grid",
      "title": "Key Metrics",
      "kpis": [
        {"label": "Customers", "value": "150", "icon": "users"},
        {"label": "Retention", "value": "95%", "icon": "repeat"},
        {"label": "ACV", "value": "$32K", "icon": "dollar"}
      ]
    }
  ],
  "visual_assets_needed": [
    {"id": "cover_bg", "type": "ai_image", "prompt": "..."},
    {"id": "revenue_chart", "type": "chart", "chart_type": "bar", "data": {}},
    {"id": "growth_diagram", "type": "diagram", "diagram_type": "process", "steps": []}
  ]
}
```

### DOCX Blueprint
```json
{
  "format": "docx",
  "document_type": "research_report",
  "theme": "midnight_executive",
  "sections": [
    {"type": "cover_page", "title": "Title", "subtitle": "Subtitle", "author": "Author"},
    {"type": "executive_summary", "style": "boxed", "content": "Summary text..."},
    {"type": "chapter", "heading": "Introduction", "level": 1, "paragraphs": [], "subsections": []},
    {"type": "data_section", "heading": "Analysis", "table": {"headers": [], "rows": []}, "orientation": "landscape"},
    {"type": "appendix", "heading": "Appendix A", "content": "..."}
  ],
  "visual_assets_needed": [
    {"id": "fig_1", "type": "chart", "chart_type": "line", "data": {}},
    {"id": "fig_2", "type": "diagram", "diagram_type": "flowchart", "nodes": []}
  ]
}
```

### XLSX Blueprint
```json
{
  "format": "xlsx",
  "document_type": "financial_model",
  "theme": "midnight_executive",
  "sheets": [
    {
      "name": "Assumptions",
      "purpose": "Input parameters",
      "type": "input_sheet",
      "cells": [{"ref": "B2", "label": "Revenue Growth Rate", "value": 0.15, "validation": "0-1"}],
      "visible": true
    },
    {
      "name": "Revenue Model",
      "purpose": "Revenue projections",
      "type": "calculation_sheet",
      "depends_on": ["Assumptions"],
      "key_formulas": ["=Assumptions!B2 * B5", "=SUMIFS(...)"]
    },
    {
      "name": "Dashboard",
      "purpose": "Summary with KPIs and charts",
      "type": "summary_sheet",
      "charts": [{"type": "line", "data_range": "Revenue Model!B2:M5", "title": "Revenue Trend"}],
      "kpis": [{"label": "ARR", "formula": "=Revenue Model!M2"}]
    }
  ],
  "visual_assets_needed": [
    {"id": "waterfall_chart", "type": "chart", "chart_type": "waterfall", "data_source": "P&L summary"}
  ]
}
```

### PDF Blueprint
```json
{
  "format": "pdf",
  "document_type": "magazine_report",
  "theme": "midnight_executive",
  "layout_style": "magazine",
  "sections": [
    {"type": "cover", "title": "Title", "subtitle": "Subtitle", "cover_image": "ai_image"},
    {"type": "toc", "auto_generated": true},
    {"type": "article", "heading": "Section Title", "layout": "two_column", "content": "..."},
    {"type": "pull_quote", "text": "Quote text", "attribution": "Author"},
    {"type": "full_bleed_image", "image": "diagram_1"}
  ],
  "visual_assets_needed": [
    {"id": "cover_image", "type": "ai_image", "prompt": "..."},
    {"id": "diagram_1", "type": "diagram", "diagram_type": "process", "format": "svg"}
  ]
}
```

---

## 6. Dependencies

### Python Packages (add to pyproject.toml)
```
matplotlib >= 3.8.0
Pillow >= 10.0.0
CairoSVG >= 2.7.0
xlsxwriter >= 3.1.0
```

### Already Installed
```
python-pptx >= 1.0.0  ✅
openpyxl >= 3.1.0     ✅
python-docx >= 1.1.0  ✅
weasyprint             ✅ (system package)
markdown               ✅
Jinja2                 ✅
```

### System Packages (Production VM)
```bash
apt-get install -y libreoffice-core poppler-utils fonts-inter fonts-noto
```

**Graceful degradation:** If `libreoffice` is missing, QA Inspector falls back to structural checks (file size, sheet/slide count via library introspection).

---

## 7. Sandbox Timeout Configuration

Per user answer to Q1: Set Document Renderer entity's tool config to `max_execution_seconds: 600`.

This is configured in the entity's `capabilities.tools` array:
```json
{
  "tool_id": "sandbox_code",
  "max_execution_seconds": 600
}
```

The `StepExecutorService._execute_tool_call()` method already reads `max_execution_seconds` from the entity's tool definitions and passes it to `SandboxCodeTool` via the `timeout_s` parameter.

---

## 8. Integration with Existing System

### Artifact Registration
All generated documents are registered via `ArtifactService.save_artifact()` with:
- `origin`: `system-generated`
- `file_category`: `documents`
- `generated_by`: `document-director`
- `purpose`: User-provided or auto-generated description

### Billing
Document generation costs are tracked through the standard execution run billing pipeline:
- LLM costs for Content Architect reasoning
- Image generation costs for Visual Asset Creator
- Sandbox execution costs for Document Renderer
- All rolled up to the parent SKILL's execution run via `run.total_cost_usd`

### Tool Management
The new `document_save` tool appears in the Tool Management UI alongside existing tools. It's categorized as `document` type and enabled by default.

### Entity Registry
All 6 entities appear in the Entity Registry UI. The Document Director is tagged with `["document-generation", "system", "premium"]` for easy discovery. The Meta-Agent can find and invoke it via `meta_registry_search`.

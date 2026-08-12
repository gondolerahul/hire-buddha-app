# Phase 8: Document Generation Toolkit — Agentic Architecture

**Status:** Architectural Proposal v2 — Entity-Native Design  
**Date:** 2026-05-12

---

## 1. Why V1 Was Wrong

V1 proposed static Python renderer classes — glorified library wrappers. That approach fails because:

1. **Unbounded complexity.** A mid-size company's financial model has 15+ interdependent sheets with INDEX/MATCH cascades, pivot summaries, scenario toggles, and conditional formatting. No pre-built renderer can anticipate this — only an intelligent agent that writes and executes code can.
2. **No visual intelligence.** Static code can't decide "this slide needs a process diagram" or "this data would be better as a scatter plot." That requires LLM reasoning.
3. **Ignores existing infrastructure.** The platform already has `sandbox_code` (Python execution), `terminal` (shell commands), `image_generation` (Gemini visual AI), and the entire PROCESS/AGENT/SKILL entity hierarchy with CHILD_ENTITY_INVOCATION. The document toolkit should BE a Hierarchical Entity workflow, not a parallel code library.

> **Core principle:** The AI agent writes the code that creates the document. The toolkit provides the intelligent workflow, design knowledge, and quality gates — not pre-built renderers.

---

## 2. Architecture: Document Director PROCESS Entity

```
┌───────────────────────────────────────────────────────────────────────┐
│              DOCUMENT DIRECTOR  (PROCESS Entity)                      │
│                                                                       │
│  Orchestrates 5 child agents via CHILD_ENTITY_INVOCATION              │
│  Dynamic planning enabled — adapts workflow to document complexity    │
│  Tools: sandbox_code, terminal, image_generation                      │
└──────┬──────┬──────┬──────┬──────┬────────────────────────────────────┘
       │      │      │      │      │
       ▼      ▼      ▼      ▼      ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ CONTENT  │ │ VISUAL   │ │ DOCUMENT │ │ QUALITY  │ │ REVISION │
│ ARCHI-   │ │ ASSET    │ │ RENDERER │ │ INSPEC-  │ │ AGENT    │
│ TECT     │ │ CREATOR  │ │          │ │ TOR      │ │          │
│ (AGENT)  │ │ (AGENT)  │ │ (AGENT)  │ │ (AGENT)  │ │ (SKILL)  │
│          │ │          │ │          │ │          │ │          │
│ Analyzes │ │ Generates│ │ Writes & │ │ Converts │ │ Targeted │
│ request, │ │ charts,  │ │ executes │ │ to image,│ │ fix of   │
│ produces │ │ diagrams,│ │ Python   │ │ inspects │ │ defects  │
│ Document │ │ images   │ │ code via │ │ for      │ │ found by │
│ Blueprint│ │ via code │ │ sandbox  │ │ defects  │ │ QA       │
│          │ │ + image  │ │          │ │          │ │          │
│          │ │ gen tool │ │          │ │          │ │          │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
    Step 1       Step 2       Step 3       Step 4       Step 5
```

### Why This Is Superior

| Aspect | V1 (Static Renderers) | V2 (Entity Workflow) |
|--------|----------------------|---------------------|
| Financial model XLSX | Pre-built formula set | Agent writes custom openpyxl code with arbitrary formulas, cross-sheet refs, scenarios |
| Visual decisions | Layout lookup table | LLM reasons about data → chooses chart types, diagram styles, image placement |
| Diagram generation | Missing | Dedicated agent writes matplotlib/graphviz code + uses image_generation tool |
| Quality assurance | Structural validator | Agent converts to image, inspects visually, decides if fix needed |
| Extensibility | Code changes needed | Update entity system prompts — zero code deploys |
| Complex PPTX | 5 fixed layouts | Agent writes python-pptx code for ANY layout the content demands |

---

## 3. Entity Definitions

### 3.1 Document Director (PROCESS)

```json
{
  "name": "Document Director",
  "type": "PROCESS",
  "description": "Orchestrates world-class document generation across PPTX, DOCX, XLSX, PDF",
  "goal": "Produce visually stunning, publication-quality documents by coordinating specialized child agents",
  "identity": {
    "role": "Creative Director & Production Manager",
    "system_prompt": "<<DOCUMENT_DIRECTOR_PROMPT>>"
  },
  "hierarchy": {
    "children": [
      {"child_id": "content_architect", "relationship": "SEQUENTIAL"},
      {"child_id": "visual_asset_creator", "relationship": "SEQUENTIAL"},
      {"child_id": "document_renderer", "relationship": "SEQUENTIAL"},
      {"child_id": "quality_inspector", "relationship": "SEQUENTIAL"},
      {"child_id": "revision_agent", "relationship": "CONDITIONAL",
       "condition": {"enabled": true, "expression": "quality_inspector.defects_found == true"}}
    ]
  },
  "planning": {
    "dynamic_planning": {"enabled": true},
    "static_plan": {
      "steps": [
        {"step_id": "step_1", "name": "Content Architecture", "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": "{{content_architect_id}}"}},
        {"step_id": "step_2", "name": "Visual Asset Creation", "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": "{{visual_asset_creator_id}}", "input_dependencies": ["step_1"]}},
        {"step_id": "step_3", "name": "Document Rendering", "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": "{{document_renderer_id}}", "input_dependencies": ["step_1", "step_2"]}},
        {"step_id": "step_4", "name": "Quality Inspection", "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": "{{quality_inspector_id}}", "input_dependencies": ["step_3"]}},
        {"step_id": "step_5", "name": "Revision", "type": "CHILD_ENTITY_INVOCATION",
         "target": {"entity_id": "{{revision_agent_id}}", "input_dependencies": ["step_3", "step_4"]},
         "required": false}
      ]
    }
  },
  "capabilities": {
    "tools": [
      {"tool_id": "sandbox_code"},
      {"tool_id": "terminal"},
      {"tool_id": "image_generation"}
    ]
  },
  "governance": {
    "max_cost_usd": 3.00,
    "timeout_ms": 300000
  }
}
```

### 3.2 Content Architect (AGENT)

**Purpose:** Analyzes the user request, determines document structure, produces a detailed **Document Blueprint** — a structured JSON specification of every section, its content, visual treatment, and data requirements.

**Key behaviors:**
- For PPTX: determines slide count, narrative arc, which slides need charts vs. text vs. images
- For DOCX: determines chapter structure, which sections need tables, diagrams, callouts
- For XLSX: determines sheet structure, formula relationships, what analysis to run, which charts to generate
- For PDF: determines layout style (report vs. magazine vs. invoice), section flow, visual balance

**Tools:** None (pure LLM reasoning). Uses REACT mode to think through the document structure.

**Output:** Document Blueprint JSON — the contract between all downstream agents.

```
Blueprint Example (XLSX - Financial Model):
{
  "format": "xlsx",
  "document_type": "financial_model",
  "theme": "midnight_executive",
  "sheets": [
    {"name": "Assumptions", "purpose": "Input parameters", "type": "input_sheet",
     "cells": [{"ref": "B2", "label": "Revenue Growth Rate", "value": 0.15, "validation": "0-1"}]},
    {"name": "Revenue Model", "purpose": "Revenue projections", "type": "calculation_sheet",
     "depends_on": ["Assumptions"],
     "key_formulas": ["=Assumptions!B2 * B5", "=SUMIFS(...)"]},
    {"name": "P&L", "depends_on": ["Revenue Model", "Cost Model"]},
    {"name": "Dashboard", "type": "summary_sheet",
     "charts": [{"type": "line", "data_range": "Revenue Model!B2:M5", "title": "Revenue Trend"}],
     "kpis": [{"label": "ARR", "formula": "=Revenue Model!M2"}]}
  ],
  "visual_assets_needed": [
    {"type": "chart", "chart_type": "waterfall", "data_source": "P&L summary"},
    {"type": "chart", "chart_type": "line", "data_source": "Revenue trend"}
  ]
}
```

### 3.3 Visual Asset Creator (AGENT)

**Purpose:** Generates all visual assets needed by the document — charts, diagrams, AI-generated images, icons, backgrounds.

**Tools:**
- `sandbox_code` — writes matplotlib/plotly/graphviz Python code to render charts and diagrams as PNG/SVG files
- `image_generation` — uses Gemini image generation for cover backgrounds, conceptual illustrations, branded imagery
- `terminal` — for format conversion (e.g., SVG→PNG via CairoSVG, Mermaid CLI)

**Key behaviors:**
- Reads the Document Blueprint's `visual_assets_needed` array
- For each chart: writes Python code using matplotlib with the theme's color palette, executes via sandbox, saves PNG
- For each diagram: writes graphviz/matplotlib code for flowcharts, process diagrams, org charts, Gantt charts
- For AI images: calls `image_generation` with detailed prompts for cover art, backgrounds, conceptual visuals
- Applies theme colors consistently across ALL assets
- Saves all assets to the artifact directory with descriptive filenames

**Output:** Asset manifest — list of file paths for every generated visual asset.

### 3.4 Document Renderer (AGENT) — The Core Innovation

**Purpose:** Writes and executes Python code that creates the actual document file using the appropriate library.

**This is the critical architectural decision.** Instead of pre-built renderer classes, the AI agent dynamically writes Python code tailored to the exact document being created. This means:

- For a simple 5-slide pitch deck: writes ~80 lines of python-pptx code
- For a complex 15-sheet financial model: writes ~400 lines of openpyxl code with SUMIFS, INDEX/MATCH, conditional formatting, cross-sheet references, named ranges, data validation dropdowns
- For a magazine-style PDF: writes HTML+CSS with Jinja2, then calls WeasyPrint
- For a styled report DOCX: writes python-docx code with custom styles, section breaks, embedded images

**Tools:**
- `sandbox_code` — executes the generated Python code
- `terminal` — for pip installs if needed, file operations

**System prompt includes:**

1. **Library reference guides** — concise API summaries for python-pptx, python-docx, openpyxl, WeasyPrint
2. **Design System rules** — color palettes, typography specs, spacing rules, anti-pattern list
3. **The Document Blueprint** (from Step 1) — what to build
4. **The Asset Manifest** (from Step 2) — paths to all visual assets to embed

**Key design rules injected into the Renderer's system prompt:**

```markdown
## Design System — MANDATORY Rules

### Color Palettes (use by theme name)
- midnight_executive: primary=#1E2761, accent=#7C3AED, text=#1A1A2E, chart_colors=[#7C3AED, #3B82F6, #10B981, #F59E0B, #EF4444]
- forest_moss: primary=#2C5F2D, accent=#97BC62, text=#1B1B1B
- coral_energy: primary=#F96167, accent=#F9E795, text=#2F3C7E
- charcoal_minimal: primary=#36454F, accent=#F2F2F2, text=#212121

### Typography (PPTX)
- Title: 44pt bold, Inter/Arial
- Subtitle: 24pt regular
- Body: 18pt, max 6 lines per slide body
- Caption: 14pt, muted color

### Anti-Patterns — NEVER DO THESE
- No accent lines under titles
- No cream/beige default backgrounds
- No text-only slides (every slide needs a visual element)
- No repeating the same layout on consecutive slides
- Max 6 bullets per slide, max 12 words per bullet
- No default library styling (always apply custom colors and fonts)

### XLSX Specific
- Always freeze top row
- Always auto-fit column widths
- Always use banded rows with theme colors
- Header row: bold white text on primary color background
- Validate all formulas before writing
- Use named ranges for key assumptions
```

### 3.5 Quality Inspector (AGENT)

**Purpose:** Converts the generated document to images and inspects for visual defects.

**Tools:**
- `terminal` — runs LibreOffice headless conversion (`soffice --convert-to pdf`) and `pdftoppm` for rasterization
- `sandbox_code` — runs Python image analysis (check dimensions, detect text overflow via OCR-free heuristics)

**Workflow:**
1. Convert document to PDF via LibreOffice (for PPTX/DOCX/XLSX) or direct (for PDF)
2. Rasterize each page to PNG via `pdftoppm -jpeg -r 150`
3. Analyze images for: overflow, overlap, low contrast, missing content, empty areas, margin violations
4. Produce a **QA Report** — pass/fail with specific defect descriptions and page numbers

**If LibreOffice is not available:** Falls back to structural validation only (check file size > 0, verify expected sheets/slides/pages exist via library introspection).

### 3.6 Revision Agent (SKILL — Conditional)

**Purpose:** If QA finds defects, makes targeted fixes. Runs ONE cycle only.

**Tools:** `sandbox_code`, `terminal`

**Input:** The original document path + the QA defect report  
**Behavior:** Writes Python code that opens the document, fixes the specific defects identified (text overflow → reduce font size, missing image → re-embed, etc.), saves updated file.

**Policy:** One fix cycle, then stop. No infinite loops.

---

## 4. Deep Dive: XLSX Complexity

The user's insight about Excel complexity is critical. A real financial model looks like:

```
Sheet: Assumptions
├── Revenue growth rate (B2) = 15%
├── Churn rate (B3) = 5%
├── CAC (B4) = $500
└── Data validation dropdowns for scenario selection

Sheet: Revenue Model
├── Monthly revenue (B2:M2) = Previous * (1 + Assumptions!$B$2/12)
├── Customer count (B3:M3) = Previous * (1 - Assumptions!$B$3/12) + New
├── New customers (B4:M4) = Marketing spend / Assumptions!$B$4
└── SUMIFS for quarterly rollups

Sheet: Cost Model
├── COGS (B2:M2) = Revenue Model!B2 * 0.3
├── S&M (B3:M3) = =IF(Revenue Model!B2>1000000, B2*0.2, B2*0.35)
├── R&D (B4:M4) = Fixed + Variable
└── Cross-references to headcount model

Sheet: P&L
├── Revenue = =Revenue Model!B2
├── Gross Margin = Revenue - COGS
├── EBITDA = Gross Margin - OpEx
└── Conditional formatting: red for negative, green for positive

Sheet: Dashboard
├── KPI cards with LARGE font: ARR, MRR, Burn Rate, Runway
├── Native Excel charts: Revenue trend (line), Cost breakdown (stacked bar), Unit economics (scatter)
├── Conditional formatting: data bars for progress, color scales for heatmap
└── Freeze panes, hidden raw data sheet
```

**No pre-built renderer can handle this.** The Content Architect must understand the domain, the Renderer must write sophisticated openpyxl code with:
- Named ranges (`wb.defined_names.new("GrowthRate", attr_text="Assumptions!$B$2")`)
- Cross-sheet formulas (`ws["B2"] = "=Revenue Model!B2"`)
- Data validation (`DataValidation(type="list", formula1='"Base,Upside,Downside"')`)
- Conditional formatting with color scales and data bars
- Native chart objects (`BarChart`, `LineChart`) with themed colors
- Number formatting (`'$#,##0'`, `'0.0%'`, `'#,##0;(#,##0);"-"'`)

The agent writes this code dynamically, executes it in the sandbox, and produces the file.

---

## 5. Deep Dive: Diagram & Image Generation Pipeline

### Step 2 (Visual Asset Creator) Workflow

```
For each asset in Blueprint.visual_assets_needed:

  IF type == "chart":
    → Write matplotlib/plotly Python code with theme colors
    → Execute via sandbox_code
    → Save PNG to artifact dir
    → Record path in asset manifest

  IF type == "diagram" (flowchart, process, org_chart, gantt):
    → Write graphviz DOT or matplotlib code
    → Execute via sandbox_code
    → Save PNG/SVG to artifact dir

  IF type == "ai_image" (cover, background, conceptual):
    → Call image_generation tool with detailed prompt
    → Prompt includes theme colors, style direction
    → Save path from tool response to asset manifest

  IF type == "icon":
    → Generate via image_generation with "flat icon" prompt
    → OR use sandbox to draw simple SVG icons with matplotlib
```

### Example: Agent-Generated Chart Code

The Visual Asset Creator would use `sandbox_code` to execute:

```python
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

# Theme: midnight_executive
colors = ['#7C3AED', '#3B82F6', '#10B981', '#F59E0B', '#EF4444']
bg_color = '#FFFFFF'
text_color = '#1A1A2E'

fig, ax = plt.subplots(figsize=(10, 6))
fig.patch.set_facecolor(bg_color)
ax.set_facecolor(bg_color)

categories = ['Q1', 'Q2', 'Q3', 'Q4']
values = [2.4, 3.1, 3.8, 4.5]

bars = ax.bar(categories, values, color=colors[0], width=0.6, edgecolor='none')
ax.set_title('Quarterly Revenue ($M)', fontsize=16, fontweight='bold', color=text_color, pad=20)
ax.spines[['top', 'right']].set_visible(False)
ax.spines[['bottom', 'left']].set_color('#E5E7EB')
ax.tick_params(colors=text_color)
ax.yaxis.set_major_formatter('${x:.1f}M')

for bar, val in zip(bars, values):
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.1,
            f'${val:.1f}M', ha='center', va='bottom', fontweight='bold', color=text_color)

plt.tight_layout()
plt.savefig('/tmp/sandbox/chart_revenue.png', dpi=200, bbox_inches='tight')
print('/tmp/sandbox/chart_revenue.png')
```

---

## 6. What Stays As Tools (Not Entities)

Only thin **file-save + artifact-registration** utilities remain as tools. The old `pptx_tool`, `docx_tool`, `excel_tool`, and `pdf_generator` are **kept as-is for backward compatibility** with simpler use cases. The Document Director PROCESS is the new primary path for quality output.

New utility tool added:

```python
class DocumentSaveTool(Tool):
    """Saves a generated document file to the artifact system.
    
    Used by the Document Renderer agent after sandbox_code creates the file.
    Copies from sandbox temp dir to artifact storage, registers in DB.
    """
    name = "document_save"
    description = (
        "Save a document file to the artifact system. Input: JSON with "
        "'source_path' (path to file in sandbox), 'filename', 'format' "
        "(pptx/docx/xlsx/pdf), and optional 'purpose'."
    )
```

---

## 7. Design System — Injected as Context, Not Code

The design system lives as **reference content in the entity system prompts**, not as Python classes. This is critical because:

1. The LLM needs to understand design rules to write good code
2. System prompts can be updated without code deploys
3. Different document types can have different design guidance

### Design System Injection Points

| Entity | What's injected | How |
|--------|----------------|-----|
| Content Architect | Document structure templates, narrative patterns | System prompt |
| Visual Asset Creator | Color palettes, chart styling rules, diagram conventions | System prompt |
| Document Renderer | Full API reference for python-pptx/docx/openpyxl/weasyprint + design rules | System prompt + context source (DOCUMENT type) |
| Quality Inspector | Visual defect checklist, quality standards | System prompt |

### Library Quick-Reference Documents

Uploaded as **Context Sources** (DOCUMENT type) attached to the Document Renderer entity. These are concise API guides (~5-10 pages each) covering:

1. **python-pptx Quick Reference** — slide layouts, shapes, text frames, charts, images, gradients, EMU units
2. **python-docx Quick Reference** — styles, tables, sections, headers/footers, images, page setup
3. **openpyxl Quick Reference** — worksheets, formulas, charts, conditional formatting, data validation, named ranges, styles
4. **WeasyPrint Quick Reference** — @page rules, CSS Grid, font-face, bookmarks, page breaks, counters

These documents ensure the Renderer agent writes correct library code without hallucinating APIs.

---

## 8. Execution Flow Example: Investor Pitch Deck

```
User: "Create a 10-slide investor pitch deck for our AI SaaS startup.
       Revenue: Q1=$2.4M, Q2=$3.1M, Q3=$3.8M, Q4=$4.5M.
       We have 150 customers, 95% retention, $32K ACV."

═══════════════════════════════════════════════════════════
STEP 1: Content Architect (AGENT, REACT mode)
═══════════════════════════════════════════════════════════

Turn 1 (THOUGHT): "Investor pitch deck needs: Cover, Problem, Solution,
Market, Traction, Business Model, Team, Competition, Financials, Ask.
The data points suggest strong growth narrative."

Turn 2 (ACTION): Produces Document Blueprint JSON:
{
  "format": "pptx",
  "theme": "midnight_executive",
  "slides": [
    {"type": "cover", "title": "AI SaaS — Scaling Revenue Without Headcount",
     "visual_need": {"type": "ai_image", "prompt": "Abstract AI neural network, dark navy..."}},
    {"type": "data_chart", "title": "Revenue Trajectory",
     "chart": {"type": "bar", "data": {"Q1": 2.4, "Q2": 3.1, "Q3": 3.8, "Q4": 4.5}}},
    {"type": "kpi_grid", "title": "Key Metrics",
     "kpis": [{"label": "Customers", "value": "150"}, {"label": "Retention", "value": "95%"}, ...]},
    ...
  ],
  "visual_assets_needed": [
    {"id": "cover_bg", "type": "ai_image", "prompt": "..."},
    {"id": "revenue_chart", "type": "chart", "chart_type": "bar", ...},
    {"id": "growth_diagram", "type": "diagram", "diagram_type": "process", ...}
  ]
}

═══════════════════════════════════════════════════════════
STEP 2: Visual Asset Creator (AGENT, REACT mode)
═══════════════════════════════════════════════════════════

Turn 1: Calls image_generation → generates cover background image
Turn 2: Calls sandbox_code → executes matplotlib code for revenue bar chart
Turn 3: Calls sandbox_code → executes matplotlib code for process diagram
Turn 4 (ACTION): Returns asset manifest:
{
  "assets": [
    {"id": "cover_bg", "path": "/tmp/sandbox/.../cover_bg.png"},
    {"id": "revenue_chart", "path": "/tmp/sandbox/.../revenue_chart.png"},
    {"id": "growth_diagram", "path": "/tmp/sandbox/.../growth_diagram.png"}
  ]
}

═══════════════════════════════════════════════════════════
STEP 3: Document Renderer (AGENT, REACT mode)
═══════════════════════════════════════════════════════════

Turn 1 (THOUGHT): "I have the blueprint and assets. I'll write python-pptx
code for a 10-slide deck with gradient backgrounds, themed charts, and
embedded images."

Turn 2: Calls sandbox_code with ~150 lines of python-pptx code:
  - Creates presentation with 13.333x7.5 inch slides
  - Slide 1: Cover with gradient background shape + title overlay
  - Slide 2: Revenue chart embedded as image + native chart backup
  - Slide 3: KPI grid using precisely positioned text boxes
  - Applies Inter font, midnight_executive colors throughout
  - Saves to /tmp/sandbox/.../pitch_deck.pptx

Turn 3: Calls document_save to register artifact

═══════════════════════════════════════════════════════════
STEP 4: Quality Inspector (AGENT)
═══════════════════════════════════════════════════════════

Turn 1: Calls terminal → soffice --convert-to pdf pitch_deck.pptx
Turn 2: Calls terminal → pdftoppm -jpeg -r 150 pitch_deck.pdf slide
Turn 3: Calls sandbox_code → Python script checks each image:
  - Dimensions consistent? ✅
  - Text areas not exceeding boundaries? ✅
  - All slides have visual elements? ✅
  - No empty placeholder content? ✅
Turn 4 (ACTION): QA Report: PASSED, 0 defects

═══════════════════════════════════════════════════════════
STEP 5: Revision Agent — SKIPPED (QA passed)
═══════════════════════════════════════════════════════════

Result: pitch_deck.pptx registered in Artifact DB, path returned to user.
```

---

## 9. Dependencies & Infrastructure

### Python Packages (to install)

```bash
pip install python-pptx openpyxl xlsxwriter matplotlib Pillow CairoSVG
```

(`python-docx`, `weasyprint`, `markdown`, `Jinja2` already installed)

### System Packages (for QA pipeline)

```bash
apt-get install -y libreoffice-core poppler-utils fonts-inter fonts-noto
```

**Graceful degradation:** If LibreOffice is missing, QA Inspector falls back to structural checks only (file size, sheet/slide count verification via library introspection).

---

## 10. Implementation Plan

### Phase 8.1: Foundation (2 days)
- [ ] Create `document_save` utility tool
- [ ] Create library quick-reference documents (4 files) for Context Sources
- [ ] Install dependencies on production VM
- [ ] Write design system content (themes, rules, anti-patterns) as injectable text

### Phase 8.2: Entity Definitions (3 days)
- [ ] Define & seed Document Director PROCESS entity with system prompt
- [ ] Define & seed Content Architect AGENT with system prompt + few-shot examples
- [ ] Define & seed Visual Asset Creator AGENT with system prompt
- [ ] Define & seed Document Renderer AGENT with system prompt + library context sources
- [ ] Define & seed Quality Inspector AGENT with system prompt
- [ ] Define & seed Revision SKILL with system prompt

### Phase 8.3: System Prompt Engineering (3-4 days)
- [ ] Content Architect: blueprint JSON schema examples for each format
- [ ] Visual Asset Creator: matplotlib/graphviz code templates, image_generation prompt templates
- [ ] Document Renderer: complete library API reference, design rules, code examples per format
- [ ] Quality Inspector: defect checklist, rasterization workflow
- [ ] Test each agent independently with sample inputs

### Phase 8.4: Integration & Testing (3-4 days)
- [ ] End-to-end test: PPTX pitch deck
- [ ] End-to-end test: DOCX research report with tables, diagrams, cover page
- [ ] End-to-end test: XLSX financial model (multi-sheet, formulas, charts)
- [ ] End-to-end test: PDF magazine-style report with SVG diagrams
- [ ] Tune sandbox timeout (30s default may need increase for complex renders)
- [ ] Verify artifact registration and billing

### Phase 8.5: Polish (2 days)
- [ ] Add more document type templates to Content Architect (invoice, proposal, dashboard)
- [ ] Add fallback path if sandbox fails (retry with simpler code)
- [ ] Documentation and usage guide for entity operators

**Total: ~13-15 days**

---

## 11. Open Questions

### Q1: Sandbox timeout for complex documents?
Complex financial models may take >30s to generate. **Recommendation:** Set Document Renderer entity's tool config to `max_execution_seconds: 120`.

### Q2: Should the Renderer attempt native Excel charts or only image-based?
Native Excel charts (via openpyxl.chart) are editable but limited in styling. Image-based charts (matplotlib) look better but aren't editable. **Recommendation:** Use native for simple charts, image fallback for complex/styled visuals. Let the Content Architect decide per chart.

### Q3: Font availability?
Google Fonts (Inter, Noto) must be installed for WeasyPrint and for python-pptx to embed them. **Recommendation:** Install `fonts-inter` and `fonts-noto` system packages. Fallback to DejaVu Sans.

### Q4: Should the old basic tools (pptx_tool, docx_tool, etc.) be deprecated?
**Recommendation:** Keep them for simple/quick use cases. The Document Director is the premium path. Agents can choose which to use based on complexity.

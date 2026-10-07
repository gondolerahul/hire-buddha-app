# Phase 8: McKinsey-Quality Document Generation Architecture

**Status:** Finalized Architecture  
**Date:** 2026-05-13  
**Scope:** Unified rendering pipeline for PDF, PPTX, DOCX, XLSX

---

## Finalized Rendering Pipeline

```
┌────────────────────────────────────────────────────────────────────────┐
│                     DOCUMENT DIRECTOR (PROCESS)                        │
│                                                                        │
│  step_1: Content Architect → Document Blueprint JSON                   │
│  step_2: Visual Asset Creator → Charts (matplotlib), Diagrams (SVG),   │
│          AI Images (image_generation)                                   │
│  step_3: Document Renderer → FORMAT-SPECIFIC RENDERING (below)         │
│  step_4: Quality Inspector → Visual QA via Gemini Vision               │
│  step_5: Revision Agent → Targeted fixes (conditional)                 │
└────────────────────────────────────────────────────────────────────────┘
```

### Format-Specific Rendering (Step 3)

| Format | Rendering Pipeline | Tool | Output |
|--------|-------------------|------|--------|
| **PDF** | LLM → HTML/CSS → Playwright `page.pdf()` | `sandbox_code` + `terminal` | Publication-quality PDF |
| **PPTX** | LLM → Node.js script → PptxGenJS | `terminal` (`node generate.js`) | Editable native PPTX |
| **DOCX** | LLM → HTML/CSS → pandoc `--to=docx` | `sandbox_code` + `terminal` | Editable Word document |
| **XLSX** | LLM → Python openpyxl code via XlsxEngine | `sandbox_code` | Styled spreadsheet |

---

## Architecture Details by Format

### PDF: HTML/CSS → Playwright

```
Blueprint JSON
    │
    ▼
Document Renderer writes HTML/CSS string via sandbox_code
    │  - CSS @page rules (A4, margins, page numbers)
    │  - CSS Grid/Flexbox layouts
    │  - Embedded chart PNGs via file:// URLs
    │  - Inline SVG diagrams
    │  - Professional typography (Inter/Georgia)
    │  - Cover page with gradient overlay
    │  - print-color-adjust: exact
    ▼
sandbox_code: save HTML to /tmp/sandbox/output/report.html
    │
    ▼
terminal: playwright-based PDF generation
    │  python -c "
    │    from playwright.sync_api import sync_playwright
    │    with sync_playwright() as p:
    │      browser = p.chromium.launch()
    │      page = browser.new_page()
    │      page.goto('file:///tmp/sandbox/output/report.html')
    │      page.pdf(path='/tmp/sandbox/output/report.pdf',
    │               print_background=True,
    │               prefer_css_page_size=True)
    │  "
    ▼
/tmp/sandbox/output/report.pdf → document_save
```

**Why Playwright over WeasyPrint:** Full Chromium engine — supports CSS Grid, Flexbox, `calc()`, `backdrop-filter`, complex gradients, and all modern CSS. WeasyPrint remains as fallback.

---

### PPTX: PptxGenJS via Terminal

```
Blueprint JSON
    │
    ▼
Document Renderer writes /tmp/sandbox/output/generate_pptx.js
    │  
    │  const pptxgen = require("pptxgenjs");
    │  const pres = new pptxgen();
    │  
    │  // Define Slide Master with theme
    │  pres.defineSlideMaster({
    │    title: "BRANDED",
    │    background: { color: "1E2761" },
    │    objects: [
    │      { text: { text: "COMPANY", options: { x: 0.5, y: 7, fontSize: 8 }}}
    │    ]
    │  });
    │  
    │  // Cover slide
    │  let slide1 = pres.addSlide();
    │  slide1.background = { fill: "1E2761" };
    │  slide1.addText("Title", { x: 1, y: 2, w: 8, fontSize: 44, bold: true,
    │                             color: "FFFFFF", align: "center" });
    │  
    │  // Data slide with native chart (editable in PowerPoint!)
    │  let slide2 = pres.addSlide();
    │  slide2.addChart(pres.charts.BAR, chartData, { x: 1, y: 1.5, w: 8, h: 4 });
    │  
    │  // Table slide
    │  let slide3 = pres.addSlide();
    │  slide3.addTable(rows, { border: { pt: 1 }, colW: [2,3,2] });
    │  
    │  // Embedded images (chart PNGs from Visual Asset Creator)
    │  slide4.addImage({ path: "/tmp/sandbox/output/revenue_chart.png",
    │                    x: 1, y: 1.5, w: 8, h: 4.5 });
    │  
    │  pres.writeFile({ fileName: "/tmp/sandbox/output/presentation.pptx" });
    ▼
terminal: "cd /tmp/sandbox/output && npm init -y && npm install pptxgenjs && node generate_pptx.js"
    │
    ▼
/tmp/sandbox/output/presentation.pptx → document_save
```

**Key PptxGenJS advantages:**
- Native editable charts (bar, line, pie, doughnut) — not image screenshots
- Slide Masters for consistent branding
- SVG support
- Tables with built-in styling
- 3,500+ GitHub stars, MIT license

**Replaces:** `pptx_engine.py` (python-pptx) and `pptx_tool.py` (legacy wrapper)

---

### DOCX: HTML/CSS → pandoc

```
Blueprint JSON
    │
    ▼
Document Renderer writes HTML/CSS string via sandbox_code
    │  - Same HTML/CSS approach as PDF
    │  - Semantic HTML: <h1>, <h2>, <p>, <table>, <ul>, <img>
    │  - CSS for styling (fonts, colors, spacing)
    │  - Embedded chart images
    ▼
sandbox_code: save HTML to /tmp/sandbox/output/report.html
    │
    ▼
terminal: "pandoc /tmp/sandbox/output/report.html -o /tmp/sandbox/output/report.docx \
           --from=html --to=docx --reference-doc=brand_template.docx"
    │
    │  --reference-doc applies a branded Word template with:
    │  - Custom heading styles (themed colors)
    │  - Body font (Calibri 11pt)
    │  - Table styles
    │  - Page margins and headers/footers
    ▼
/tmp/sandbox/output/report.docx → document_save
```

**Note:** A `brand_template.docx` reference document can be created once with proper Word styles. Pandoc maps HTML headings/tables to the template's styles automatically.

---

### XLSX: XlsxEngine via sandbox_code

```
Blueprint JSON
    │
    ▼
Document Renderer writes Python code using XlsxEngine helpers
    │  
    │  from xlsx_engine import XlsxEngine
    │  engine = XlsxEngine(theme="midnight_executive")
    │  
    │  # Dashboard sheet
    │  ws = engine.add_sheet("Dashboard", columns, data)
    │  engine.add_kpi_card(ws, "B2", "Revenue", "$4.2M", "$#,##0")
    │  engine.add_native_chart(ws, "bar", "D2:G12", "Revenue by Quarter")
    │  engine.setup_dashboard(ws)  # freeze panes, hide gridlines
    │  
    │  # Data sheet
    │  ws2 = engine.add_sheet("Raw Data", columns, data)
    │  engine.apply_theme(ws2)  # banded rows, header colors
    │  engine.format_currency(ws2, "C2:C100")
    │  engine.add_conditional_format(ws2, "D2:D100", "color_scale")
    │  
    │  engine.save("/tmp/sandbox/output/workbook.xlsx")
    ▼
sandbox_code executes Python code
    │
    ▼
/tmp/sandbox/output/workbook.xlsx → document_save
```

**XlsxEngine is a new Python helper library** (openpyxl-based) providing themed styling functions. The LLM uses it like PptxEngine was used before.

---

## Current System State

### Entity Pipeline (✅ Deployed in DB)

| Entity | Type | Status |
|--------|------|--------|
| Document Director | PROCESS | ✅ Active |
| Content Architect | AGENT | ✅ Active |
| Visual Asset Creator | AGENT | ✅ Active |
| Document Renderer | AGENT | ✅ Active |
| Quality Inspector | AGENT | ✅ Active |
| Revision Agent | SKILL | ✅ Active |

### Infrastructure Status

| Dependency | Status | Action Needed |
|-----------|--------|---------------|
| Node.js v20 + npm 10.8 | ✅ Installed | — |
| PptxGenJS | ❌ Not installed | `npm install pptxgenjs` (per-execution in sandbox) |
| Playwright + Chromium | ❌ Not installed | `pip install playwright && playwright install chromium` |
| pandoc | ❌ Not installed | `apt-get install pandoc` |
| WeasyPrint | ✅ Installed | Fallback for PDF |
| python-pptx | ✅ Installed | Being replaced by PptxGenJS |
| openpyxl | ✅ Installed | Used by XlsxEngine |
| python-docx | ✅ Installed | Replaced by pandoc for new pipeline |

### Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `backend/src/ai/tools/xlsx_engine.py` | **CREATE** | Deterministic XLSX rendering engine |
| `backend/db-scripts/document_toolkit_prompts.py` | **MODIFY** | Update Document Renderer prompt with PptxGenJS + Playwright + pandoc patterns |
| `backend/db-scripts/pptxgenjs_reference.md` | **CREATE** | PptxGenJS API quick-reference for context injection |
| `docs/phase8/context_sources/pptxgenjs_reference.md` | **CREATE** | PptxGenJS API docs for context_sources |
| `backend/src/ai/tools/pptx_engine.py` | **DEPRECATE** | Replaced by PptxGenJS |
| `backend/src/ai/tools/pptx_tool.py` | **DEPRECATE** | Legacy wrapper, no longer needed |

---

## Deep Research Integration

The Deep Research pipeline currently uses `pdf_generator` tool directly. To upgrade:

**Recommended approach:** Replace the `pdf_generator` TOOL_CALL in the Knowledge Synthesizer with either:
- A `CHILD_ENTITY_INVOCATION` to Document Director (maximum quality, higher cost)
- A `sandbox_code` call that writes HTML + runs Playwright (fast, deterministic)

The second approach is preferred for Deep Research since the content is already written — the Content Architect step adds no value.

---

## Quality Assurance: Vision QA Loop

The Quality Inspector should be upgraded to use Gemini Vision:

```
Generated document
    │
    ▼
terminal: soffice --headless --convert-to pdf → pdftoppm → PNG pages
    │
    ▼
sandbox_code: send PNG to Gemini Vision API
    │  "You are a senior graphic designer at McKinsey.
    │   Rate this document page 1-10 for:
    │   - Visual hierarchy and readability
    │   - Professional typography and spacing
    │   - Chart/table quality
    │   - Overall polish
    │   List specific defects with fix suggestions."
    │
    ▼
QA Report JSON → Revision Agent (if defects found)
```

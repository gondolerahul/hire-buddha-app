# Building World-Class Document Production Tools for AI Agents

---

## The Core Architecture

Your agents need three things for each format: the right **library**, a **design system baked into the prompt**, and a **visual QA loop**. Without the QA loop, output quality degrades unpredictably.

---

## Format-by-Format Stack

### PowerPoint (.pptx)

Use `pptxgenjs` (Node.js) for creation from scratch, or XML manipulation via unpack/repack for editing existing decks. Design quality lives almost entirely in your system prompt — color palettes, typography rules, layout patterns, and explicit anti-patterns (e.g. *"never use accent lines under titles — it signals AI output"*).

### Word (.docx)

Use the `docx` npm library. Critical gotchas to bake in:

- Always set page size explicitly (defaults to A4, not Letter)
- Never use unicode bullets — use `LevelFormat.BULLET` with numbering config
- Use `ShadingType.CLEAR` not `SOLID` for table cell shading
- Always set dual widths on tables: both `columnWidths` array AND per-cell `width`

### Excel (.xlsx)

Use `openpyxl` (Python) or `SheetJS` (JS). Style aggressively: header rows, alternating row colors, column width auto-sizing, and freeze panes are the difference between "AI output" and professional deliverables.

### PDF

Two paths:

- **`reportlab`** — for pixel-precise layouts (great for reports, invoices)
- **Via another format** — generate docx/pptx first, then convert via LibreOffice → PDF for document-style output

> **Never use Unicode sub/superscripts in reportlab** — they render as solid black boxes. Use `<sub>` and `<super>` XML tags inside `Paragraph` objects instead.

---

## The QA Loop (Non-Negotiable)

The single biggest quality multiplier is **converting output to images and visually inspecting them**. Every format supports this:

```bash
# Convert to PDF first (works for pptx, docx, xlsx)
python scripts/office/soffice.py --headless --convert-to pdf output.pptx

# Rasterize to images
pdftoppm -jpeg -r 150 output.pdf slide

# Inspect images for: overflow, overlap, low contrast, misalignment
```

Build this as a tool your agents can call. Without it, agents ship overflowing text boxes, low-contrast elements, and misaligned columns they can't see.

**What to inspect for:**

- Overlapping elements (text through shapes, lines through words)
- Text overflow or cut off at edges/box boundaries
- Elements too close (< 0.3" gaps) or nearly touching
- Insufficient margin from slide/page edges (< 0.5")
- Low-contrast text or icons
- Leftover placeholder content

---

## Design Quality in System Prompts

The biggest lever is encoding design rules as **constraints, not suggestions**. For each format, give your agent:

### Color Rules

Provide a curated palette table with primary/secondary/accent colors. Enforce a dominant-color rule (60–70% visual weight to one color) and a dark/light contrast structure.

| Theme | Primary | Secondary | Accent |
|---|---|---|---|
| Midnight Executive | `1E2761` (navy) | `CADCFC` (ice blue) | `FFFFFF` (white) |
| Forest & Moss | `2C5F2D` (forest) | `97BC62` (moss) | `F5F5F5` (cream) |
| Coral Energy | `F96167` (coral) | `F9E795` (gold) | `2F3C7E` (navy) |
| Charcoal Minimal | `36454F` (charcoal) | `F2F2F2` (off-white) | `212121` (black) |
| Cherry Bold | `990011` (cherry) | `FCF6F5` (off-white) | `2F3C7E` (navy) |

### Typography Rules

Provide explicit font pairings, size hierarchies, and alignment rules:

| Element | Size |
|---|---|
| Slide/document title | 36–44pt bold |
| Section header | 20–24pt bold |
| Body text | 14–16pt |
| Captions | 10–12pt muted |

Left-align everything except titles. Never mix spacing randomly — pick 0.3" or 0.5" gaps and use consistently.

### Layout Rules

Give agents a menu of proven layouts to pick from rather than inventing:

- **Two-column** — text left, visual right
- **Icon-grid** — icons in colored circles with bold headers and description below
- **Half-bleed image** — full left or right side image with content overlay
- **Stat callouts** — large numbers (60–72pt) with small label below
- **Timeline/process flow** — numbered steps with arrows

### Anti-Pattern Lists

Explicitly list the hallmarks of AI-generated output and prohibit them:

- Accent lines under titles
- Cream/beige backgrounds by default (`F5F5DC`, `FAF0E6`, etc.)
- Text-only slides (every slide needs a visual element)
- Equal visual weight across all colors
- Repeating the same layout on every slide/page
- Decorative full-width colored bars or header ribbons

---

## Tool Design for Agents

Structure each document tool as a **multi-step function**:

1. **Plan** — agent decides content, layout, and palette before touching any code
2. **Generate** — produce the file using the appropriate library
3. **Validate** — run the format-specific validator (e.g. `validate.py` for docx)
4. **QA** — convert to images, inspect for visual defects
5. **Fix & re-verify** — one targeted fix cycle, then stop

---

## Infrastructure Requirements

Give agents access to these tools as callable utilities:

- **LibreOffice** (`soffice`) — cross-format conversion to PDF
- **Poppler** (`pdftoppm`) — PDF-to-image rasterization for visual QA
- **`pptxgenjs`** — `npm install -g pptxgenjs`
- **`docx`** — `npm install -g docx`
- **`openpyxl`** / **`reportlab`** — `pip install openpyxl reportlab --break-system-packages`

---

## Practical Tips

**Templates beat from-scratch** for docx and pptx. Let agents edit brand-approved templates via XML manipulation rather than generating from zero. It eliminates font-availability problems and keeps output on-brand.

**DXA units everywhere in docx** — never use `WidthType.PERCENTAGE`; it breaks in Google Docs rendering. Always use `WidthType.DXA`.

**Sub-agents for QA** — have a separate agent inspect the rendered images. The generating agent has too much context about what it *intended* and will miss what's actually broken.

**Design tokens as config** — store your palette, fonts, and spacing as a shared config object that all document tools import. This keeps output visually consistent across formats.

**One fix cycle, then stop** — the most common failure mode is over-iteration on sub-pixel nudges and minor color tweaks. Agents should fix real user-visible defects (overflow, overlap, missing content) and stop, not loop endlessly chasing perfect alignment.

---

## Summary

| Format | Library | QA Method |
|---|---|---|
| `.pptx` | `pptxgenjs` (Node) | soffice → pdftoppm → image inspect |
| `.docx` | `docx` (Node) | validate.py + soffice → image inspect |
| `.xlsx` | `openpyxl` (Python) / `SheetJS` | soffice → image inspect |
| `.pdf` | `reportlab` (Python) | Direct image inspect |

The stack — right library + design-rule-heavy prompts + image-based QA — is what separates agents that produce professional deliverables from ones that produce technically valid but visually mediocre files.

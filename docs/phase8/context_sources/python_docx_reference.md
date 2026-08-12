# python-docx Quick Reference — HireBuddha Document Toolkit

> This reference provides correct, tested API patterns for `python-docx ^1.1`.
> Use ONLY the patterns documented here. Do NOT guess at API methods.

## Core Setup

```python
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_ORIENT

doc = Document()
```

## Page Setup

```python
section = doc.sections[0]
section.page_width = Inches(8.5)
section.page_height = Inches(11)
section.top_margin = Inches(1)
section.bottom_margin = Inches(1)
section.left_margin = Inches(1.25)
section.right_margin = Inches(1.25)

# Landscape orientation
section.orientation = WD_ORIENT.LANDSCAPE
# IMPORTANT: swap width and height for landscape
section.page_width = Inches(11)
section.page_height = Inches(8.5)
```

## Headings and Paragraphs

```python
# Headings (0 = Title, 1-9 = Heading levels)
doc.add_heading('Document Title', level=0)
doc.add_heading('Chapter 1', level=1)
doc.add_heading('Section 1.1', level=2)

# Paragraph with formatting
p = doc.add_paragraph()
run = p.add_run('Bold text here')
run.bold = True
run.font.size = Pt(11)
run.font.name = 'Arial'
run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x2E)

# Paragraph alignment
p.alignment = WD_ALIGN_PARAGRAPH.CENTER

# Paragraph spacing
from docx.shared import Pt
p.paragraph_format.space_before = Pt(6)
p.paragraph_format.space_after = Pt(12)
p.paragraph_format.line_spacing = 1.5
```

## Styles

```python
# Modify existing styles
style = doc.styles['Heading 1']
style.font.name = 'Arial'
style.font.size = Pt(20)
style.font.color.rgb = RGBColor(0x1E, 0x27, 0x61)

style = doc.styles['Normal']
style.font.name = 'Georgia'
style.font.size = Pt(11)
style.font.color.rgb = RGBColor(0x1A, 0x1A, 0x2E)

# Apply style to paragraph
p = doc.add_paragraph('Styled text', style='Quote')
```

## Tables

```python
table = doc.add_table(rows=4, cols=3)
table.style = 'Table Grid'
table.alignment = WD_TABLE_ALIGNMENT.CENTER

# Set column widths
for cell in table.columns[0].cells:
    cell.width = Inches(2)

# Header row
header_cells = table.rows[0].cells
header_cells[0].text = 'Name'
header_cells[1].text = 'Value'
header_cells[2].text = 'Notes'

# Style header cells
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

for cell in header_cells:
    # Background color
    shading = OxmlElement('w:shd')
    shading.set(qn('w:fill'), '1E2761')
    cell._element.get_or_add_tcPr().append(shading)
    # Text color
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            run.font.bold = True

# Data rows
for row_idx in range(1, 4):
    for col_idx in range(3):
        table.cell(row_idx, col_idx).text = f'Data {row_idx},{col_idx}'

# Banded rows
for row_idx in range(1, len(table.rows)):
    if row_idx % 2 == 0:
        for cell in table.rows[row_idx].cells:
            shading = OxmlElement('w:shd')
            shading.set(qn('w:fill'), 'F3F0FF')
            cell._element.get_or_add_tcPr().append(shading)
```

## Images

```python
# Inline image
doc.add_picture('chart.png', width=Inches(5))

# Image in paragraph (centered)
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run()
run.add_picture('diagram.png', width=Inches(4))
```

## Sections and Page Breaks

```python
# Page break
doc.add_page_break()

# New section (for different orientation/margins)
from docx.enum.section import WD_ORIENT
new_section = doc.add_section(WD_ORIENT.LANDSCAPE)
new_section.page_width = Inches(11)
new_section.page_height = Inches(8.5)
```

## Headers and Footers

```python
section = doc.sections[0]
header = section.header
header_para = header.paragraphs[0]
header_para.text = "Company Name — Confidential"
header_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
header_para.runs[0].font.size = Pt(9)
header_para.runs[0].font.color.rgb = RGBColor(0x99, 0x99, 0x99)

footer = section.footer
footer_para = footer.paragraphs[0]
footer_para.text = "Page "
# Add page number field
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
fld = OxmlElement('w:fldSimple')
fld.set(qn('w:instr'), 'PAGE')
footer_para._element.append(fld)
```

## Cover Page Pattern

```python
# Full cover page with title and subtitle
doc.add_paragraph()  # Spacer
doc.add_paragraph()  # Spacer
doc.add_paragraph()  # Spacer

title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run('Report Title')
run.font.size = Pt(36)
run.font.bold = True
run.font.color.rgb = RGBColor(0x1E, 0x27, 0x61)

subtitle = doc.add_paragraph()
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = subtitle.add_run('Subtitle Line')
run.font.size = Pt(18)
run.font.color.rgb = RGBColor(0x7C, 0x3A, 0xED)

doc.add_page_break()  # End cover page
```

## Saving

```python
doc.save("/tmp/sandbox/<company_id>/output.docx")
```

## Common Mistakes to Avoid

1. **WRONG:** `p.font.size = Pt(11)` — Font properties are on RUNS, not paragraphs: `p.runs[0].font.size`
2. **WRONG:** `doc.add_heading('Title', 0)` — Use keyword arg: `level=0`
3. **WRONG:** Forgetting to swap width/height for landscape sections
4. **WRONG:** Using `cell.text = "text"` then trying to format — Set text via `cell.paragraphs[0].add_run()`
5. **WRONG:** `cell.shading = ...` — Cell shading uses OxmlElement, not direct property

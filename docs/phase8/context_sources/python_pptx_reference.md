# python-pptx Quick Reference — HireBuddha Document Toolkit

> This reference provides correct, tested API patterns for `python-pptx ^1.0`.
> Use ONLY the patterns documented here. Do NOT guess at API methods.

## Core Setup

```python
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE

prs = Presentation()
prs.slide_width = Inches(13.333)   # 16:9 widescreen
prs.slide_height = Inches(7.5)
```

## Slide Layouts

```python
# Use blank layout for full control
slide_layout = prs.slide_layouts[6]  # Blank
slide = prs.slides.add_slide(slide_layout)
```

## Text Boxes

```python
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor

txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(10), Inches(1.5))
tf = txBox.text_frame
tf.word_wrap = True

# First paragraph (already exists)
p = tf.paragraphs[0]
p.text = "Title Text"
p.font.size = Pt(44)
p.font.bold = True
p.font.color.rgb = RGBColor(0x1E, 0x27, 0x61)
p.font.name = "Arial"
p.alignment = PP_ALIGN.LEFT

# Add subsequent paragraphs
p2 = tf.add_paragraph()
p2.text = "Body text"
p2.font.size = Pt(18)
p2.font.name = "Arial"
p2.space_before = Pt(12)
```

## Shapes and Rectangles

```python
from pptx.enum.shapes import MSO_SHAPE

# Full-slide background rectangle
bg = slide.shapes.add_shape(
    MSO_SHAPE.RECTANGLE,
    Inches(0), Inches(0),
    prs.slide_width, prs.slide_height
)
bg.fill.solid()
bg.fill.fore_color.rgb = RGBColor(0x1E, 0x27, 0x61)
bg.line.fill.background()  # No border

# Gradient fill
bg.fill.gradient()
bg.fill.gradient_stops[0].color.rgb = RGBColor(0x1E, 0x27, 0x61)
bg.fill.gradient_stops[0].position = 0.0
bg.fill.gradient_stops[1].color.rgb = RGBColor(0x7C, 0x3A, 0xED)
bg.fill.gradient_stops[1].position = 1.0
```

## Images

```python
# Add image with explicit size
pic = slide.shapes.add_picture(
    "cover_bg.png",
    Inches(0), Inches(0),
    width=prs.slide_width,
    height=prs.slide_height
)
# Send to back (behind text)
slide.shapes._spTree.remove(pic._element)
slide.shapes._spTree.insert(2, pic._element)
```

## Tables

```python
rows, cols = 5, 4
table_shape = slide.shapes.add_table(rows, cols, Inches(1), Inches(2), Inches(11), Inches(4))
table = table_shape.table

# Set column widths
table.columns[0].width = Inches(3)
table.columns[1].width = Inches(2.5)

# Style header row
for col_idx in range(cols):
    cell = table.cell(0, col_idx)
    cell.text = f"Header {col_idx}"
    cell.fill.solid()
    cell.fill.fore_color.rgb = RGBColor(0x1E, 0x27, 0x61)
    for paragraph in cell.text_frame.paragraphs:
        paragraph.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        paragraph.font.size = Pt(12)
        paragraph.font.bold = True

# Style data rows with banding
for row_idx in range(1, rows):
    for col_idx in range(cols):
        cell = table.cell(row_idx, col_idx)
        cell.text = f"Data {row_idx},{col_idx}"
        if row_idx % 2 == 0:
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(0xF3, 0xF0, 0xFF)
```

## Native Charts (Editable)

```python
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION

# Bar Chart
chart_data = CategoryChartData()
chart_data.categories = ['Q1', 'Q2', 'Q3', 'Q4']
chart_data.add_series('Revenue ($M)', (2.4, 3.1, 3.8, 4.5))

chart_frame = slide.shapes.add_chart(
    XL_CHART_TYPE.COLUMN_CLUSTERED,
    Inches(1), Inches(2), Inches(10), Inches(4.5),
    chart_data
)
chart = chart_frame.chart
chart.has_legend = True
chart.legend.position = XL_LEGEND_POSITION.BOTTOM

# Style series colors
series = chart.series[0]
series.format.fill.solid()
series.format.fill.fore_color.rgb = RGBColor(0x7C, 0x3A, 0xED)

# Line Chart
chart_data = CategoryChartData()
chart_data.categories = ['Jan', 'Feb', 'Mar', 'Apr', 'May']
chart_data.add_series('Users', (100, 250, 420, 680, 950))
chart_frame = slide.shapes.add_chart(
    XL_CHART_TYPE.LINE, Inches(1), Inches(2), Inches(10), Inches(4.5), chart_data
)

# Pie Chart
from pptx.chart.data import ChartData
chart_data = ChartData()
chart_data.categories = ['Product A', 'Product B', 'Product C']
chart_data.add_series('Share', (45, 30, 25))
chart_frame = slide.shapes.add_chart(
    XL_CHART_TYPE.PIE, Inches(3), Inches(2), Inches(6), Inches(4.5), chart_data
)
```

## EMU Units Reference

```python
# 1 inch = 914400 EMUs
# 1 point = 12700 EMUs
# 1 cm = 360000 EMUs
# Widescreen 16:9 = 13.333 x 7.5 inches = 12192000 x 6858000 EMUs
```

## Saving

```python
prs.save("/tmp/sandbox/<company_id>/output.pptx")
```

## Common Mistakes to Avoid

1. **WRONG:** `slide.shapes.add_textbox(1, 1, 10, 1)` — Values MUST use `Inches()` or `Emu()`
2. **WRONG:** `p.font.color = RGBColor(...)` — Use `p.font.color.rgb = RGBColor(...)`
3. **WRONG:** Using `prs.slide_layouts[0]` for custom layouts — Use `prs.slide_layouts[6]` (blank) and build manually
4. **WRONG:** Forgetting `tf.word_wrap = True` — Text will overflow without this
5. **WRONG:** `chart_data.add_series('Name', [1,2,3])` — Use tuples `(1,2,3)` not lists
6. **WRONG:** `from pptx.chart.data import ChartData` for category charts — Use `CategoryChartData`

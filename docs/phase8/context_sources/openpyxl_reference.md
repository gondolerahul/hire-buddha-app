# openpyxl Quick Reference — HireBuddha Document Toolkit

> Correct, tested API patterns for `openpyxl ^3.1`. Use ONLY these patterns.

## Core Setup
```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
wb = Workbook()
ws = wb.active
ws.title = "Dashboard"
```

## Worksheets
```python
ws1 = wb.active; ws1.title = "Assumptions"
ws2 = wb.create_sheet("Revenue Model")
ws3 = wb.create_sheet("Dashboard")
ws3.sheet_properties.tabColor = "1E2761"
```

## Cells, Formulas, Named Ranges
```python
ws['A1'] = 'Revenue Growth Rate'
ws['B1'] = 0.15
ws['B5'] = '=Assumptions!B2 * B4'
ws['B6'] = '=SUM(B2:B5)'

from openpyxl.workbook.defined_name import DefinedName
ref = DefinedName('growth_rate', attr_text="Assumptions!$B$2")
wb.defined_names.add(ref)
```

## Styling
```python
header_font = Font(name='Arial', size=11, bold=True, color='FFFFFF')
header_fill = PatternFill(start_color='1E2761', end_color='1E2761', fill_type='solid')
band_fill = PatternFill(start_color='F3F0FF', end_color='F3F0FF', fill_type='solid')
center = Alignment(horizontal='center', vertical='center', wrap_text=True)
border = Border(left=Side(style='thin',color='D3D8DE'), right=Side(style='thin',color='D3D8DE'),
                top=Side(style='thin',color='D3D8DE'), bottom=Side(style='thin',color='D3D8DE'))
for col in range(1, 6):
    cell = ws.cell(row=1, column=col)
    cell.font = header_font; cell.fill = header_fill; cell.alignment = center; cell.border = border
```

## Number Formats
```python
ws['B2'].number_format = '$#,##0.00'   # Currency
ws['C2'].number_format = '0.0%'        # Percentage
ws['D2'].number_format = '#,##0'       # Thousands
```

## Column Widths, Freeze Panes
```python
ws.column_dimensions['A'].width = 25
ws.freeze_panes = 'A2'   # Freeze top row
ws.row_dimensions[1].height = 30
```

## Conditional Formatting
```python
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule, CellIsRule
ws.conditional_formatting.add('B2:B20',
    ColorScaleRule(start_type='min', start_color='FF0000',
                   mid_type='percentile', mid_value=50, mid_color='FFFF00',
                   end_type='max', end_color='00FF00'))
ws.conditional_formatting.add('C2:C20',
    DataBarRule(start_type='min', end_type='max', color='7C3AED'))
```

## Data Validation
```python
from openpyxl.worksheet.datavalidation import DataValidation
dv = DataValidation(type="list", formula1='"Yes,No,Maybe"', allow_blank=True)
ws.add_data_validation(dv); dv.add(ws['A2'])
```

## Native Charts
```python
chart = BarChart(); chart.type = "col"; chart.title = "Revenue"
chart.width = 18; chart.height = 12
data = Reference(ws, min_col=2, min_row=1, max_row=5, max_col=2)
cats = Reference(ws, min_col=1, min_row=2, max_row=5)
chart.add_data(data, titles_from_data=True); chart.set_categories(cats)
chart.series[0].graphicalProperties.solidFill = "7C3AED"
ws.add_chart(chart, "D2")
```

## Images
```python
from openpyxl.drawing.image import Image
img = Image('chart.png'); img.width = 600; img.height = 400
ws.add_image(img, 'D2')
```

## Saving
```python
wb.save("/tmp/sandbox/<company_id>/output.xlsx")
```

## Common Mistakes
1. Use `PatternFill(start_color=..., fill_type='solid')` — forgetting `fill_type` won't render
2. Chart colors: `"7C3AED"` NOT `"#7C3AED"` (no hash prefix)
3. `freeze_panes = 'A1'` freezes nothing — use `'A2'` to freeze row 1
4. `chart.add_data(data, titles_from_data=True)` when row 1 has headers

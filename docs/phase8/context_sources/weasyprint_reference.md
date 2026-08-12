# WeasyPrint Quick Reference — HireBuddha Document Toolkit

> Correct, tested patterns for WeasyPrint PDF generation via HTML/CSS.

## Core Setup
```python
from weasyprint import HTML, CSS

html_content = "<html><body><h1>Title</h1><p>Content</p></body></html>"
css_content = "body { font-family: Georgia, serif; font-size: 11pt; }"

HTML(string=html_content).write_pdf(
    "/tmp/sandbox/<company_id>/output.pdf",
    stylesheets=[CSS(string=css_content)]
)
```

## Page Setup (@page)
```css
@page {
    size: A4;              /* or Letter, A3, 210mm 297mm */
    margin: 2.5cm 2cm;
    @top-right { content: "Company Name"; font-size: 9pt; color: #999; }
    @bottom-center { content: "Page " counter(page) " of " counter(pages); font-size: 9pt; }
}
@page :first { margin-top: 0; }    /* No margin on cover page */
@page landscape { size: A4 landscape; }
```

## Typography
```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
body { font-family: Georgia, serif; font-size: 11pt; line-height: 1.6; color: #1A1A2E; }
h1 { font-family: Inter, Arial, sans-serif; font-size: 20pt; color: #1E2761; line-height: 1.3; }
h2 { font-family: Inter, Arial, sans-serif; font-size: 16pt; color: #7C3AED; margin-top: 1.5em; }
h3 { font-family: Inter, Arial, sans-serif; font-size: 13pt; color: #1A1A2E; }
code { font-family: 'DejaVu Sans Mono', monospace; font-size: 9pt; }
```

## Page Breaks
```css
h1 { page-break-before: always; }
h1:first-of-type { page-break-before: avoid; }
.no-break { page-break-inside: avoid; }
.page-break { page-break-after: always; }
table, figure { page-break-inside: avoid; }
```

## Table of Contents (Bookmarks)
```css
h1 { bookmark-level: 1; }
h2 { bookmark-level: 2; }
h3 { bookmark-level: 3; }
/* WeasyPrint auto-generates PDF bookmarks from these */
```

## Two-Column Layout
```css
.two-column {
    column-count: 2;
    column-gap: 1.5cm;
    column-rule: 1px solid #E0E0E0;
}
```

## Cover Page
```html
<div class="cover">
    <div class="cover-bg" style="background: linear-gradient(135deg, #1E2761 0%, #7C3AED 100%);
         width: 100%; height: 100%; position: absolute; top: 0; left: 0;"></div>
    <h1 class="cover-title">Report Title</h1>
    <p class="cover-subtitle">Subtitle</p>
</div>
```
```css
.cover { page-break-after: always; position: relative; height: 100vh; }
.cover-title { color: white; font-size: 36pt; position: relative; z-index: 1; padding-top: 40%; text-align: center; }
.cover-subtitle { color: rgba(255,255,255,0.8); font-size: 18pt; text-align: center; position: relative; z-index: 1; }
```

## Tables
```css
table { width: 100%; border-collapse: collapse; margin: 1em 0; page-break-inside: avoid; }
th { background: #1E2761; color: white; font-family: Inter, sans-serif; font-size: 10pt;
     padding: 8px 12px; text-align: left; }
td { padding: 8px 12px; border-bottom: 1px solid #E0E0E0; font-size: 10pt; }
tr:nth-child(even) td { background: #F3F0FF; }
```

## Pull Quotes / Callouts
```css
blockquote { border-left: 4px solid #7C3AED; padding: 1em 1.5em; margin: 1.5em 0;
             background: #F8F7FF; font-style: italic; page-break-inside: avoid; }
.callout { background: #EEF2FF; border-radius: 8px; padding: 1em 1.5em; margin: 1em 0;
           border-left: 4px solid #3B82F6; }
```

## Images
```html
<figure>
    <img src="/tmp/sandbox/<company_id>/chart.png" style="width: 100%; max-width: 500px;">
    <figcaption>Figure 1: Revenue Growth</figcaption>
</figure>
```
```css
figure { text-align: center; margin: 1.5em 0; page-break-inside: avoid; }
figcaption { font-size: 9pt; color: #666; margin-top: 0.5em; }
img { max-width: 100%; }
```

## Saving
```python
HTML(string=html_content).write_pdf(
    "/tmp/sandbox/<company_id>/report.pdf",
    stylesheets=[CSS(string=css_string)]
)
```

## Common Mistakes
1. WeasyPrint does NOT support JavaScript — no interactive elements
2. Use `file:///absolute/path` for local image `src` attributes
3. `@page` margins apply to ALL pages — use `:first` pseudo for cover
4. CSS `position: fixed` does NOT work in WeasyPrint — use `@page` margin boxes
5. Google Fonts import works but requires network access — prefer local fonts

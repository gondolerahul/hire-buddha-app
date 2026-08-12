# PptxGenJS Quick Reference — Document Renderer Context

## Installation
PptxGenJS is installed in `/home/rahul/workspace/hb-proto-3/backend/node_modules/pptxgenjs/`.

## Execution Pattern
Write a `.js` file to `/tmp/sandbox/output/generate_pptx.js`, then run via terminal:
```bash
cd /home/rahul/workspace/hb-proto-3/backend && node /tmp/sandbox/output/generate_pptx.js
```

## Core API

### Create Presentation
```javascript
const PptxGenJS = require("pptxgenjs");
const pres = new PptxGenJS();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5 inches (default)
```

### Define Slide Master (branding)
```javascript
pres.defineSlideMaster({
  title: "BRANDED_SLIDE",
  background: { color: "FFFFFF" },
  objects: [
    // Top accent bar
    { rect: { x: 0, y: 0, w: "100%", h: 0.06, fill: { color: "7C3AED" } } },
    // Footer text
    { text: { text: "Confidential", options: { x: 0.5, y: 7.0, fontSize: 8, color: "999999" } } },
    // Slide number
    { text: { text: { field: "slideNumber" }, options: { x: 12, y: 7.0, fontSize: 8, color: "999999" } } },
  ],
});
```

### Add Slides
```javascript
let slide = pres.addSlide();
// or with master:
let slide = pres.addSlide({ masterName: "BRANDED_SLIDE" });
```

### Slide Background
```javascript
// Solid color
slide.background = { color: "1E2761" };
// Gradient
slide.background = { fill: { type: "solid", color: "1E2761" } };
// Image
slide.background = { path: "/path/to/image.png" };
```

### Add Text
```javascript
slide.addText("Title Text", {
  x: 1, y: 1, w: 8, h: 1.2,
  fontSize: 44, bold: true, color: "FFFFFF",
  fontFace: "Arial",
  align: "center",   // left, center, right
  valign: "middle",   // top, middle, bottom
});

// Multi-line with formatting
slide.addText([
  { text: "Bold Part ", options: { bold: true, fontSize: 18, color: "1E2761" } },
  { text: "Normal Part", options: { fontSize: 16, color: "666666" } },
], { x: 1, y: 2, w: 10 });

// Bullet list
slide.addText([
  { text: "First point", options: { bullet: true, fontSize: 16, color: "1A1A2E" } },
  { text: "Second point", options: { bullet: true, fontSize: 16, color: "1A1A2E" } },
  { text: "Third point", options: { bullet: true, fontSize: 16, color: "1A1A2E" } },
], { x: 1, y: 2, w: 5.5, lineSpacingMultiple: 1.5 });
```

### Add Shapes
```javascript
// Rectangle (card/container)
slide.addShape(pres.shapes.RECT, {
  x: 0.5, y: 1.5, w: 5, h: 3,
  fill: { color: "FFFFFF" },
  shadow: { type: "outer", blur: 6, offset: 3, color: "000000", opacity: 0.15 },
  rectRadius: 0.1,  // rounded corners
  line: { color: "E0E0E0", width: 0.5 },
});

// Accent bar
slide.addShape(pres.shapes.RECT, {
  x: 0.8, y: 1.3, w: 2, h: 0.04,
  fill: { color: "7C3AED" },
  line: { width: 0 },
});

// Circle
slide.addShape(pres.shapes.OVAL, {
  x: 3, y: 3, w: 0.7, h: 0.7,
  fill: { color: "7C3AED" },
});
```

### Add Images
```javascript
// From file path
slide.addImage({ path: "/tmp/sandbox/output/chart.png", x: 1, y: 1.5, w: 8, h: 4.5 });

// SVG
slide.addImage({ path: "/tmp/sandbox/output/diagram.svg", x: 1, y: 1.5, w: 8, h: 4 });
```

### Add Tables
```javascript
let rows = [
  // Header row
  [
    { text: "Metric", options: { bold: true, color: "FFFFFF", fill: { color: "1E2761" } } },
    { text: "Q1", options: { bold: true, color: "FFFFFF", fill: { color: "1E2761" } } },
    { text: "Q2", options: { bold: true, color: "FFFFFF", fill: { color: "1E2761" } } },
  ],
  // Data rows
  [{ text: "Revenue" }, { text: "$2.4M" }, { text: "$3.1M" }],
  [{ text: "Growth" }, { text: "12%" }, { text: "18%" }],
];

slide.addTable(rows, {
  x: 1, y: 2, w: 10,
  fontSize: 14,
  border: { type: "solid", pt: 0.5, color: "E0E0E0" },
  colW: [3, 3.5, 3.5],
  rowH: [0.5, 0.4, 0.4],
  autoPage: true,
  autoPageRepeatHeader: true,
});
```

### Add Native Charts (EDITABLE in PowerPoint!)
```javascript
// Bar Chart
let chartData = [
  { name: "Revenue", labels: ["Q1", "Q2", "Q3", "Q4"], values: [2.4, 3.1, 3.8, 4.5] },
];
slide.addChart(pres.charts.BAR, chartData, {
  x: 1, y: 1.5, w: 8, h: 4.5,
  showTitle: true, title: "Revenue ($M)",
  showValue: true, valueFontSize: 10,
  catAxisLabelFontSize: 12,
  chartColors: ["7C3AED"],
  showLegend: false,
});

// Line Chart
slide.addChart(pres.charts.LINE, chartData, {
  x: 1, y: 1.5, w: 8, h: 4.5,
  showTitle: true, title: "Growth Trend",
  lineSize: 3,
  lineSmooth: true,
  chartColors: ["7C3AED", "3B82F6"],
  showMarker: true, markerSize: 8,
});

// Pie Chart
let pieData = [
  { name: "Market Share", labels: ["Us", "Competitor A", "Others"], values: [45, 30, 25] },
];
slide.addChart(pres.charts.PIE, pieData, {
  x: 1, y: 1.5, w: 6, h: 5,
  showTitle: true, title: "Market Share",
  showPercent: true,
  chartColors: ["7C3AED", "3B82F6", "10B981"],
});

// Doughnut Chart
slide.addChart(pres.charts.DOUGHNUT, pieData, {
  x: 1, y: 1.5, w: 6, h: 5,
  showPercent: true,
  chartColors: ["7C3AED", "3B82F6", "10B981"],
});
```

### Save File
```javascript
const fs = require("fs");
pres.write("nodebuffer").then(buffer => {
  fs.writeFileSync("/tmp/sandbox/output/presentation.pptx", buffer);
  console.log("PPTX saved to /tmp/sandbox/output/presentation.pptx");
  process.exit(0);
});
```

## Theme Colors Reference

| Theme | Primary | Accent | Text | Chart Colors |
|-------|---------|--------|------|-------------|
| midnight_executive | 1E2761 | 7C3AED | 1A1A2E | 7C3AED, 3B82F6, 10B981, F59E0B, EF4444 |
| forest_moss | 2C5F2D | 97BC62 | 1B1B1B | 97BC62, 4A7C4B, 8FBC8F, 556B2F, 228B22 |
| coral_energy | 2F3C7E | F96167 | 2F3C7E | F96167, F9E795, FCB69F, FF6B6B, FFA07A |
| charcoal_minimal | 36454F | 64B5F6 | 212121 | 64B5F6, 5F6B7C, 87919E, B0B8C1, 26C6DA |

## Slide Type Templates

### Cover Slide
```javascript
let slide = pres.addSlide();
slide.background = { color: PRIMARY };
// Optional: background image
// slide.background = { path: coverImagePath };
// Dark overlay for readability
slide.addShape(pres.shapes.RECT, { x:0, y:0, w:"100%", h:"100%", fill:{color:"000000"}, opacity:0.4 });
// Top accent bar
slide.addShape(pres.shapes.RECT, { x:0, y:0, w:"100%", h:0.08, fill:{color:ACCENT} });
// Title
slide.addText(title, { x:1.5, y:2.4, w:10.3, h:1.5, fontSize:48, bold:true, color:"FFFFFF", align:"center" });
// Subtitle
slide.addText(subtitle, { x:2, y:4.2, w:9.3, h:0.8, fontSize:22, color:"CCCCDD", align:"center" });
// Bottom accent bar
slide.addShape(pres.shapes.RECT, { x:5, y:5.3, w:3.3, h:0.04, fill:{color:ACCENT} });
```

### Title + Content Slide
```javascript
let slide = pres.addSlide({ masterName: "BRANDED_SLIDE" });
// Left accent bar
slide.addShape(pres.shapes.RECT, { x:0, y:0, w:0.08, h:"100%", fill:{color:ACCENT} });
// Title
slide.addText(title, { x:0.8, y:0.5, w:6, h:0.8, fontSize:34, bold:true, color:PRIMARY });
// Accent underline
slide.addShape(pres.shapes.RECT, { x:0.8, y:1.4, w:2, h:0.04, fill:{color:ACCENT} });
// Bullets
slide.addText(bullets.map(b => ({ text: b, options: { bullet:true, fontSize:17, color:TEXT } })),
  { x:0.8, y:1.8, w:5.8, h:4.5, lineSpacingMultiple:1.5 });
// Right image (if available)
if (imagePath) {
  slide.addShape(pres.shapes.RECT, { x:7.2, y:0.8, w:5.6, h:5.9, fill:{color:"FFFFFF"}, shadow:{type:"outer",blur:6,offset:3,opacity:0.15} });
  slide.addImage({ path: imagePath, x:7.35, y:0.95, w:5.3, h:5.6 });
}
```

### KPI Grid Slide
```javascript
let slide = pres.addSlide();
slide.background = { color: PRIMARY };
slide.addText(title, { x:0.8, y:0.4, w:11, h:0.8, fontSize:34, bold:true, color:"FFFFFF" });
kpis.forEach((kpi, i) => {
  let x = 1 + i * 3.1;
  // Card background
  slide.addShape(pres.shapes.RECT, { x:x, y:2.2, w:2.7, h:3.8, fill:{color:"FFFFFF"}, rectRadius:0.1, shadow:{type:"outer",blur:6,offset:3,opacity:0.15} });
  // Colored top accent
  slide.addShape(pres.shapes.RECT, { x:x, y:2.2, w:2.7, h:0.08, fill:{color:CHART_COLORS[i]} });
  // Value
  slide.addText(kpi.value, { x:x+0.2, y:2.8, w:2.3, h:1.0, fontSize:36, bold:true, color:PRIMARY, align:"center" });
  // Label
  slide.addText(kpi.label, { x:x+0.2, y:4.0, w:2.3, h:0.8, fontSize:14, color:"666666", align:"center" });
  // Delta
  if (kpi.delta) {
    let dc = kpi.delta.startsWith("+") ? "10B981" : "EF4444";
    slide.addText(kpi.delta, { x:x+0.2, y:5.0, w:2.3, h:0.5, fontSize:16, bold:true, color:dc, align:"center" });
  }
});
```

### Data Chart Slide
```javascript
let slide = pres.addSlide({ masterName: "BRANDED_SLIDE" });
slide.addText(title, { x:0.8, y:0.4, w:10, h:0.8, fontSize:32, bold:true, color:PRIMARY });
// Use native chart (editable!) or embedded image
slide.addChart(pres.charts.BAR, chartData, { x:0.5, y:1.6, w:8.5, h:5.3, chartColors:CHART_COLORS });
// Callout cards on right
callouts.forEach((co, i) => {
  let y = 1.8 + i * 1.8;
  slide.addShape(pres.shapes.RECT, { x:9.5, y:y, w:3.3, h:1.4, fill:{color:"FFFFFF"}, shadow:{type:"outer",blur:4,offset:2,opacity:0.1} });
  slide.addText(co.label, { x:9.8, y:y+0.15, w:2.8, h:0.4, fontSize:13, color:"888888" });
  slide.addText(co.value, { x:9.8, y:y+0.55, w:2.8, h:0.6, fontSize:28, bold:true, color:PRIMARY });
});
```

## Anti-Patterns (NEVER DO)
1. Never use default font — always set fontFace to "Arial" or "Inter"
2. Never use black (#000000) for text — use theme text color
3. Never leave slides without visual elements (shapes, charts, or images)
4. Max 6 bullets per slide, max 12 words per bullet
5. Charts must fill at least 60% of slide area
6. Always use theme chart colors, not random colors
7. Always include a Slide Master for consistent branding
8. Use `pres.write("nodebuffer")` + `fs.writeFileSync()` for reliable saving (not `writeFile`)

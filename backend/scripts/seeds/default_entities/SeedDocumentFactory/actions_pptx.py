"""Layer 1: PPTX ACTION entity definitions for Document Factory Engine.

Distilled from Claude Skills: skills/pptx/SKILL.md, editing.md, pptxgenjs.md
"""

ACTIONS_PPTX = [
    {
        "key": "pptx_create_action",
        "payload": {
            "name": "doc-create-pptx",
            "display_name": "PPTX Creator (PptxGenJS)",
            "description": "Creates presentation decks from scratch using PptxGenJS. Produces stunning, McKinsey-quality slides with charts, icons, and professional design.",
            "goal": "Generate a pixel-perfect .pptx presentation from content specifications using PptxGenJS with world-class design.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pptx", "creation", "pptxgenjs"],
            "identity": {
                "system_prompt": (
                    "You are a world-class presentation designer. Create PPTX files using PptxGenJS.\n\n"
                    "## SETUP\n"
                    "```javascript\n"
                    "const pptxgen = require('pptxgenjs');\n"
                    "let pres = new pptxgen();\n"
                    "pres.layout = 'LAYOUT_16x9'; // 10\" x 5.625\"\n"
                    "let slide = pres.addSlide();\n"
                    "slide.addText('Hello', { x: 0.5, y: 0.5, fontSize: 36, color: '363636' });\n"
                    "pres.writeFile({ fileName: 'output.pptx' });\n"
                    "```\n\n"
                    "## DESIGN PRINCIPLES (NON-NEGOTIABLE)\n"
                    "- NEVER create boring slides. Every slide needs a visual element.\n"
                    "- Pick a bold, content-informed color palette specific to THIS topic.\n"
                    "- One color dominates (60-70%), 1-2 supporting, one sharp accent.\n"
                    "- Dark backgrounds for title+conclusion, light for content.\n"
                    "- Commit to ONE visual motif and repeat across every slide.\n\n"
                    "## COLOR PALETTES (choose one matching the topic):\n"
                    "Midnight Executive: 1E2761/CADCFC/FFFFFF | Forest & Moss: 2C5F2D/97BC62/F5F5F5\n"
                    "Coral Energy: F96167/F9E795/2F3C7E | Warm Terracotta: B85042/E7E8D1/A7BEAE\n"
                    "Ocean Gradient: 065A82/1C7293/21295C | Charcoal Minimal: 36454F/F2F2F2/212121\n"
                    "Teal Trust: 028090/00A896/02C39A | Berry & Cream: 6D2E46/A26769/ECE2D0\n"
                    "Sage Calm: 84B59F/69A297/50808E | Cherry Bold: 990011/FCF6F5/2F3C7E\n\n"
                    "## TYPOGRAPHY\n"
                    "Header/Body pairs: Georgia/Calibri, Arial Black/Arial, Cambria/Calibri\n"
                    "Sizes: Slide title 36-44pt bold, Section header 20-24pt bold, Body 14-16pt, Captions 10-12pt\n"
                    "Spacing: 0.5\" min margins, 0.3-0.5\" between blocks.\n\n"
                    "## LAYOUT OPTIONS (vary across slides!)\n"
                    "- Two-column (text left, visual right)\n"
                    "- Icon + text rows (icon in colored circle, bold header, description)\n"
                    "- 2x2 or 2x3 grid with image on one side\n"
                    "- Half-bleed image with content overlay\n"
                    "- Large stat callouts (big numbers 60-72pt with labels below)\n"
                    "- Timeline or process flow (numbered steps, arrows)\n\n"
                    "## TEXT & LISTS\n"
                    "```javascript\n"
                    "// Multi-line: use breakLine: true\n"
                    "slide.addText([\n"
                    "  { text: 'Line 1', options: { breakLine: true } },\n"
                    "  { text: 'Line 2' }\n"
                    "], { x: 0.5, y: 0.5, w: 8, h: 2 });\n"
                    "// Bullets: use bullet: true, NEVER unicode '•'\n"
                    "{ text: 'Item', options: { bullet: true, breakLine: true } }\n"
                    "```\n\n"
                    "## SHAPES & SHADOWS\n"
                    "```javascript\n"
                    "slide.addShape(pres.shapes.RECTANGLE, {\n"
                    "  x: 1, y: 1, w: 3, h: 2, fill: { color: 'FF0000' },\n"
                    "  shadow: { type: 'outer', color: '000000', blur: 6, offset: 2, angle: 135, opacity: 0.15 }\n"
                    "});\n"
                    "```\n"
                    "Shadow offset MUST be non-negative. For upward shadow use angle: 270.\n\n"
                    "## CHARTS\n"
                    "```javascript\n"
                    "slide.addChart(pres.charts.BAR, [{ name: 'Sales', labels: ['Q1','Q2'], values: [4500,5500] }],\n"
                    "  { x: 0.5, y: 1, w: 9, h: 4, barDir: 'col',\n"
                    "    chartColors: ['0D9488','14B8A6'], valGridLine: { color: 'E2E8F0', size: 0.5 },\n"
                    "    catGridLine: { style: 'none' }, showValue: true });\n"
                    "```\n\n"
                    "## ICONS (react-icons → PNG)\n"
                    "```javascript\n"
                    "const React = require('react');\n"
                    "const ReactDOMServer = require('react-dom/server');\n"
                    "const sharp = require('sharp');\n"
                    "const { FaCheckCircle } = require('react-icons/fa');\n"
                    "function renderIconSvg(Icon, color, size=256) {\n"
                    "  return ReactDOMServer.renderToStaticMarkup(React.createElement(Icon, { color, size: String(size) }));\n"
                    "}\n"
                    "async function iconToBase64Png(Icon, color, size=256) {\n"
                    "  const svg = renderIconSvg(Icon, color, size);\n"
                    "  const buf = await sharp(Buffer.from(svg)).png().toBuffer();\n"
                    "  return 'image/png;base64,' + buf.toString('base64');\n"
                    "}\n"
                    "```\n\n"
                    "## CRITICAL PITFALLS\n"
                    "1. NEVER use '#' with hex colors — causes file corruption\n"
                    "2. NEVER encode opacity in hex (8-char colors corrupt file) — use opacity property\n"
                    "3. Use bullet: true, NEVER unicode '•'\n"
                    "4. Use breakLine: true between array items\n"
                    "5. NEVER reuse option objects across calls — PptxGenJS mutates them. Use factory functions.\n"
                    "6. Don't use ROUNDED_RECTANGLE with accent borders\n"
                    "7. NEVER use accent lines under titles — hallmark of AI-generated slides\n"
                    "8. Set margin: 0 on text boxes when aligning with shapes\n\n"
                    "## AVOID\n"
                    "- Don't repeat same layout across slides — vary columns, cards, callouts\n"
                    "- Don't center body text — left-align paragraphs, center only titles\n"
                    "- Don't default to blue — pick topic-specific colors\n"
                    "- Don't create text-only slides — add images, icons, charts\n"
                    "- Don't use low-contrast elements"
                ),
                "behavioral_constraints": [
                    "NEVER use '#' prefix with hex colors — causes file corruption",
                    "NEVER encode opacity in hex color strings — use opacity property instead",
                    "Use bullet: true for lists — NEVER unicode bullet characters",
                    "NEVER reuse option objects across addShape/addText calls — use factory functions",
                    "Every slide must have a visual element — no text-only slides",
                    "Vary layouts across slides — never repeat the same layout consecutively",
                    "Shadow offset must be non-negative — use angle: 270 for upward shadows",
                    "NEVER use accent lines under titles — hallmark of AI-generated slides",
                    "Pick topic-specific color palette — never default to generic blue"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.4, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "retry_policy": {"max_retries": 2, "backoff_strategy": "EXPONENTIAL"},
                "context_policy": {"type": "FULL", "summarize_threshold": 25000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Generate PPTX with PptxGenJS",
                    "description": "Write and execute JavaScript using PptxGenJS to create the presentation",
                    "type": "ACTION",
                    "target": {"tool_id": "sandbox_code", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {"tools": [{"tool_id": "sandbox_code"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 3000000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pptx_analyze_template_action",
        "payload": {
            "name": "doc-analyze-pptx-template",
            "display_name": "PPTX Template Analyzer",
            "description": "Analyzes an existing PPTX template to identify slide layouts, placeholders, and design patterns for template-based editing.",
            "goal": "Produce a complete analysis of available slide layouts and their visual structure.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pptx", "template", "analysis"],
            "identity": {
                "system_prompt": (
                    "You analyze PPTX templates for editing workflows.\n\n"
                    "## COMMANDS\n"
                    "```bash\n"
                    "# Visual overview of all slides\n"
                    "python scripts/pptx/thumbnail.py template.pptx\n"
                    "# Text content extraction\n"
                    "python -m markitdown template.pptx\n"
                    "```\n\n"
                    "## ANALYSIS OUTPUT\n"
                    "For each slide, identify:\n"
                    "- Layout type (title, content, two-column, image+text, quote, etc.)\n"
                    "- Placeholder text that needs replacement\n"
                    "- Visual elements (images, shapes, charts)\n"
                    "- Color scheme and fonts used\n\n"
                    "## SLIDE MAPPING GUIDANCE\n"
                    "USE VARIED LAYOUTS — monotonous presentations are a common failure mode.\n"
                    "Actively seek: multi-column, image+text, full-bleed, quote slides, stat callouts, icon grids.\n"
                    "Match content type to layout style."
                ),
                "behavioral_constraints": [
                    "Review thumbnails.jpg to see visual layouts",
                    "Use markitdown output to see placeholder text",
                    "Recommend varied layout usage — flag if too many similar layouts"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.2, "reasoning_mode": "REACT"}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Analyze Template", "type": "ACTION", "target": {"tool_id": "terminal", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pptx_unpack_action",
        "payload": {
            "name": "doc-unpack-pptx",
            "display_name": "PPTX Unpacker",
            "description": "Extracts a .pptx file into XML files for editing.",
            "goal": "Unpack a .pptx into an editable directory with pretty-printed XML.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pptx", "unpack"],
            "identity": {
                "system_prompt": "You unpack .pptx files.\n\n```bash\npython scripts/pptx/office/unpack.py input.pptx unpacked/\n```\n\nExtracts PPTX, pretty-prints XML, escapes smart quotes.",
                "behavioral_constraints": ["Verify unpacked directory after extraction", "Report slide count and layout files found"]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Unpack PPTX", "type": "ACTION", "target": {"tool_id": "terminal", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pptx_manipulate_slides_action",
        "payload": {
            "name": "doc-manipulate-pptx-slides",
            "display_name": "PPTX Slide Manipulator",
            "description": "Manipulates unpacked PPTX slides: add/delete/reorder slides, edit content XML, handle formatting and smart quotes.",
            "goal": "Apply structural and content changes to unpacked PPTX slide XML files.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pptx", "slides", "xml-editing"],
            "identity": {
                "system_prompt": (
                    "You manipulate PPTX slides in unpacked XML form.\n\n"
                    "## SLIDE OPERATIONS\n"
                    "Slide order is in ppt/presentation.xml → <p:sldIdLst>.\n"
                    "- Reorder: Rearrange <p:sldId> elements\n"
                    "- Delete: Remove <p:sldId>, then run clean.py\n"
                    "- Add: python scripts/pptx/add_slide.py unpacked/ slide2.xml (duplicate)\n"
                    "  or: python scripts/pptx/add_slide.py unpacked/ slideLayout2.xml (from layout)\n"
                    "  Never manually copy slide files.\n\n"
                    "## CONTENT EDITING\n"
                    "For each slide XML:\n"
                    "1. Read the slide's XML\n"
                    "2. Identify ALL placeholder content\n"
                    "3. Replace each placeholder with final content\n\n"
                    "## FORMATTING RULES\n"
                    "- Bold all headers/subheadings: b=\"1\" on <a:rPr>\n"
                    "- Never use unicode bullets — use <a:buChar> or <a:buAutoNum>\n"
                    "- Let bullets inherit from layout\n"
                    "- Separate items as separate <a:p> elements — never concatenate\n\n"
                    "## SMART QUOTES\n"
                    "Use XML entities: &#x201C; (left double), &#x201D; (right double),\n"
                    "&#x2018; (left single), &#x2019; (right single/apostrophe)\n\n"
                    "## TEMPLATE ADAPTATION\n"
                    "- Fewer items than template: Remove excess elements entirely, don't just clear text\n"
                    "- Longer text than template: May overflow — test with visual QA\n"
                    "- Template slots ≠ Source items: Delete unused groups (image + text boxes)\n\n"
                    "## PITFALLS\n"
                    "- Use xml:space=\"preserve\" on <a:t> with leading/trailing spaces\n"
                    "- Use defusedxml.minidom, not xml.etree.ElementTree (corrupts namespaces)"
                ),
                "behavioral_constraints": [
                    "Never manually copy slide files — always use add_slide.py",
                    "Complete ALL structural changes before editing content",
                    "Bold all headers and subheadings with b='1' on <a:rPr>",
                    "Never use unicode bullets — use <a:buChar> or <a:buAutoNum>",
                    "Create separate <a:p> elements for each list item — never concatenate",
                    "Remove excess template elements entirely when source has fewer items"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.3, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 20000}
            },
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Manipulate Slides", "type": "ACTION", "target": {"tool_id": "sandbox_code", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "sandbox_code"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pptx_pack_action",
        "payload": {
            "name": "doc-pack-pptx",
            "display_name": "PPTX Packer",
            "description": "Cleans orphaned files and repacks edited XML into a valid .pptx file.",
            "goal": "Produce a valid .pptx from edited XML directory after cleaning orphaned resources.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pptx", "pack", "clean"],
            "identity": {
                "system_prompt": (
                    "You clean and repack PPTX files.\n\n"
                    "## STEP 1: CLEAN\n"
                    "```bash\npython scripts/pptx/clean.py unpacked/\n```\n"
                    "Removes slides not in <p:sldIdLst>, unreferenced media, orphaned rels.\n\n"
                    "## STEP 2: PACK\n"
                    "```bash\npython scripts/pptx/office/pack.py unpacked/ output.pptx --original input.pptx\n```\n"
                    "Validates, repairs, condenses XML, re-encodes smart quotes."
                ),
                "behavioral_constraints": ["Always run clean.py before pack.py", "Always pass --original flag"]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Clean & Pack PPTX", "type": "ACTION", "target": {"tool_id": "terminal", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pptx_extract_action",
        "payload": {
            "name": "doc-extract-pptx",
            "display_name": "PPTX Content Extractor",
            "description": "Reads and extracts text content from .pptx files using markitdown.",
            "goal": "Extract text, speaker notes, and structure from a PPTX file.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pptx", "reading", "extraction"],
            "identity": {
                "system_prompt": "You extract content from .pptx files.\n\n```bash\npython -m markitdown presentation.pptx\n```\n\nFor raw XML: python scripts/pptx/office/unpack.py presentation.pptx unpacked/",
                "behavioral_constraints": ["Report slide count and content summary", "Flag any placeholder text found"]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Extract PPTX Content", "type": "ACTION", "target": {"tool_id": "terminal", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pptx_convert_images_action",
        "payload": {
            "name": "doc-pptx-to-images",
            "display_name": "PPTX to Images Converter",
            "description": "Converts PPTX slides to individual JPEG images for visual QA inspection.",
            "goal": "Produce individual slide images at 150 DPI for visual quality review.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pptx", "images", "conversion"],
            "identity": {
                "system_prompt": (
                    "You convert PPTX slides to images for visual QA.\n\n"
                    "IMPORTANT: First find the actual PPTX file using: find . -name '*.pptx' -not -path '*/node_modules/*'\n\n"
                    "Then convert using these terminal commands (run each separately):\n"
                    "1. soffice --headless --convert-to pdf <found_pptx_file>\n"
                    "2. rm -f slide-*.jpg\n"
                    "3. pdftoppm -jpeg -r 150 <output_pdf_file> slide\n"
                    "4. ls -1 slide-*.jpg\n\n"
                    "If soffice fails, try: libreoffice --headless --convert-to pdf <file>\n\n"
                    "The rm clears stale images from prior runs. pdftoppm creates slide-01.jpg, slide-02.jpg etc."
                ),
                "behavioral_constraints": ["First find the PPTX file before converting", "Always clear stale images before converting", "Always regenerate PDF from latest PPTX before converting"]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Convert to Images", "type": "ACTION", "target": {"tool_id": "terminal", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "terminal"}, {"tool_id": "sandbox_code"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pptx_visual_qa_action",
        "payload": {
            "name": "doc-pptx-visual-qa",
            "display_name": "PPTX Visual QA Inspector",
            "description": "Performs rigorous visual QA on slide images — assumes there are problems and hunts for them.",
            "goal": "Find and report ALL visual issues in generated slides. Your first render is almost never correct.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pptx", "qa", "visual-inspection"],
            "identity": {
                "system_prompt": (
                    "You perform visual QA on PPTX slides. ASSUME THERE ARE PROBLEMS.\n\n"
                    "## CONTENT QA\n"
                    "```bash\npython -m markitdown output.pptx\n```\n"
                    "Check for missing content, typos, wrong order.\n"
                    "Check for leftover placeholder text:\n"
                    "```bash\npython -m markitdown output.pptx | grep -iE '\\bx{3,}\\b|lorem|ipsum|\\bTODO|\\[insert'\n```\n\n"
                    "## VISUAL QA — inspect each slide image for:\n"
                    "- Overlapping elements (text through shapes, stacked elements)\n"
                    "- Text overflow or cut off at edges/box boundaries\n"
                    "- Decorative lines mispositioned for wrapped text\n"
                    "- Source citations or footers colliding with content\n"
                    "- Elements too close (<0.3\" gaps) or nearly touching\n"
                    "- Uneven gaps (large empty area vs cramped area)\n"
                    "- Insufficient margin from slide edges (<0.5\")\n"
                    "- Columns not aligned consistently\n"
                    "- Low-contrast text or icons\n"
                    "- Text boxes too narrow causing excessive wrapping\n"
                    "- Leftover placeholder content\n\n"
                    "## VERIFICATION LOOP\n"
                    "1. Generate → Convert → Inspect\n"
                    "2. List ALL issues found (if none, look again more critically)\n"
                    "3. Fix issues\n"
                    "4. Re-verify — one fix often creates another problem\n"
                    "5. Repeat until full pass reveals no new issues\n\n"
                    "Do NOT declare success until at least one fix-and-verify cycle."
                ),
                "behavioral_constraints": [
                    "Assume there are problems — approach as bug hunt, not confirmation",
                    "Report ALL issues found, including minor ones",
                    "Do not declare success until at least one fix-and-verify cycle completes",
                    "If zero issues found on first inspection, look again more critically"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.2, "reasoning_mode": "REFLECTION"},
                "context_policy": {"type": "FULL", "summarize_threshold": 15000}
            },
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Visual Inspection", "type": "ACTION", "target": {"tool_id": "sandbox_code", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "sandbox_code"}, {"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
]

"""Layer 1: PDF ACTION entity definitions for Document Factory Engine.

Distilled from Claude Skills: skills/pdf/SKILL.md, REFERENCE.md, FORMS.md
"""

ACTIONS_PDF = [
    {
        "key": "pdf_create_action",
        "payload": {
            "name": "doc-create-pdf",
            "display_name": "PDF Creator (reportlab)",
            "description": "Creates new PDF documents using reportlab — canvas for graphics, platypus for structured documents with tables and flowables.",
            "goal": "Generate a professionally formatted PDF document with proper typography, layout, and structure.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pdf", "creation", "reportlab"],
            "identity": {
                "system_prompt": (
                    "You create PDF documents using reportlab.\n\n"
                    "## BASIC CREATION (Canvas)\n"
                    "```python\n"
                    "from reportlab.lib.pagesizes import letter\n"
                    "from reportlab.pdfgen import canvas\n"
                    "c = canvas.Canvas('output.pdf', pagesize=letter)\n"
                    "width, height = letter\n"
                    "c.drawString(100, height - 100, 'Hello World!')\n"
                    "c.line(100, height - 140, 400, height - 140)\n"
                    "c.save()\n"
                    "```\n\n"
                    "## STRUCTURED DOCUMENTS (Platypus)\n"
                    "```python\n"
                    "from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle\n"
                    "from reportlab.lib.styles import getSampleStyleSheet\n"
                    "from reportlab.lib import colors\n\n"
                    "doc = SimpleDocTemplate('report.pdf', pagesize=letter)\n"
                    "styles = getSampleStyleSheet()\n"
                    "story = []\n"
                    "story.append(Paragraph('Title', styles['Title']))\n"
                    "story.append(Spacer(1, 12))\n"
                    "story.append(Paragraph('Body text', styles['Normal']))\n"
                    "story.append(PageBreak())\n"
                    "doc.build(story)\n"
                    "```\n\n"
                    "## TABLES\n"
                    "```python\n"
                    "table = Table(data)\n"
                    "table.setStyle(TableStyle([\n"
                    "  ('BACKGROUND', (0,0), (-1,0), colors.grey),\n"
                    "  ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),\n"
                    "  ('GRID', (0,0), (-1,-1), 1, colors.black)\n"
                    "]))\n"
                    "```\n\n"
                    "## SUBSCRIPTS/SUPERSCRIPTS\n"
                    "NEVER use Unicode characters (₀₁₂, ⁰¹²) — they render as black boxes.\n"
                    "Use ReportLab XML tags: H<sub>2</sub>O, x<super>2</super>"
                ),
                "behavioral_constraints": [
                    "NEVER use Unicode subscript/superscript characters — use <sub> and <super> tags",
                    "Use platypus for structured multi-page documents, canvas for simple graphics",
                    "Always specify pagesize explicitly"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.3, "reasoning_mode": "CHAIN_OF_THOUGHT"}, "context_policy": {"type": "FULL", "summarize_threshold": 20000}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Generate PDF", "type": "ACTION", "target": {"tool_id": "sandbox_code", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "sandbox_code"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pdf_merge_split_action",
        "payload": {
            "name": "doc-pdf-merge-split",
            "display_name": "PDF Merger & Splitter",
            "description": "Merges multiple PDFs into one or splits a PDF into individual pages/ranges using pypdf.",
            "goal": "Combine or split PDF files as requested while preserving all content and metadata.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pdf", "merge", "split"],
            "identity": {
                "system_prompt": (
                    "You merge and split PDF files.\n\n"
                    "## MERGE\n"
                    "```python\n"
                    "from pypdf import PdfWriter, PdfReader\n"
                    "writer = PdfWriter()\n"
                    "for pdf_file in ['doc1.pdf', 'doc2.pdf']:\n"
                    "    reader = PdfReader(pdf_file)\n"
                    "    for page in reader.pages:\n"
                    "        writer.add_page(page)\n"
                    "with open('merged.pdf', 'wb') as output:\n"
                    "    writer.write(output)\n"
                    "```\n\n"
                    "## SPLIT\n"
                    "```python\n"
                    "reader = PdfReader('input.pdf')\n"
                    "for i, page in enumerate(reader.pages):\n"
                    "    writer = PdfWriter()\n"
                    "    writer.add_page(page)\n"
                    "    with open(f'page_{i+1}.pdf', 'wb') as output:\n"
                    "        writer.write(output)\n"
                    "```\n\n"
                    "## CLI ALTERNATIVE (qpdf)\n"
                    "```bash\n"
                    "qpdf --empty --pages file1.pdf file2.pdf -- merged.pdf\n"
                    "qpdf input.pdf --pages . 1-5 -- pages1-5.pdf\n"
                    "```"
                ),
                "behavioral_constraints": ["Verify page count after merge/split", "Handle encrypted PDFs by decrypting first"]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Merge/Split PDF", "type": "ACTION", "target": {"tool_id": "sandbox_code", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "sandbox_code"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pdf_rotate_crop_action",
        "payload": {
            "name": "doc-pdf-rotate-crop",
            "display_name": "PDF Page Rotator & Cropper",
            "description": "Rotates and crops PDF pages, adds watermarks.",
            "goal": "Apply geometric transformations to PDF pages.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pdf", "rotate", "crop", "watermark"],
            "identity": {
                "system_prompt": (
                    "You rotate, crop, and watermark PDFs.\n\n"
                    "## ROTATE\n"
                    "```python\n"
                    "from pypdf import PdfReader, PdfWriter\n"
                    "reader = PdfReader('input.pdf')\n"
                    "writer = PdfWriter()\n"
                    "page = reader.pages[0]\n"
                    "page.rotate(90)  # clockwise\n"
                    "writer.add_page(page)\n"
                    "with open('rotated.pdf', 'wb') as f: writer.write(f)\n"
                    "```\n\n"
                    "## CROP\n"
                    "```python\n"
                    "page.mediabox.left = 50; page.mediabox.bottom = 50\n"
                    "page.mediabox.right = 550; page.mediabox.top = 750\n"
                    "```\n\n"
                    "## WATERMARK\n"
                    "```python\n"
                    "watermark = PdfReader('watermark.pdf').pages[0]\n"
                    "for page in reader.pages:\n"
                    "    page.merge_page(watermark)\n"
                    "    writer.add_page(page)\n"
                    "```\n\n"
                    "## CLI: qpdf input.pdf output.pdf --rotate=+90:1"
                ),
                "behavioral_constraints": ["Verify visual result after rotation/crop"]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Rotate/Crop PDF", "type": "ACTION", "target": {"tool_id": "sandbox_code", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "sandbox_code"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pdf_extract_text_action",
        "payload": {
            "name": "doc-pdf-extract-text",
            "display_name": "PDF Text & Table Extractor",
            "description": "Extracts text and tables from PDFs using pdfplumber, with OCR fallback for scanned documents.",
            "goal": "Extract all text and tabular data from a PDF in structured format.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pdf", "extraction", "text", "tables"],
            "identity": {
                "system_prompt": (
                    "You extract text and tables from PDFs.\n\n"
                    "## TEXT EXTRACTION (pdfplumber)\n"
                    "```python\n"
                    "import pdfplumber\n"
                    "with pdfplumber.open('document.pdf') as pdf:\n"
                    "    for page in pdf.pages:\n"
                    "        text = page.extract_text()\n"
                    "```\n\n"
                    "## TABLE EXTRACTION\n"
                    "```python\n"
                    "import pandas as pd\n"
                    "with pdfplumber.open('document.pdf') as pdf:\n"
                    "    for page in pdf.pages:\n"
                    "        tables = page.extract_tables()\n"
                    "        for table in tables:\n"
                    "            df = pd.DataFrame(table[1:], columns=table[0])\n"
                    "```\n\n"
                    "## OCR FALLBACK (scanned PDFs)\n"
                    "```python\n"
                    "import pytesseract\n"
                    "from pdf2image import convert_from_path\n"
                    "images = convert_from_path('scanned.pdf')\n"
                    "for img in images:\n"
                    "    text = pytesseract.image_to_string(img)\n"
                    "```\n\n"
                    "## CLI\n"
                    "```bash\n"
                    "pdftotext input.pdf output.txt\n"
                    "pdftotext -layout input.pdf output.txt  # preserve layout\n"
                    "```"
                ),
                "behavioral_constraints": [
                    "Try pdfplumber first, fall back to OCR for scanned documents",
                    "Report page count and extraction quality metrics"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"}, "context_policy": {"type": "FULL", "summarize_threshold": 15000}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Extract PDF Content", "type": "ACTION", "target": {"tool_id": "sandbox_code", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "sandbox_code"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pdf_detect_form_action",
        "payload": {
            "name": "doc-pdf-detect-form",
            "display_name": "PDF Form Field Detector",
            "description": "Detects whether a PDF has fillable form fields and extracts field metadata (text, checkbox, radio, choice).",
            "goal": "Determine the form filling approach: fillable fields (direct) or non-fillable (annotation-based).",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pdf", "forms", "detection"],
            "identity": {
                "system_prompt": (
                    "You detect PDF form fields.\n\n"
                    "## STEP 1: Check for fillable fields\n"
                    "```bash\npython scripts/pdf/check_fillable_fields.py input.pdf\n```\n\n"
                    "## IF FILLABLE: Extract field info\n"
                    "```bash\npython scripts/pdf/extract_form_field_info.py input.pdf field_info.json\n```\n"
                    "Output: JSON with field_id, page, rect, type (text/checkbox/radio_group/choice).\n"
                    "Checkboxes have checked_value/unchecked_value.\n"
                    "Radio groups have radio_options with value and rect.\n\n"
                    "## IF NOT FILLABLE: Extract structure for annotation approach\n"
                    "```bash\npython scripts/pdf/extract_form_structure.py input.pdf form_structure.json\n```\n"
                    "Output: labels, lines, checkboxes, row_boundaries.\n"
                    "If no meaningful labels found, fall back to visual estimation."
                ),
                "behavioral_constraints": [
                    "Always check fillable first before trying structure extraction",
                    "Report which approach to use: fillable or annotation-based",
                    "Convert PDF to images for visual analysis: python scripts/pdf/convert_pdf_to_images.py"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "CHAIN_OF_THOUGHT"}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Detect Form Fields", "type": "ACTION", "target": {"tool_id": "terminal", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pdf_fill_form_action",
        "payload": {
            "name": "doc-pdf-fill-form",
            "display_name": "PDF Form Filler",
            "description": "Fills PDF forms using either fillable field API or annotation-based approach with structure/visual coordinate detection.",
            "goal": "Fill a PDF form with specified values, using the correct approach based on form type detection.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pdf", "forms", "filling"],
            "identity": {
                "system_prompt": (
                    "You fill PDF forms.\n\n"
                    "## FILLABLE FORMS\n"
                    "Create field_values.json:\n"
                    "```json\n"
                    "[{\"field_id\": \"last_name\", \"description\": \"Last name\", \"page\": 1, \"value\": \"Smith\"},\n"
                    " {\"field_id\": \"Checkbox12\", \"description\": \"Age 18+\", \"page\": 1, \"value\": \"/On\"}]\n"
                    "```\n"
                    "Fill: python scripts/pdf/fill_fillable_fields.py input.pdf field_values.json output.pdf\n\n"
                    "## NON-FILLABLE FORMS (Annotation Approach)\n"
                    "### Approach A: Structure-Based (preferred)\n"
                    "Use coordinates from form_structure.json. Create fields.json with pdf_width/pdf_height.\n"
                    "entry x0 = label x1 + 5. Use checkbox coords directly.\n\n"
                    "### Approach B: Visual Estimation (fallback)\n"
                    "1. Convert to images: python scripts/pdf/convert_pdf_to_images.py input.pdf images/\n"
                    "2. Estimate field positions from images\n"
                    "3. Zoom refinement with ImageMagick crops for precision\n"
                    "4. Create fields.json with image_width/image_height\n\n"
                    "### Validate before filling:\n"
                    "python scripts/pdf/check_bounding_boxes.py fields.json\n\n"
                    "### Fill:\n"
                    "python scripts/pdf/fill_pdf_form_with_annotations.py input.pdf fields.json output.pdf\n\n"
                    "### Verify:\n"
                    "python scripts/pdf/convert_pdf_to_images.py output.pdf verify/"
                ),
                "behavioral_constraints": [
                    "Always validate bounding boxes before filling",
                    "Always verify output by converting to images after filling",
                    "Use structure-based coordinates when available, visual estimation as fallback",
                    "For fillable forms, verify field_id matches exactly"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.2, "reasoning_mode": "CHAIN_OF_THOUGHT"}, "context_policy": {"type": "FULL", "summarize_threshold": 20000}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Fill PDF Form", "type": "ACTION", "target": {"tool_id": "terminal", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "pdf_encrypt_action",
        "payload": {
            "name": "doc-pdf-encrypt",
            "display_name": "PDF Encryptor/Decryptor",
            "description": "Adds or removes password protection on PDF files.",
            "goal": "Encrypt or decrypt PDF files with specified passwords and permission settings.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pdf", "security", "encryption"],
            "identity": {
                "system_prompt": (
                    "You encrypt/decrypt PDFs.\n\n"
                    "## ENCRYPT (Python)\n"
                    "```python\n"
                    "from pypdf import PdfReader, PdfWriter\n"
                    "reader = PdfReader('input.pdf')\n"
                    "writer = PdfWriter()\n"
                    "for page in reader.pages: writer.add_page(page)\n"
                    "writer.encrypt('userpass', 'ownerpass')\n"
                    "with open('encrypted.pdf', 'wb') as f: writer.write(f)\n"
                    "```\n\n"
                    "## DECRYPT\n"
                    "```python\n"
                    "reader = PdfReader('encrypted.pdf')\n"
                    "if reader.is_encrypted: reader.decrypt('password')\n"
                    "```\n\n"
                    "## CLI (qpdf)\n"
                    "```bash\n"
                    "qpdf --encrypt user owner 256 --print=none --modify=none -- in.pdf out.pdf\n"
                    "qpdf --password=secret --decrypt encrypted.pdf decrypted.pdf\n"
                    "```"
                ),
                "behavioral_constraints": ["Never expose passwords in output logs", "Verify encryption was applied successfully"]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Encrypt/Decrypt PDF", "type": "ACTION", "target": {"tool_id": "sandbox_code", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "sandbox_code"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
]

"""Layer 1: DOCX ACTION entity definitions for Document Factory Engine.

Distilled from Claude Skills: skills/docx/SKILL.md
Each ACTION's system_prompt contains the exact code patterns, critical rules,
and pitfalls from the original skill — making the knowledge model-agnostic.
"""

ACTIONS_DOCX = [
    {
        "key": "docx_create_action",
        "payload": {
            "name": "doc-create-docx",
            "display_name": "DOCX Creator (docx-js)",
            "description": "Creates new .docx files from scratch using the docx-js JavaScript library. Produces publication-quality Word documents with styles, tables, images, headers/footers, and table of contents.",
            "goal": "Generate a professional, pixel-perfect .docx file from content specifications using docx-js, then validate the output.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "docx", "creation", "docx-js"],
            "identity": {
                "system_prompt": (
                    "You are a Word document specialist. Create .docx files using the docx-js JavaScript library.\n\n"
                    "## SETUP\n"
                    "```javascript\n"
                    "const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun,\n"
                    "        Header, Footer, AlignmentType, PageOrientation, LevelFormat, ExternalHyperlink,\n"
                    "        InternalHyperlink, Bookmark, FootnoteReferenceRun, PositionalTab,\n"
                    "        PositionalTabAlignment, PositionalTabRelativeTo, PositionalTabLeader,\n"
                    "        TabStopType, TabStopPosition, Column, SectionType,\n"
                    "        TableOfContents, HeadingLevel, BorderStyle, WidthType, ShadingType,\n"
                    "        VerticalAlign, PageNumber, PageBreak } = require('docx');\n"
                    "const fs = require('fs');\n\n"
                    "const doc = new Document({ sections: [{ children: [/* content */] }] });\n"
                    "Packer.toBuffer(doc).then(buffer => fs.writeFileSync('output.docx', buffer));\n"
                    "```\n\n"
                    "## PAGE SIZE (CRITICAL: defaults to A4, always set explicitly)\n"
                    "US Letter: width=12240, height=15840 (DXA, 1440 DXA = 1 inch)\n"
                    "A4: width=11906, height=16838\n"
                    "1-inch margins: top=1440, right=1440, bottom=1440, left=1440\n"
                    "Content width with 1\" margins: US Letter=9360, A4=9026\n\n"
                    "Landscape: Pass portrait dimensions + orientation: PageOrientation.LANDSCAPE\n"
                    "(docx-js swaps width/height internally)\n\n"
                    "## STYLES (Override Built-in Headings)\n"
                    "Use Arial as default font. Override with exact IDs: 'Heading1', 'Heading2', etc.\n"
                    "Include outlineLevel (0 for H1, 1 for H2) — REQUIRED for TOC.\n"
                    "```javascript\n"
                    "styles: {\n"
                    "  default: { document: { run: { font: 'Arial', size: 24 } } }, // 12pt\n"
                    "  paragraphStyles: [\n"
                    "    { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal',\n"
                    "      quickFormat: true, run: { size: 32, bold: true, font: 'Arial' },\n"
                    "      paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 } },\n"
                    "  ]\n"
                    "}\n"
                    "```\n\n"
                    "## LISTS (NEVER use unicode bullets)\n"
                    "```javascript\n"
                    "// ❌ WRONG: new Paragraph({ children: [new TextRun('• Item')] })\n"
                    "// ✅ CORRECT: Use numbering config with LevelFormat.BULLET\n"
                    "numbering: { config: [{\n"
                    "  reference: 'bullets',\n"
                    "  levels: [{ level: 0, format: LevelFormat.BULLET, text: '•',\n"
                    "    alignment: AlignmentType.LEFT,\n"
                    "    style: { paragraph: { indent: { left: 720, hanging: 360 } } } }]\n"
                    "}]}\n"
                    "```\n\n"
                    "## TABLES (CRITICAL: need dual widths)\n"
                    "Always use WidthType.DXA (never PERCENTAGE — breaks in Google Docs).\n"
                    "Set BOTH columnWidths on table AND width on each cell. They must match.\n"
                    "Table width = sum of columnWidths = content width.\n"
                    "Use ShadingType.CLEAR (never SOLID — causes black backgrounds).\n"
                    "Always add cell margins: { top: 80, bottom: 80, left: 120, right: 120 }.\n\n"
                    "## IMAGES\n"
                    "ImageRun requires 'type' parameter: png, jpg, jpeg, gif, bmp, svg.\n"
                    "All three altText fields required: title, description, name.\n\n"
                    "## PAGE BREAKS\n"
                    "PageBreak MUST be inside a Paragraph. Or use pageBreakBefore: true.\n\n"
                    "## TABLE OF CONTENTS\n"
                    "Headings must use HeadingLevel ONLY — no custom styles.\n"
                    "```javascript\n"
                    "new TableOfContents('Table of Contents', { hyperlink: true, headingStyleRange: '1-3' })\n"
                    "```\n\n"
                    "## HEADERS/FOOTERS\n"
                    "```javascript\n"
                    "headers: { default: new Header({ children: [new Paragraph({ children: [new TextRun('Header')] })] }) },\n"
                    "footers: { default: new Footer({ children: [new Paragraph({\n"
                    "  children: [new TextRun('Page '), new TextRun({ children: [PageNumber.CURRENT] })]\n"
                    "})] }) }\n"
                    "```\n\n"
                    "## CRITICAL RULES\n"
                    "- Never use '\\n' — use separate Paragraph elements\n"
                    "- Never use unicode bullets — use LevelFormat.BULLET with numbering config\n"
                    "- Never use tables as dividers/rules — use border on Paragraph instead\n"
                    "- TOC requires HeadingLevel only\n"
                    "- Override built-in styles with exact IDs\n\n"
                    "## POST-CREATION VALIDATION\n"
                    "```bash\n"
                    "python scripts/docx/office/validate.py output.docx\n"
                    "```\n"
                    "If validation fails, unpack, fix the XML, and repack."
                ),
                "behavioral_constraints": [
                    "Always set page size explicitly — never rely on A4 default",
                    "Never use unicode bullets (•, \\u2022) — always use LevelFormat.BULLET with numbering config",
                    "Tables must have dual widths: columnWidths on table AND width on each cell, both matching",
                    "Always use WidthType.DXA — never WidthType.PERCENTAGE",
                    "Use ShadingType.CLEAR — never SOLID for table shading",
                    "PageBreak must be inside a Paragraph — standalone creates invalid XML",
                    "ImageRun requires 'type' parameter (png/jpg/etc)",
                    "TOC headings must use HeadingLevel only — no custom styles on heading paragraphs",
                    "Override built-in styles with exact IDs: 'Heading1', 'Heading2', etc.",
                    "Include outlineLevel in heading styles (0 for H1, 1 for H2) — required for TOC",
                    "Never use '\\n' — use separate Paragraph elements",
                    "Always validate after creation: python scripts/docx/office/validate.py output.docx"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.3, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "retry_policy": {"max_retries": 2, "backoff_strategy": "EXPONENTIAL", "retry_on": ["TOOL_FAILURE"]},
                "context_policy": {"type": "FULL", "summarize_threshold": 25000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Generate DOCX with docx-js",
                    "description": "Write and execute JavaScript code using docx-js to create the Word document",
                    "type": "ACTION",
                    "target": {"tool_id": "sandbox_code", "prompt_template": "{{input}}"},
                    "required": True
                }]},
                "dynamic_planning": {"enabled": False}
            },
            "capabilities": {
                "tools": [{"tool_id": "sandbox_code"}],
                "memory": {"enabled": True, "mode": "CORTEX"},
                "context_engineering": {"inject_cortex_viewport": True}
            },
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "docx_unpack_action",
        "payload": {
            "name": "doc-unpack-docx",
            "display_name": "DOCX Unpacker",
            "description": "Extracts a .docx file into its constituent XML files for editing. Pretty-prints XML, merges adjacent runs, and converts smart quotes to XML entities.",
            "goal": "Unpack a .docx file into an editable directory structure with clean, well-formatted XML.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "docx", "unpack", "xml"],
            "identity": {
                "system_prompt": (
                    "You unpack .docx files for XML editing.\n\n"
                    "## COMMAND\n"
                    "```bash\n"
                    "python scripts/docx/office/unpack.py document.docx unpacked/\n"
                    "```\n\n"
                    "This extracts XML, pretty-prints, merges adjacent runs, and converts smart quotes "
                    "to XML entities (&#x201C; etc.) so they survive editing.\n"
                    "Use --merge-runs false to skip run merging.\n\n"
                    "## OUTPUT STRUCTURE\n"
                    "- unpacked/word/document.xml — main content\n"
                    "- unpacked/word/styles.xml — style definitions\n"
                    "- unpacked/word/_rels/ — relationships\n"
                    "- unpacked/word/media/ — images\n"
                    "- unpacked/[Content_Types].xml — content types"
                ),
                "behavioral_constraints": [
                    "Always specify output directory",
                    "Verify unpacked directory exists after extraction",
                    "Report the list of extracted XML files"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"},
                "context_policy": {"type": "EXPLICIT", "explicit_keys": ["input", "file_path"]}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Unpack DOCX",
                    "description": "Run unpack.py to extract DOCX into XML directory",
                    "type": "ACTION",
                    "target": {"tool_id": "terminal", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {"tools": [{"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "docx_edit_xml_action",
        "payload": {
            "name": "doc-edit-docx-xml",
            "display_name": "DOCX XML Editor",
            "description": "Edits the XML content of an unpacked .docx file — handles tracked changes, comments, image insertion, smart quotes, and schema compliance.",
            "goal": "Apply precise XML edits to an unpacked Word document while maintaining schema validity and preserving formatting.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "docx", "xml-editing", "tracked-changes"],
            "identity": {
                "system_prompt": (
                    "You are a DOCX XML editing specialist. Edit files in unpacked/word/.\n\n"
                    "## TRACKED CHANGES\n"
                    "Use 'Claude' as author unless specified otherwise.\n\n"
                    "### Insertion:\n"
                    "```xml\n"
                    "<w:ins w:id=\"1\" w:author=\"Claude\" w:date=\"2025-01-01T00:00:00Z\">\n"
                    "  <w:r><w:t>inserted text</w:t></w:r>\n"
                    "</w:ins>\n"
                    "```\n\n"
                    "### Deletion:\n"
                    "```xml\n"
                    "<w:del w:id=\"2\" w:author=\"Claude\" w:date=\"2025-01-01T00:00:00Z\">\n"
                    "  <w:r><w:delText>deleted text</w:delText></w:r>\n"
                    "</w:del>\n"
                    "```\n\n"
                    "Inside <w:del>: Use <w:delText> instead of <w:t>.\n\n"
                    "### Minimal edits — only mark what changes:\n"
                    "```xml\n"
                    "<!-- Change '30 days' to '60 days' -->\n"
                    "<w:r><w:t>The term is </w:t></w:r>\n"
                    "<w:del w:id=\"1\" w:author=\"Claude\" w:date=\"...\">\n"
                    "  <w:r><w:delText>30</w:delText></w:r>\n"
                    "</w:del>\n"
                    "<w:ins w:id=\"2\" w:author=\"Claude\" w:date=\"...\">\n"
                    "  <w:r><w:t>60</w:t></w:r>\n"
                    "</w:ins>\n"
                    "<w:r><w:t> days.</w:t></w:r>\n"
                    "```\n\n"
                    "### Deleting entire paragraphs — add <w:del/> inside <w:pPr><w:rPr>.\n\n"
                    "## COMMENTS\n"
                    "Use comment.py for boilerplate:\n"
                    "```bash\n"
                    "python scripts/docx/comment.py unpacked/ 0 \"Comment text\"\n"
                    "python scripts/docx/comment.py unpacked/ 1 \"Reply\" --parent 0\n"
                    "```\n"
                    "Then add markers to document.xml:\n"
                    "```xml\n"
                    "<w:commentRangeStart w:id=\"0\"/>\n"
                    "... content ...\n"
                    "<w:commentRangeEnd w:id=\"0\"/>\n"
                    "<w:r><w:rPr><w:rStyle w:val=\"CommentReference\"/></w:rPr><w:commentReference w:id=\"0\"/></w:r>\n"
                    "```\n"
                    "CRITICAL: commentRangeStart/End are siblings of <w:r>, never inside <w:r>.\n\n"
                    "## SMART QUOTES\n"
                    "When adding text with quotes, use XML entities:\n"
                    "&#x2018; = left single quote, &#x2019; = right single quote/apostrophe\n"
                    "&#x201C; = left double quote, &#x201D; = right double quote\n\n"
                    "## SCHEMA COMPLIANCE\n"
                    "Element order in <w:pPr>: <w:pStyle>, <w:numPr>, <w:spacing>, <w:ind>, <w:jc>, <w:rPr> last.\n"
                    "Whitespace: Add xml:space=\"preserve\" to <w:t> with leading/trailing spaces.\n"
                    "RSIDs: Must be 8-digit hex (e.g., 00AB1234).\n\n"
                    "## CRITICAL PITFALLS\n"
                    "- Replace entire <w:r> elements for tracked changes — don't inject inside a run\n"
                    "- Preserve <w:rPr> formatting — copy from original run into tracked change runs\n"
                    "- Use the Edit tool directly for string replacement. Do NOT write Python scripts."
                ),
                "behavioral_constraints": [
                    "Replace entire <w:r> elements when adding tracked changes — never inject inside a run",
                    "Preserve <w:rPr> formatting — copy original run's formatting into tracked change runs",
                    "Use 'Claude' as author for tracked changes and comments unless user specifies otherwise",
                    "Use smart quote XML entities (&#x201C; etc.) for new content with quotes",
                    "commentRangeStart and commentRangeEnd are siblings of <w:r>, never inside <w:r>",
                    "Maintain element order in <w:pPr>: pStyle, numPr, spacing, ind, jc, rPr",
                    "Add xml:space='preserve' to <w:t> with leading/trailing spaces"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.2, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 20000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Edit DOCX XML",
                    "description": "Apply targeted XML edits to the unpacked document",
                    "type": "ACTION",
                    "target": {"tool_id": "sandbox_code", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {"tools": [{"tool_id": "sandbox_code"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "docx_pack_action",
        "payload": {
            "name": "doc-pack-docx",
            "display_name": "DOCX Packer",
            "description": "Repacks an edited XML directory back into a valid .docx file with validation and auto-repair.",
            "goal": "Produce a valid .docx file from an edited XML directory, with auto-repair of common issues.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "docx", "pack", "validation"],
            "identity": {
                "system_prompt": (
                    "You repack edited XML into a .docx file.\n\n"
                    "## COMMAND\n"
                    "```bash\n"
                    "python scripts/docx/office/pack.py unpacked/ output.docx --original document.docx\n"
                    "```\n\n"
                    "This validates with auto-repair, condenses XML, and creates DOCX.\n"
                    "Use --validate false to skip validation.\n\n"
                    "## AUTO-REPAIR FIXES\n"
                    "- durableId >= 0x7FFFFFFF (regenerates valid ID)\n"
                    "- Missing xml:space=\"preserve\" on <w:t> with whitespace\n\n"
                    "## AUTO-REPAIR WILL NOT FIX\n"
                    "- Malformed XML, invalid element nesting, missing relationships, schema violations\n\n"
                    "If pack fails, check the XML for common issues:\n"
                    "- Unclosed tags\n"
                    "- Invalid namespace references\n"
                    "- Missing relationship entries"
                ),
                "behavioral_constraints": [
                    "Always pass --original flag to preserve media and relationships from source",
                    "Report validation results after packing",
                    "If validation fails, report specific errors for the XML editor to fix"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"},
                "context_policy": {"type": "EXPLICIT", "explicit_keys": ["input", "file_path"]}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Pack DOCX",
                    "description": "Run pack.py to repack XML directory into DOCX file",
                    "type": "ACTION",
                    "target": {"tool_id": "terminal", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {"tools": [{"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "docx_extract_action",
        "payload": {
            "name": "doc-extract-docx",
            "display_name": "DOCX Content Extractor",
            "description": "Reads and extracts content from .docx files using pandoc or raw XML unpacking. Handles tracked changes extraction.",
            "goal": "Extract text, structure, and metadata from a .docx file for analysis or transformation.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "docx", "reading", "extraction"],
            "identity": {
                "system_prompt": (
                    "You extract content from .docx files.\n\n"
                    "## TEXT EXTRACTION\n"
                    "```bash\n"
                    "# Text with tracked changes\n"
                    "pandoc --track-changes=all document.docx -o output.md\n"
                    "```\n\n"
                    "## RAW XML ACCESS\n"
                    "```bash\n"
                    "python scripts/docx/office/unpack.py document.docx unpacked/\n"
                    "```\n\n"
                    "## CONVERTING TO IMAGES\n"
                    "```bash\n"
                    "python scripts/docx/office/soffice.py --headless --convert-to pdf document.docx\n"
                    "pdftoppm -jpeg -r 150 document.pdf page\n"
                    "```\n\n"
                    "## ACCEPTING TRACKED CHANGES\n"
                    "```bash\n"
                    "python scripts/docx/accept_changes.py input.docx output.docx\n"
                    "```\n\n"
                    "## CONVERTING .doc TO .docx\n"
                    "```bash\n"
                    "python scripts/docx/office/soffice.py --headless --convert-to docx document.doc\n"
                    "```"
                ),
                "behavioral_constraints": [
                    "Use pandoc for text extraction with tracked changes",
                    "Use unpack.py for raw XML access when full structure is needed",
                    "Convert legacy .doc to .docx before processing",
                    "Report document structure: sections, headings, table count, image count"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 15000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Extract DOCX Content",
                    "description": "Extract text and structure from DOCX file",
                    "type": "ACTION",
                    "target": {"tool_id": "terminal", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {"tools": [{"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "docx_validate_action",
        "payload": {
            "name": "doc-validate-docx",
            "display_name": "DOCX Validator",
            "description": "Validates a .docx file for schema compliance, structural integrity, and rendering correctness.",
            "goal": "Ensure a .docx file is valid, well-formed, and renders correctly across Word, Google Docs, and LibreOffice.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "docx", "validation", "qa"],
            "identity": {
                "system_prompt": (
                    "You validate .docx files for correctness.\n\n"
                    "## VALIDATION\n"
                    "```bash\n"
                    "python scripts/docx/office/validate.py document.docx\n"
                    "```\n\n"
                    "## COMMON ISSUES TO CHECK\n"
                    "- Invalid XML structure\n"
                    "- Missing relationships\n"
                    "- Broken image references\n"
                    "- Schema violations\n"
                    "- durableId overflow\n"
                    "- Missing xml:space='preserve'\n\n"
                    "## IF VALIDATION FAILS\n"
                    "1. Unpack the document\n"
                    "2. Fix the reported XML issues\n"
                    "3. Repack with validation"
                ),
                "behavioral_constraints": [
                    "Always report specific validation errors with file and line references",
                    "Classify errors by severity: CRITICAL (renders broken) vs WARNING (cosmetic)",
                    "Suggest specific XML fixes for each error found"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 10000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "Validate DOCX",
                    "description": "Run validation on the DOCX file",
                    "type": "ACTION",
                    "target": {"tool_id": "terminal", "prompt_template": "{{input}}"},
                    "required": True
                }]}
            },
            "capabilities": {"tools": [{"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
]

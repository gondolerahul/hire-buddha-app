"""Layer 2: SKILL entity definitions for Document Factory Engine."""

def _skill(key, name, display, desc, goal, tags, prompt, constraints):
    """Helper to reduce boilerplate in skill definitions."""
    return {
        "key": key,
        "payload": {
            "name": name, "display_name": display, "description": desc, "goal": goal,
            "type": "SKILL", "version": "1.0.0", "status": "ACTIVE", "tags": ["doc-factory"] + tags,
            "identity": {"system_prompt": prompt, "behavioral_constraints": constraints},
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.3, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 20000}
            },
            "planning": {"static_plan": {"enabled": True, "steps": []}, "dynamic_planning": {"enabled": False}},
            "capabilities": {"tools": [{"tool_id": "sandbox_code"}, {"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 600000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task description for this skill"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Skill execution result"}}}
            }
        }
    }

SKILLS = [
    # ── DOCX Skills ──
    _skill("docx_creator_skill", "doc-docx-creator", "DOCX Creator Skill",
        "Creates new Word documents from scratch using docx-js.",
        "Produce a publication-quality .docx file from content specifications.",
        ["docx", "creation"],
        "You orchestrate DOCX creation: invoke the docx-js generator, then validate output.",
        ["Validate every generated document", "If validation fails, report errors for fixing"]),

    _skill("docx_editor_skill", "doc-docx-editor", "DOCX Editor Skill",
        "Edits existing .docx files via XML manipulation: unpack → edit → pack.",
        "Apply precise edits to existing Word documents while preserving formatting.",
        ["docx", "editing"],
        "You orchestrate DOCX editing: (1) Unpack the document, (2) Edit the XML, (3) Repack. Each step builds on the previous.",
        ["Unpack must complete before editing begins", "Editing must complete before packing"]),

    _skill("docx_reader_skill", "doc-docx-reader", "DOCX Reader Skill",
        "Reads and extracts content from .docx files for analysis.",
        "Extract text, structure, and metadata from Word documents.",
        ["docx", "reading"],
        "You extract content from DOCX files using pandoc or raw XML unpacking.",
        ["Report document structure: headings, tables, images"]),

    _skill("docx_validator_skill", "doc-docx-validator", "DOCX Validator Skill",
        "Validates .docx files for schema compliance and correctness.",
        "Ensure Word documents are valid and render correctly.",
        ["docx", "validation"],
        "You validate DOCX files and report any schema or structural issues.",
        ["Report specific errors with severity classification"]),

    # ── PPTX Skills ──
    _skill("pptx_creator_skill", "doc-pptx-creator", "PPTX Creator Skill",
        "Creates presentations from scratch using PptxGenJS with stunning design.",
        "Produce a board-ready presentation with world-class design quality.",
        ["pptx", "creation"],
        "You orchestrate PPTX creation from scratch using PptxGenJS. Invoke the generator action.",
        ["Every slide must have a visual element", "Pick topic-specific color palette"]),

    _skill("pptx_template_editor_skill", "doc-pptx-template-editor", "PPTX Template Editor Skill",
        "Edits presentations using an existing template: analyze → unpack → manipulate → pack.",
        "Produce a polished presentation by adapting an existing template with new content.",
        ["pptx", "template", "editing"],
        "You orchestrate template-based PPTX editing: (1) Analyze template layouts, (2) Unpack, (3) Manipulate slides & content, (4) Clean & pack. Complete all structural changes before content editing.",
        ["Analyze template before unpacking", "Complete structural changes before content editing", "Always clean before packing"]),

    _skill("pptx_reader_skill", "doc-pptx-reader", "PPTX Reader Skill",
        "Reads and extracts content from .pptx files.",
        "Extract text, speaker notes, and structure from presentations.",
        ["pptx", "reading"],
        "You extract content from PPTX files using markitdown or raw XML.",
        ["Report slide count and content summary"]),

    _skill("pptx_visual_qa_skill", "doc-pptx-visual-qa", "PPTX Visual QA Skill",
        "Performs rigorous visual quality assurance on generated presentations.",
        "Find and fix ALL visual issues. First render is almost never correct.",
        ["pptx", "qa"],
        "You orchestrate PPTX visual QA: (1) Convert slides to images, (2) Visually inspect each slide. Assume there are problems.",
        ["Convert to images before inspection", "Do not declare success until fix-and-verify cycle completes"]),

    # ── XLSX Skills ──
    _skill("xlsx_creator_skill", "doc-xlsx-creator", "XLSX Creator Skill",
        "Creates new Excel workbooks with data, formulas, and formatting.",
        "Produce a professional Excel workbook with proper formulas and zero errors.",
        ["xlsx", "creation"],
        "You orchestrate XLSX creation using openpyxl. Always use Excel formulas, never hardcode values.",
        ["Use formulas not hardcoded values", "Run recalc.py after creation"]),

    _skill("xlsx_editor_skill", "doc-xlsx-editor", "XLSX Editor Skill",
        "Edits existing Excel files while preserving formatting and formulas.",
        "Apply modifications to existing workbooks without breaking formulas or formatting.",
        ["xlsx", "editing"],
        "You edit existing Excel files using openpyxl. Preserve existing conventions.",
        ["Match existing format/style exactly", "Never open with data_only=True if saving"]),

    _skill("xlsx_data_analyzer_skill", "doc-xlsx-data-analyzer", "XLSX Data Analyzer Skill",
        "Analyzes Excel data using pandas for insights and statistics.",
        "Extract insights from spreadsheet data.",
        ["xlsx", "analysis"],
        "You analyze Excel data using pandas: read, transform, aggregate, visualize.",
        ["Handle NaN values properly", "Specify data types to avoid inference issues"]),

    _skill("xlsx_formula_engine_skill", "doc-xlsx-formula-engine", "XLSX Formula Engine Skill",
        "Recalculates formulas and fixes errors until zero errors remain.",
        "Ensure all Excel formulas calculate correctly with zero errors.",
        ["xlsx", "formulas"],
        "You orchestrate formula verification: (1) Recalculate with recalc.py, (2) If errors found, fix them. Repeat until zero errors.",
        ["Repeat fix-and-verify until zero errors", "Test fixes on 2-3 cells before applying broadly"]),

    _skill("xlsx_financial_formatter_skill", "doc-xlsx-financial-formatter", "XLSX Financial Formatter Skill",
        "Applies industry-standard financial model formatting.",
        "Transform workbooks into professionally formatted financial models.",
        ["xlsx", "financial"],
        "You apply IB/consulting financial formatting: color coding, number formats, assumption placement.",
        ["Blue for inputs, black for formulas", "Document sources for hardcoded values"]),

    # ── PDF Skills ──
    _skill("pdf_creator_skill", "doc-pdf-creator", "PDF Creator Skill",
        "Creates new PDF documents using reportlab.",
        "Produce professionally formatted PDF documents.",
        ["pdf", "creation"],
        "You orchestrate PDF creation using reportlab canvas or platypus.",
        ["Never use Unicode subscript/superscript characters"]),

    _skill("pdf_manipulator_skill", "doc-pdf-manipulator", "PDF Manipulator Skill",
        "Merges, splits, rotates, crops, and watermarks PDF files.",
        "Apply structural transformations to PDF files.",
        ["pdf", "manipulation"],
        "You orchestrate PDF manipulation: merge, split, rotate, crop, or watermark as requested.",
        ["Verify page count after operations"]),

    _skill("pdf_reader_skill", "doc-pdf-reader", "PDF Reader Skill",
        "Extracts text and tables from PDF files with OCR fallback.",
        "Extract all content from PDFs in structured format.",
        ["pdf", "reading"],
        "You extract text and tables from PDFs using pdfplumber, with OCR fallback for scanned docs.",
        ["Try pdfplumber first, OCR as fallback"]),

    _skill("pdf_form_filler_skill", "doc-pdf-form-filler", "PDF Form Filler Skill",
        "Detects form fields and fills PDF forms using fillable or annotation approach.",
        "Fill PDF forms with specified values using the correct approach.",
        ["pdf", "forms"],
        "You orchestrate PDF form filling: (1) Detect form type (fillable vs non-fillable), (2) Fill using appropriate method. Always validate bounding boxes and verify output.",
        ["Detect form type before filling", "Always validate bounding boxes", "Always verify output visually"]),

    _skill("pdf_security_skill", "doc-pdf-security", "PDF Security Skill",
        "Encrypts or decrypts PDF files with password protection.",
        "Apply or remove security on PDF documents.",
        ["pdf", "security"],
        "You manage PDF encryption and decryption.",
        ["Never expose passwords in output"]),

    # ── QA Skill ──
    _skill("doc_qa_pipeline_skill", "doc-qa-pipeline", "Document QA Pipeline Skill",
        "Validates all generated documents and archives outputs for delivery.",
        "Ensure document quality and organize deliverables.",
        ["qa", "delivery"],
        "You orchestrate QA: (1) Validate all generated documents for completeness and correctness, (2) Archive outputs with manifest.",
        ["Validation must pass before archiving", "Archive includes all generated artifacts"]),
]

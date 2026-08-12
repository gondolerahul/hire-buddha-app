"""Layer 3: AGENT entity definitions for Document Factory Engine."""

AGENTS = [
    {
        "key": "docx_document_agent",
        "payload": {
            "name": "doc-docx-agent",
            "display_name": "📝 DOCX Document Agent",
            "description": "Autonomous agent specializing in Word document creation, editing, reading, and validation. Decides between docx-js creation and XML editing workflows.",
            "goal": "Produce publication-quality .docx files — create from scratch or edit existing documents with precision.",
            "type": "AGENT", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "docx-agent", "word"],
            "identity": {
                "system_prompt": (
                    "You are the DOCX Document Agent — a senior document engineer.\n\n"
                    "## Your Skills:\n"
                    "1. **DOCX Creator** — Create new .docx from scratch using docx-js (JavaScript)\n"
                    "2. **DOCX Editor** — Edit existing .docx via XML (unpack → edit → pack)\n"
                    "3. **DOCX Reader** — Extract content from .docx files\n"
                    "4. **DOCX Validator** — Validate .docx for schema compliance\n\n"
                    "## Routing Logic:\n"
                    "- 'Create/generate/write a Word doc' → Creator skill\n"
                    "- 'Edit/modify/update an existing .docx' → Editor skill\n"
                    "- 'Read/extract/analyze a .docx' → Reader skill\n"
                    "- 'Validate/check a .docx' → Validator skill\n"
                    "- For creation tasks, always validate after generating"
                ),
                "behavioral_constraints": [
                    "Route to the correct skill based on task type",
                    "Always validate documents after creation or editing",
                    "For creation: use docx-js. For editing existing: use XML workflow",
                    "Pass full context between skills"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 2, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "thinking", "temperature": 0.3, "reasoning_mode": "REFLECTION"},
                "retry_policy": {"max_retries": 2, "backoff_strategy": "EXPONENTIAL"},
                "context_policy": {"type": "FULL", "summarize_threshold": 25000, "preserve_keys": ["document_path", "content_spec"]},
                "review_mechanism": {"enabled": True, "review_prompt": "Was the document generated/edited successfully? Did validation pass?", "on_failure": "RETRY"}
            },
            "planning": {
                "static_plan": {"enabled": False},
                "dynamic_planning": {"enabled": True, "planning_prompt": "Analyze the request and determine which DOCX skill(s) to invoke."}
            },
            "capabilities": {
                "tools": [{"tool_id": "sandbox_code"}, {"tool_id": "terminal"}],
                "memory": {"enabled": True, "mode": "CORTEX", "memory_scope": "INTELLIGENCE_ONLY", "cortex_config": {"max_children": 12, "auto_checkpoint": True, "context_budget_pct": 40, "resume_enabled": True}},
                "context_engineering": {"inject_cortex_viewport": True, "inject_episodic_memory": False, "inject_semantic_context": True, "no_truncation": True}
            },
            "governance": {"timeout_ms": 600000, "max_cost_usd": 3.00, "max_recursion_depth": 4, "execution_limits": {"max_tool_calls": 25}},
            "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Document task description — what to create, edit, or extract"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Task result with file paths"}}}
            }
        }
    },
    {
        "key": "pptx_presentation_agent",
        "payload": {
            "name": "doc-pptx-agent",
            "display_name": "📊 PPTX Presentation Agent",
            "description": "Autonomous presentation design specialist. Creates stunning slide decks rivaling McKinsey/BCG quality. Chooses between from-scratch and template workflows. Runs mandatory visual QA.",
            "goal": "Produce board-ready presentations with world-class design — every slide must have a visual element, topic-specific colors, and varied layouts.",
            "type": "AGENT", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pptx-agent", "presentation"],
            "identity": {
                "system_prompt": (
                    "You are the PPTX Presentation Agent — a top-tier presentation designer.\n\n"
                    "## Your Skills:\n"
                    "1. **PPTX Creator** — Create from scratch with PptxGenJS\n"
                    "2. **PPTX Template Editor** — Edit from existing template (analyze → unpack → edit → pack)\n"
                    "3. **PPTX Reader** — Extract content from .pptx files\n"
                    "4. **PPTX Visual QA** — Convert to images and inspect (MANDATORY after creation/editing)\n\n"
                    "## Routing Logic:\n"
                    "- No template provided → Creator skill\n"
                    "- Template/reference deck provided → Template Editor skill\n"
                    "- Read/extract from existing → Reader skill\n"
                    "- ALWAYS run Visual QA after creating or editing\n\n"
                    "## Design Standards:\n"
                    "- Every slide MUST have a visual element\n"
                    "- Topic-specific color palette (never default blue)\n"
                    "- Varied layouts across slides\n"
                    "- 0.5\" minimum margins, 0.3-0.5\" between blocks"
                ),
                "behavioral_constraints": [
                    "ALWAYS run Visual QA after creation or editing — no exceptions",
                    "If no template: use Creator. If template provided: use Template Editor",
                    "Every slide must have a visual element — reject text-only slides",
                    "Iterate on fixes until Visual QA passes with no issues"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 2, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "thinking", "temperature": 0.4, "reasoning_mode": "REFLECTION"},
                "retry_policy": {"max_retries": 2, "backoff_strategy": "EXPONENTIAL"},
                "context_policy": {"type": "FULL", "summarize_threshold": 25000},
                "review_mechanism": {"enabled": True, "review_prompt": "Did Visual QA pass? Are there remaining visual issues?", "on_failure": "RETRY"}
            },
            "planning": {
                "static_plan": {"enabled": False},
                "dynamic_planning": {"enabled": True, "planning_prompt": "Determine if this is a from-scratch or template-based task, invoke the right skill, then ALWAYS run Visual QA."}
            },
            "capabilities": {
                "tools": [{"tool_id": "sandbox_code"}, {"tool_id": "terminal"}],
                "memory": {"enabled": True, "mode": "CORTEX", "memory_scope": "INTELLIGENCE_ONLY", "cortex_config": {"max_children": 12, "auto_checkpoint": True, "context_budget_pct": 40, "resume_enabled": True}},
                "context_engineering": {"inject_cortex_viewport": True, "no_truncation": True}
            },
            "governance": {"timeout_ms": 900000, "max_cost_usd": 5.00, "max_recursion_depth": 5, "execution_limits": {"max_tool_calls": 40}},
            "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Presentation task description — what to create, edit, or extract"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Task result with file paths"}}}
            }
        }
    },
    {
        "key": "xlsx_spreadsheet_agent",
        "payload": {
            "name": "doc-xlsx-agent",
            "display_name": "📈 XLSX Spreadsheet Agent",
            "description": "Financial modeling expert. Creates Excel workbooks with proper formulas, industry-standard color coding, and zero formula errors.",
            "goal": "Produce professional Excel workbooks — always formulas over hardcoded values, zero errors, financial-grade formatting.",
            "type": "AGENT", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "xlsx-agent", "excel"],
            "identity": {
                "system_prompt": (
                    "You are the XLSX Spreadsheet Agent — a financial modeling expert.\n\n"
                    "## Your Skills:\n"
                    "1. **XLSX Creator** — Create new workbooks (openpyxl)\n"
                    "2. **XLSX Editor** — Edit existing workbooks\n"
                    "3. **XLSX Data Analyzer** — Analyze data (pandas)\n"
                    "4. **XLSX Formula Engine** — Recalculate & fix formula errors\n"
                    "5. **XLSX Financial Formatter** — Apply IB/consulting formatting standards\n\n"
                    "## Routing Logic:\n"
                    "- Create new workbook → Creator + Formula Engine (mandatory recalc)\n"
                    "- Edit existing → Editor + Formula Engine\n"
                    "- Analyze data → Data Analyzer\n"
                    "- Financial model → Creator/Editor + Financial Formatter + Formula Engine\n\n"
                    "## IRON RULE: Formulas over hardcoded values. ALWAYS."
                ),
                "behavioral_constraints": [
                    "ALWAYS use Excel formulas — never hardcode calculated values",
                    "ALWAYS run Formula Engine (recalc) after creation or editing",
                    "Zero formula errors is mandatory — iterate until achieved",
                    "Apply financial formatting for financial/business models"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 2, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "thinking", "temperature": 0.3, "reasoning_mode": "REFLECTION"},
                "context_policy": {"type": "FULL", "summarize_threshold": 25000},
                "review_mechanism": {"enabled": True, "review_prompt": "Are there zero formula errors? Was financial formatting applied if needed?", "on_failure": "RETRY"}
            },
            "planning": {
                "static_plan": {"enabled": False},
                "dynamic_planning": {"enabled": True, "planning_prompt": "Determine the task type and invoke appropriate skills. Always recalculate formulas."}
            },
            "capabilities": {
                "tools": [{"tool_id": "sandbox_code"}, {"tool_id": "terminal"}],
                "memory": {"enabled": True, "mode": "CORTEX", "memory_scope": "INTELLIGENCE_ONLY", "cortex_config": {"auto_checkpoint": True, "context_budget_pct": 40}},
                "context_engineering": {"inject_cortex_viewport": True, "no_truncation": True}
            },
            "governance": {"timeout_ms": 600000, "max_cost_usd": 3.00, "max_recursion_depth": 4, "execution_limits": {"max_tool_calls": 25}},
            "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Spreadsheet task description — what to create, edit, or analyze"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Task result with file paths"}}}
            }
        }
    },
    {
        "key": "pdf_document_agent",
        "payload": {
            "name": "doc-pdf-agent",
            "display_name": "📕 PDF Document Agent",
            "description": "PDF processing specialist. Creates, manipulates, extracts from, and fills forms in PDF documents.",
            "goal": "Handle all PDF operations — creation, manipulation, extraction, form filling, and security.",
            "type": "AGENT", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "pdf-agent"],
            "identity": {
                "system_prompt": (
                    "You are the PDF Document Agent — a PDF processing specialist.\n\n"
                    "## Your Skills:\n"
                    "1. **PDF Creator** — Create new PDFs (reportlab)\n"
                    "2. **PDF Manipulator** — Merge, split, rotate, crop, watermark\n"
                    "3. **PDF Reader** — Extract text and tables (pdfplumber + OCR)\n"
                    "4. **PDF Form Filler** — Detect and fill PDF forms\n"
                    "5. **PDF Security** — Encrypt/decrypt\n\n"
                    "## Routing Logic:\n"
                    "- Create/generate PDF → Creator skill\n"
                    "- Merge/split/rotate/crop/watermark → Manipulator skill\n"
                    "- Read/extract text/tables → Reader skill\n"
                    "- Fill form → Form Filler skill (detects fillable vs annotation)\n"
                    "- Encrypt/decrypt → Security skill"
                ),
                "behavioral_constraints": [
                    "Route to correct skill based on operation type",
                    "For form filling: always detect form type first",
                    "For extraction: try pdfplumber first, OCR as fallback"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 2, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "thinking", "temperature": 0.3, "reasoning_mode": "REFLECTION"},
                "context_policy": {"type": "FULL", "summarize_threshold": 25000}
            },
            "planning": {
                "static_plan": {"enabled": False},
                "dynamic_planning": {"enabled": True, "planning_prompt": "Analyze the PDF operation type and invoke the appropriate skill."}
            },
            "capabilities": {
                "tools": [{"tool_id": "sandbox_code"}, {"tool_id": "terminal"}],
                "memory": {"enabled": True, "mode": "CORTEX", "memory_scope": "INTELLIGENCE_ONLY", "cortex_config": {"auto_checkpoint": True, "context_budget_pct": 40}},
                "context_engineering": {"inject_cortex_viewport": True, "no_truncation": True}
            },
            "governance": {"timeout_ms": 600000, "max_cost_usd": 3.00, "max_recursion_depth": 4, "execution_limits": {"max_tool_calls": 25}},
            "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "PDF task description — what to create, manipulate, extract, or fill"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Task result with file paths"}}}
            }
        }
    },
    {
        "key": "doc_qa_delivery_agent",
        "payload": {
            "name": "doc-qa-delivery-agent",
            "display_name": "✅ Document QA & Delivery Agent",
            "description": "Quality assurance agent that validates all generated documents and archives outputs for delivery.",
            "goal": "Ensure all documents pass quality checks and organize them for clean delivery.",
            "type": "AGENT", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "qa-agent", "delivery"],
            "identity": {
                "system_prompt": (
                    "You are the Document QA & Delivery Agent.\n\n"
                    "## Your Process:\n"
                    "1. **Validate** — Check all generated documents for completeness and correctness\n"
                    "2. **Archive** — Organize outputs into dated folder with manifest\n\n"
                    "## Quality Standards:\n"
                    "- Every file must exist, be non-empty, and open without errors\n"
                    "- No placeholder text (TODO, lorem ipsum, [INSERT])\n"
                    "- XLSX: zero formula errors\n"
                    "- DOCX: schema validation passes\n"
                    "- PPTX: no visual issues"
                ),
                "behavioral_constraints": [
                    "Validate before archiving",
                    "FAIL verdict if any CRITICAL issues",
                    "Archive must include manifest.json"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 2, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 20000}
            },
            "planning": {
                "static_plan": {"enabled": True, "fallback_behavior": "STRICT", "steps": [
                    {"step_id": "step_1", "order": 1, "name": "Validate Documents", "description": "Run content validation on all generated documents.", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER__", "prompt_template": "Validate these documents:\n\n{{input}}"}, "required": True},
                    {"step_id": "step_2", "order": 2, "name": "Archive & Deliver", "description": "Archive all validated outputs.", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER__", "prompt_template": "Archive these outputs. QA result:\n\n{{step_1}}\n\nDocuments:\n\n{{input}}", "input_dependencies": ["step_1"]}, "required": True}
                ]},
                "dynamic_planning": {"enabled": False}
            },
            "capabilities": {
                "tools": [{"tool_id": "sandbox_code"}, {"tool_id": "terminal"}],
                "memory": {"enabled": True, "mode": "CORTEX", "memory_scope": "INTELLIGENCE_ONLY", "cortex_config": {"auto_checkpoint": True}},
                "context_engineering": {"inject_cortex_viewport": True, "no_truncation": True}
            },
            "governance": {"timeout_ms": 300000, "max_cost_usd": 1.00, "max_recursion_depth": 3},
            "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Documents to validate and archive"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"qa_verdict": {"type": "string", "description": "PASS or FAIL"}, "archive_path": {"type": "string", "description": "Archive location"}}}
            }
        }
    },
]

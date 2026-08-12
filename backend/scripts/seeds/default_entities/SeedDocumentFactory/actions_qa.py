"""Layer 1: QA & Delivery ACTION entity definitions for Document Factory Engine."""

ACTIONS_QA = [
    {
        "key": "doc_content_validation_action",
        "payload": {
            "name": "doc-content-validation",
            "display_name": "Document Content Validator",
            "description": "Validates generated documents for completeness, formatting errors, empty placeholders, and structural integrity.",
            "goal": "Ensure all generated documents are complete, correctly formatted, and free of placeholder content.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "qa", "validation", "content"],
            "identity": {
                "system_prompt": (
                    "You are a document quality analyst. Validate generated documents:\n\n"
                    "## CHECKS\n"
                    "1. File exists and is non-empty\n"
                    "2. File opens without corruption errors\n"
                    "3. No placeholder text remains (TODO, FIXME, [INSERT], lorem ipsum, xxx)\n"
                    "4. Content matches specifications (sections present, data correct)\n"
                    "5. Formatting is consistent (fonts, sizes, colors)\n"
                    "6. For XLSX: zero formula errors after recalculation\n"
                    "7. For DOCX: schema validation passes\n"
                    "8. For PPTX: visual QA passes, no overlapping elements\n"
                    "9. For PDF: all pages render, text is extractable\n\n"
                    "Output structured JSON: { 'verdict': 'PASS|FAIL', 'issues': [...] }"
                ),
                "behavioral_constraints": [
                    "Check every generated file — never skip validation",
                    "Report specific issues with file, page/sheet, and location",
                    "Classify issues: CRITICAL (broken) vs WARNING (cosmetic)",
                    "Verdict is FAIL if any CRITICAL issues exist"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 20000}
            },
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Validate Documents", "type": "ACTION", "target": {"tool_id": "sandbox_code", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "sandbox_code"}, {"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
    {
        "key": "doc_archive_delivery_action",
        "payload": {
            "name": "doc-archive-delivery",
            "display_name": "Document Archiver & Deliverer",
            "description": "Organizes all generated document artifacts into a dated folder with a manifest file.",
            "goal": "Create a clean, organized archive of all document artifacts with a manifest listing every file.",
            "type": "ACTION", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["doc-factory", "archive", "delivery"],
            "identity": {
                "system_prompt": (
                    "You organize and archive generated documents.\n\n"
                    "1. Create dated directory: /tmp/doc-factory/YYYY-MM-DD/\n"
                    "2. Copy all generated files to the directory\n"
                    "3. Create manifest.json: { files: [{ filename, type, size_bytes, created_at }] }\n"
                    "4. List final directory: ls -la\n"
                    "5. Print archive path"
                ),
                "behavioral_constraints": [
                    "Always create date-stamped directory",
                    "Include ALL generated artifacts in manifest",
                    "Never delete original files — only copy to archive",
                    "Print final ls -la for verification"
                ]
            },
            "hierarchy": {"is_atomic": True, "composition_depth": 0, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Archive Documents", "type": "ACTION", "target": {"tool_id": "terminal", "prompt_template": "{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "terminal"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50},
            "io_contract": {
                "input_schema": {"type": "object", "properties": {"input": {"type": "string", "description": "Task input for this action"}}, "required": ["input"]},
                "output_schema": {"type": "object", "properties": {"result": {"type": "string", "description": "Action execution result"}}}
            }
        }
    },
]

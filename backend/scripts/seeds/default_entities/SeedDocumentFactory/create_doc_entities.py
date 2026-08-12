#!/usr/bin/env python3
"""
Document Factory Engine — Entity Setup Script
================================================
Creates the complete entity hierarchy for the Document Factory Engine.
Follows the same bottom-up pattern as SeedAutonomousBI.

Usage:
    python create_doc_entities.py
    python create_doc_entities.py --cleanup
"""

import json, os, sys, time

sys.path.insert(0, os.path.dirname(__file__))
from config import APIClient
from actions_docx import ACTIONS_DOCX
from actions_pptx import ACTIONS_PPTX
from actions_xlsx import ACTIONS_XLSX
from actions_pdf import ACTIONS_PDF
from actions_qa import ACTIONS_QA
from skills import SKILLS
from agents import AGENTS
from phase11 import enrich_payload

ALL_ACTIONS = ACTIONS_DOCX + ACTIONS_PPTX + ACTIONS_XLSX + ACTIONS_PDF + ACTIONS_QA


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Create Document Factory entities")
    parser.add_argument("--cleanup", action="store_true", help="Delete old entities first")
    args = parser.parse_args()

    client = APIClient()
    entity_ids = {}

    # ========================================
    # PHASE 0: Verify auth
    # ========================================
    print("=" * 60)
    print("Phase 0: Verifying authentication")
    print("=" * 60)
    client.verify_auth()

    # ========================================
    # PHASE 0.5: Optional cleanup
    # ========================================
    if args.cleanup:
        ids_path = os.path.join(os.path.dirname(__file__), "entity_ids.json")
        if os.path.exists(ids_path):
            print("\n" + "=" * 60)
            print("Phase 0.5: Cleaning up old entities")
            print("=" * 60)
            with open(ids_path) as f:
                old_ids = json.load(f)
            for key in reversed(list(old_ids.keys())):
                client.delete_entity(old_ids[key])
                time.sleep(0.1)
            print(f"  Deleted {len(old_ids)} old entities")

    # ========================================
    # PHASE 1: Create ACTIONs (Layer 1)
    # ========================================
    print("\n" + "=" * 60)
    print(f"Phase 1: Creating ACTIONs (Layer 1 — {len(ALL_ACTIONS)} Atomic Operations)")
    print("=" * 60)
    for action_def in ALL_ACTIONS:
        key = action_def["key"]
        payload = enrich_payload(key, action_def["payload"])
        try:
            result = client.create_entity(payload)
            entity_ids[key] = result["id"]
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ Failed: {payload['name']}: {e}")
            sys.exit(1)

    # ========================================
    # PHASE 2: Create SKILLs (Layer 2)
    # ========================================
    print("\n" + "=" * 60)
    print(f"Phase 2: Creating SKILLs (Layer 2 — {len(SKILLS)} Composed Capabilities)")
    print("=" * 60)
    for skill_def in SKILLS:
        key = skill_def["key"]
        payload = enrich_payload(key, skill_def["payload"])
        try:
            result = client.create_entity(payload)
            entity_ids[key] = result["id"]
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ Failed: {payload['name']}: {e}")
            sys.exit(1)

    # ========================================
    # PHASE 3: Create AGENTs (Layer 3)
    # ========================================
    print("\n" + "=" * 60)
    print(f"Phase 3: Creating AGENTs (Layer 3 — {len(AGENTS)} Document Specialists)")
    print("=" * 60)
    for agent_def in AGENTS:
        key = agent_def["key"]
        payload = enrich_payload(key, agent_def["payload"])
        try:
            result = client.create_entity(payload)
            entity_ids[key] = result["id"]
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ Failed: {payload['name']}: {e}")
            sys.exit(1)

    # ========================================
    # PHASE 4: Create PROCESS (Layer 4)
    # ========================================
    print("\n" + "=" * 60)
    print("Phase 4: Creating PROCESS (Layer 4 — Top-Level Orchestrator)")
    print("=" * 60)

    docx_id = entity_ids["docx_document_agent"]
    pptx_id = entity_ids["pptx_presentation_agent"]
    xlsx_id = entity_ids["xlsx_spreadsheet_agent"]
    pdf_id = entity_ids["pdf_document_agent"]
    qa_id = entity_ids["doc_qa_delivery_agent"]

    process_payload = {
        "name": "doc-factory-process",
        "display_name": "📄 Document Factory Engine",
        "description": (
            "Autonomous Document Factory that analyzes user requests and dynamically routes "
            "to specialized document agents (DOCX, PPTX, XLSX, PDF). Each agent contains the "
            "full domain expertise from Claude Skills, distilled into model-agnostic system "
            "prompts. Produces pixel-perfect documents rivaling top consulting firms."
        ),
        "goal": "Analyze user document requests, route to the correct specialist agent(s), and deliver publication-quality documents.",
        "type": "PROCESS", "version": "1.0.0", "status": "ACTIVE",
        "tags": ["doc-factory", "process", "orchestrator"],
        "identity": {
            "system_prompt": (
                "You are the Document Factory Orchestrator. You analyze user requests and route "
                "them to specialized document agents.\n\n"
                "## Available Agents:\n"
                "1. **📝 DOCX Agent** — Word documents (.docx): reports, memos, letters, templates\n"
                "2. **📊 PPTX Agent** — Presentations (.pptx): slide decks, pitch decks\n"
                "3. **📈 XLSX Agent** — Spreadsheets (.xlsx): financial models, data analysis, dashboards\n"
                "4. **📕 PDF Agent** — PDF files (.pdf): reports, forms, merging, extraction\n"
                "5. **✅ QA Agent** — Validates and archives all outputs\n\n"
                "## Routing Rules:\n"
                "- Analyze the user's request to determine which document type(s) are needed\n"
                "- Route to ONLY the relevant agent(s) — don't invoke agents unnecessarily\n"
                "- If multiple documents needed, invoke agents sequentially\n"
                "- ALWAYS invoke QA Agent as the final step\n"
                "- If request is ambiguous, ask for clarification"
            ),
            "behavioral_constraints": [
                "Invoke ONLY the relevant document agent(s) — dynamic routing",
                "Always invoke QA Agent as the final step",
                "If request mentions multiple formats, invoke each agent sequentially",
                "If ambiguous, default to the most likely document type"
            ]
        },
        "hierarchy": {
            "is_atomic": False, "composition_depth": 3,
            "children": [
                {"child_id": docx_id, "child_type": "AGENT", "relationship": "PARALLEL"},
                {"child_id": pptx_id, "child_type": "AGENT", "relationship": "PARALLEL"},
                {"child_id": xlsx_id, "child_type": "AGENT", "relationship": "PARALLEL"},
                {"child_id": pdf_id, "child_type": "AGENT", "relationship": "PARALLEL"},
                {"child_id": qa_id, "child_type": "AGENT", "relationship": "SEQUENTIAL"},
            ]
        },
        "logic_gate": {
            "reasoning_config": {"task_type": "thinking", "temperature": 0.3, "reasoning_mode": "REFLECTION"},
            "retry_policy": {"max_retries": 2, "backoff_strategy": "EXPONENTIAL"},
            "context_policy": {"type": "FULL", "summarize_threshold": 30000, "preserve_keys": ["request_type", "document_outputs", "qa_verdict"]}
        },
        "planning": {
            "static_plan": {"enabled": False},
            "dynamic_planning": {
                "enabled": True,
                "planning_prompt": "Analyze the user request. Determine which document type(s) are needed. Invoke only the relevant agent(s), then QA."
            }
        },
        "capabilities": {
            "tools": [],
            "memory": {"enabled": True, "mode": "CORTEX", "cortex_config": {"max_children": 12, "page_size_tokens": 8000, "context_budget_pct": 40, "auto_checkpoint": True, "resume_enabled": True}},
            "context_engineering": {"inject_cortex_viewport": True, "inject_episodic_memory": True, "no_truncation": True}
        },
        "governance": {"timeout_ms": 3600000, "max_cost_usd": 25.00, "max_recursion_depth": 5, "execution_limits": {"max_tool_calls": 100}},
        "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True},
        "io_contract": {
            "input_schema": {
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "Describe the document(s) you want to create. Include: document type (DOCX, PPTX, XLSX, PDF), content details, style preferences, and any special requirements.",
                        "x-ui-widget": "textarea"
                    }
                },
                "required": ["input"]
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "documents": {"type": "array", "description": "Generated document file paths"},
                    "qa_report": {"type": "string", "description": "Quality assurance report"}
                }
            }
        }
    }

    enrich_payload("doc_factory_process", process_payload)
    try:
        result = client.create_entity(process_payload)
        entity_ids["doc_factory_process"] = result["id"]
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        sys.exit(1)

    # ========================================
    # PHASE 5: Link Entity Hierarchy
    # ========================================
    print("\n" + "=" * 60)
    print("Phase 5: Linking Entity Hierarchy (SKILLs → ACTIONs, AGENTs → SKILLs)")
    print("=" * 60)

    # SKILLs → ACTIONs mapping
    skill_action_map = {
        "docx_creator_skill": ["docx_create_action"],
        "docx_editor_skill": ["docx_unpack_action", "docx_edit_xml_action", "docx_pack_action"],
        "docx_reader_skill": ["docx_extract_action"],
        "docx_validator_skill": ["docx_validate_action"],
        "pptx_creator_skill": ["pptx_create_action"],
        "pptx_template_editor_skill": ["pptx_analyze_template_action", "pptx_unpack_action", "pptx_manipulate_slides_action", "pptx_pack_action"],
        "pptx_reader_skill": ["pptx_extract_action"],
        "pptx_visual_qa_skill": ["pptx_convert_images_action", "pptx_visual_qa_action"],
        "xlsx_creator_skill": ["xlsx_create_action"],
        "xlsx_editor_skill": ["xlsx_edit_action"],
        "xlsx_data_analyzer_skill": ["xlsx_analyze_data_action"],
        "xlsx_formula_engine_skill": ["xlsx_recalc_action", "xlsx_verify_errors_action"],
        "xlsx_financial_formatter_skill": ["xlsx_financial_format_action"],
        "pdf_creator_skill": ["pdf_create_action"],
        "pdf_manipulator_skill": ["pdf_merge_split_action", "pdf_rotate_crop_action"],
        "pdf_reader_skill": ["pdf_extract_text_action"],
        "pdf_form_filler_skill": ["pdf_detect_form_action", "pdf_fill_form_action"],
        "pdf_security_skill": ["pdf_encrypt_action"],
        "doc_qa_pipeline_skill": ["doc_content_validation_action", "doc_archive_delivery_action"],
    }

    for skill_key, action_keys in skill_action_map.items():
        skill_id = entity_ids[skill_key]
        children = [
            {"child_id": entity_ids[ak], "child_type": "ACTION", "relationship": "SEQUENTIAL"}
            for ak in action_keys
        ]
        client.update_entity(skill_id, {
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": children}
        })
        time.sleep(0.2)

    # AGENTs → SKILLs mapping
    agent_skill_map = {
        "docx_document_agent": ["docx_creator_skill", "docx_editor_skill", "docx_reader_skill", "docx_validator_skill"],
        "pptx_presentation_agent": ["pptx_creator_skill", "pptx_template_editor_skill", "pptx_reader_skill", "pptx_visual_qa_skill"],
        "xlsx_spreadsheet_agent": ["xlsx_creator_skill", "xlsx_editor_skill", "xlsx_data_analyzer_skill", "xlsx_formula_engine_skill", "xlsx_financial_formatter_skill"],
        "pdf_document_agent": ["pdf_creator_skill", "pdf_manipulator_skill", "pdf_reader_skill", "pdf_form_filler_skill", "pdf_security_skill"],
        "doc_qa_delivery_agent": ["doc_qa_pipeline_skill"],
    }

    for agent_key, skill_keys in agent_skill_map.items():
        agent_id = entity_ids[agent_key]
        children = [
            {"child_id": entity_ids[sk], "child_type": "SKILL", "relationship": "SEQUENTIAL"}
            for sk in skill_keys
        ]
        client.update_entity(agent_id, {
            "hierarchy": {"is_atomic": False, "composition_depth": 2, "children": children}
        })
        time.sleep(0.2)

    # ========================================
    # PHASE 6: Patch SKILLs with real ACTION UUIDs
    # ========================================
    print("\n" + "=" * 60)
    print("Phase 6: Patching SKILLs with real ACTION UUIDs")
    print("=" * 60)

    for skill_key, action_keys in skill_action_map.items():
        steps = []
        for i, ak in enumerate(action_keys, 1):
            step = {
                "step_id": f"step_{i}", "order": i,
                "name": action_keys[i-1].replace("_action", "").replace("_", " ").title(),
                "type": "CHILD_ENTITY_INVOCATION",
                "target": {"entity_id": entity_ids[ak], "prompt_template": "{{input}}" if i == 1 else "Continue with:\n\n{{step_" + str(i-1) + "}}"},
                "required": True
            }
            if i > 1:
                step["target"]["input_dependencies"] = [f"step_{i-1}"]
            steps.append(step)

        client.update_entity(entity_ids[skill_key], {
            "planning": {"static_plan": {"enabled": True, "steps": steps}, "dynamic_planning": {"enabled": False}}
        })
        time.sleep(0.1)
    print("  ✅ All SKILLs patched with real ACTION UUIDs")

    # Patch QA Agent with real skill UUID
    qa_skill_id = entity_ids["doc_qa_pipeline_skill"]
    qa_validate_id = entity_ids["doc_content_validation_action"]
    qa_archive_id = entity_ids["doc_archive_delivery_action"]

    client.update_entity(entity_ids["doc_qa_delivery_agent"], {
        "planning": {"static_plan": {"enabled": True, "fallback_behavior": "STRICT", "steps": [
            {"step_id": "step_1", "order": 1, "name": "Validate Documents", "type": "CHILD_ENTITY_INVOCATION",
             "target": {"entity_id": qa_skill_id, "prompt_template": "Validate these documents:\n\n{{input}}"}, "required": True},
            {"step_id": "step_2", "order": 2, "name": "Archive & Deliver", "type": "CHILD_ENTITY_INVOCATION",
             "target": {"entity_id": qa_skill_id, "prompt_template": "Archive outputs. QA:\n\n{{step_1}}\n\nDocs:\n\n{{input}}", "input_dependencies": ["step_1"]}, "required": True}
        ]}, "dynamic_planning": {"enabled": False}}
    })
    print("  ✅ QA Agent patched")

    # ========================================
    # Summary
    # ========================================
    print("\n" + "=" * 60)
    print("✅ Document Factory Engine Setup Complete!")
    print("=" * 60)
    print(f"\nTotal entities created: {len(entity_ids)}")

    print("\n📄 Entity Hierarchy:")
    print(f"  PROCESS: 📄 Document Factory → {entity_ids['doc_factory_process']}")
    for agent_key, skill_keys in agent_skill_map.items():
        agent_name = agent_key.replace("_", " ").title()
        print(f"  ├── AGENT: {agent_name} → {entity_ids[agent_key]}")
        for sk in skill_keys:
            skill_name = sk.replace("_skill", "").replace("_", " ").title()
            actions = skill_action_map.get(sk, [])
            print(f"  │   ├── SKILL: {skill_name} → {entity_ids[sk]}")
            for ak in actions:
                action_name = ak.replace("_action", "").replace("_", " ").title()
                print(f"  │   │   └── ACTION: {action_name} → {entity_ids[ak]}")

    # Save entity IDs
    output_path = os.path.join(os.path.dirname(__file__), "entity_ids.json")
    with open(output_path, "w") as f:
        json.dump(entity_ids, f, indent=2)
    print(f"\nEntity IDs saved to: {output_path}")
    print(f"\nNext: python trigger_doc_execution.py")


if __name__ == "__main__":
    main()

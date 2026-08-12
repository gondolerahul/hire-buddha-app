#!/usr/bin/env python3
"""
Autonomous BI Engine — Entity Setup Script
=============================================
Creates the complete 23-entity hierarchy for the Autonomous Business
Intelligence & Reporting Engine. Follows the same bottom-up pattern
as DeepResearchSetup/cleanup_and_recreate.py.

Usage:
    python create_bi_entities.py
    python create_bi_entities.py --cleanup   # Delete old BI entities first
"""

import json, os, sys, time

# Local imports
sys.path.insert(0, os.path.dirname(__file__))
from config import APIClient
from actions import ACTIONS
from skills import SKILLS
from agents import AGENTS


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Create BI Engine entities")
    parser.add_argument("--cleanup", action="store_true", help="Delete old BI entities first")
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
            print("Phase 0.5: Cleaning up old BI entities")
            print("=" * 60)
            with open(ids_path) as f:
                old_ids = json.load(f)
            # Delete in reverse order (process → agents → skills → actions)
            for key in reversed(list(old_ids.keys())):
                client.delete_entity(old_ids[key])
                time.sleep(0.1)
            print(f"  Deleted {len(old_ids)} old entities")

    # ========================================
    # PHASE 1: Create ACTIONs (Layer 1)
    # ========================================
    print("\n" + "=" * 60)
    print(f"Phase 1: Creating ACTIONs (Layer 1 — {len(ACTIONS)} Atomic Operations)")
    print("=" * 60)
    for action_def in ACTIONS:
        key = action_def["key"]
        payload = action_def["payload"]
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
        payload = skill_def["payload"]
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
    print(f"Phase 3: Creating AGENTs (Layer 3 — {len(AGENTS)} Autonomous Specialists)")
    print("=" * 60)
    for agent_def in AGENTS:
        key = agent_def["key"]
        payload = agent_def["payload"]
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

    dp_id = entity_ids["data_processor_agent"]
    rb_id = entity_ids["report_builder_agent"]
    qa_id = entity_ids["qa_archiver_agent"]

    process_payload = {
        "name": "bi-engine-process",
        "display_name": "📊 Autonomous BI Engine",
        "description": (
            "Autonomous Business Intelligence Engine that takes raw data parameters, "
            "processes and analyzes the data, generates comprehensive analytics "
            "(statistics, anomalies, forecasts, charts), and produces a full suite of "
            "business documents: Excel workbook, DOCX narrative report, PPTX executive "
            "deck, and PDF final package. Leverages CORTEX cognitive trees for unbounded "
            "context across long-running reporting cycles."
        ),
        "goal": (
            "Produce a complete, consistent, publication-quality business intelligence "
            "report suite from raw data. All documents must tell the same story with "
            "the same numbers."
        ),
        "type": "PROCESS", "version": "1.0.0", "status": "ACTIVE",
        "tags": ["bi-engine", "process", "analytics", "reporting", "cortex-stress-test"],
        "identity": {
            "system_prompt": (
                "You are the BI Engine Orchestrator. You coordinate three specialized agents:\n\n"
                "1. **Data Processor** — Fetches, cleans, analyzes data and generates charts\n"
                "2. **Report Builder** — Produces Excel, DOCX, PPTX, and PDF deliverables\n"
                "3. **QA & Delivery** — Validates consistency and archives outputs\n\n"
                "Your process:\n"
                "1. Receive data parameters (source, period, metrics)\n"
                "2. Invoke the Data Processor agent\n"
                "3. Quality-check the analytics output\n"
                "4. Invoke the Report Builder agent\n"
                "5. Invoke the QA & Delivery agent\n"
                "6. Return the completed report suite"
            ),
            "behavioral_constraints": [
                "Data Processor must complete fully before Report Builder begins",
                "Report Builder must complete fully before QA begins",
                "If analytics output is insufficient, request more processing",
                "Track total cost and halt if approaching limits",
                "Use CORTEX checkpointing between agents"
            ]
        },
        "hierarchy": {
            "is_atomic": False, "composition_depth": 3,
            "children": [
                {"child_id": dp_id, "child_type": "AGENT", "relationship": "SEQUENTIAL"},
                {"child_id": rb_id, "child_type": "AGENT", "relationship": "SEQUENTIAL"},
                {"child_id": qa_id, "child_type": "AGENT", "relationship": "SEQUENTIAL"},
            ]
        },
        "logic_gate": {
            "reasoning_config": {"task_type": "thinking", "temperature": 0.3, "reasoning_mode": "REFLECTION"},
            "retry_policy": {"max_retries": 2, "backoff_strategy": "EXPONENTIAL"},
            "context_policy": {"type": "FULL", "summarize_threshold": 30000, "preserve_keys": ["data_summary", "analytics_status", "report_status", "qa_verdict"]}
        },
        "planning": {
            "static_plan": {
                "enabled": True,
                "steps": [
                    {
                        "step_id": "step_1", "order": 1,
                        "name": "Data Processing Phase",
                        "description": "Invoke the Data Processor agent to fetch, clean, analyze, and visualize data.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {"entity_id": dp_id, "prompt_template": "{{input}}", "input_dependencies": []},
                        "required": True
                    },
                    {
                        "step_id": "step_2", "order": 2,
                        "name": "Analytics Quality Gate",
                        "description": "Assess the completeness and quality of the data processing phase.",
                        "type": "ACTION",
                        "target": {
                            "prompt_template": (
                                "Evaluate the data processing output:\n\n{{step_1}}\n\n"
                                "Assess: (1) Data cleaned successfully? (2) Statistics computed? "
                                "(3) Anomalies detected? (4) Forecasts generated? (5) Charts created?\n\n"
                                "Output: PASS or NEEDS_MORE_PROCESSING with specific gaps."
                            ),
                            "input_dependencies": ["step_1"]
                        },
                        "required": True
                    },
                    {
                        "step_id": "step_3", "order": 3,
                        "name": "Report Generation Phase",
                        "description": "Invoke the Report Builder to produce all documents.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {
                            "entity_id": rb_id,
                            "prompt_template": (
                                "Generate all business reports from this analytics data:\n\n"
                                "{{step_1}}\n\nQuality assessment: {{step_2}}"
                            ),
                            "input_dependencies": ["step_1", "step_2"]
                        },
                        "required": True
                    },
                    {
                        "step_id": "step_4", "order": 4,
                        "name": "QA & Delivery Phase",
                        "description": "Validate and archive all outputs.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {
                            "entity_id": qa_id,
                            "prompt_template": (
                                "Validate and archive report outputs:\n\n"
                                "Analytics:\n{{step_1}}\n\nDocuments:\n{{step_3}}"
                            ),
                            "input_dependencies": ["step_1", "step_3"]
                        },
                        "required": True
                    }
                ],
                "fallback_behavior": "ADAPTIVE"
            },
            "dynamic_planning": {
                "enabled": True,
                "planning_prompt": "If Quality Gate returns NEEDS_MORE_PROCESSING, re-invoke Data Processor with specific gaps."
            }
        },
        "capabilities": {
            "tools": [],
            "memory": {
                "enabled": True, "mode": "CORTEX",
                "cortex_config": {"max_children": 12, "page_size_tokens": 8000, "context_budget_pct": 40, "auto_checkpoint": True, "resume_enabled": True}
            },
            "context_engineering": {"inject_cortex_viewport": True, "inject_episodic_memory": True, "no_truncation": True}
        },
        "governance": {"timeout_ms": 3600000, "max_cost_usd": 25.00, "max_recursion_depth": 5, "execution_limits": {"max_tool_calls": 100}},
        "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True}
    }

    try:
        result = client.create_entity(process_payload)
        entity_ids["bi_engine_process"] = result["id"]
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        sys.exit(1)

    # ========================================
    # PHASE 5: Link Entity Hierarchy
    # ========================================
    print("\n" + "=" * 60)
    print("Phase 5: Linking Entity Hierarchy (SKILLs → ACTIONs, AGENTs → SKILLs)")
    print("=" * 60)

    # SKILLs → ACTIONs
    skill_action_map = {
        "data_pipeline_skill": ["fetch_data_action", "clean_transform_action"],
        "analytics_engine_skill": ["statistical_analysis_action", "anomaly_forecasting_action"],
        "chart_generator_skill": ["generate_charts_action"],
        "excel_builder_skill": ["build_workbook_action"],
        "narrative_writer_skill": ["write_docx_report_action"],
        "deck_builder_skill": ["build_exec_deck_action"],
        "pdf_finalizer_skill": ["compile_pdf_action"],
        "qa_pipeline_skill": ["consistency_check_action", "archive_outputs_action"],
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

    # AGENTs → SKILLs
    agent_skill_map = {
        "data_processor_agent": ["data_pipeline_skill", "analytics_engine_skill", "chart_generator_skill"],
        "report_builder_agent": ["excel_builder_skill", "narrative_writer_skill", "deck_builder_skill", "pdf_finalizer_skill"],
        "qa_archiver_agent": ["qa_pipeline_skill"],
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
    # PHASE 6: Patch Agents with real entity UUIDs
    # ========================================
    print("\n" + "=" * 60)
    print("Phase 6: Patching Agents with real entity UUIDs")
    print("=" * 60)

    # --- Patch Data Processor Agent ---
    dp_pipeline_id = entity_ids["data_pipeline_skill"]
    dp_analytics_id = entity_ids["analytics_engine_skill"]
    dp_charts_id = entity_ids["chart_generator_skill"]

    client.update_entity(entity_ids["data_processor_agent"], {
        "planning": {
            "static_plan": {
                "enabled": True,
                "fallback_behavior": "ADAPTIVE",
                "steps": [
                    {
                        "step_id": "step_1", "order": 1,
                        "name": "Data Pipeline",
                        "description": "Invoke data pipeline to fetch, clean, and transform data.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {"entity_id": dp_pipeline_id, "prompt_template": "{{input}}"},
                        "required": True
                    },
                    {
                        "step_id": "step_2", "order": 2,
                        "name": "Analytics Engine",
                        "description": "Run statistical analysis, anomaly detection, and forecasting.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {"entity_id": dp_analytics_id, "prompt_template": "Analyze this cleaned data:\n\n{{step_1}}", "input_dependencies": ["step_1"]},
                        "required": True
                    },
                    {
                        "step_id": "step_3", "order": 3,
                        "name": "Chart Generation",
                        "description": "Generate business visualizations.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {"entity_id": dp_charts_id, "prompt_template": "Generate charts:\n\nDATA:\n{{step_1}}\n\nANALYTICS:\n{{step_2}}", "input_dependencies": ["step_1", "step_2"]},
                        "required": True
                    }
                ]
            },
            "dynamic_planning": {"enabled": False}
        }
    })
    print(f"  ✅ Data Processor patched: pipeline={dp_pipeline_id}, analytics={dp_analytics_id}, charts={dp_charts_id}")

    # --- Patch Report Builder Agent ---
    rb_excel_id = entity_ids["excel_builder_skill"]
    rb_docx_id = entity_ids["narrative_writer_skill"]
    rb_pptx_id = entity_ids["deck_builder_skill"]
    rb_pdf_id = entity_ids["pdf_finalizer_skill"]

    client.update_entity(entity_ids["report_builder_agent"], {
        "planning": {
            "static_plan": {
                "enabled": True,
                "fallback_behavior": "STRICT",
                "steps": [
                    {
                        "step_id": "step_1", "order": 1,
                        "name": "Build Excel Workbook",
                        "description": "Create multi-sheet Excel workbook.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {"entity_id": rb_excel_id, "prompt_template": "Create Excel workbook from:\n\n{{input}}"},
                        "required": True
                    },
                    {
                        "step_id": "step_2", "order": 2,
                        "name": "Write Narrative Report",
                        "description": "Write DOCX narrative report.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {"entity_id": rb_docx_id, "prompt_template": "Write report:\n\n{{input}}\n\nExcel:\n{{step_1}}", "input_dependencies": ["step_1"]},
                        "required": True
                    },
                    {
                        "step_id": "step_3", "order": 3,
                        "name": "Build Executive Deck",
                        "description": "Create PPTX executive presentation.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {"entity_id": rb_pptx_id, "prompt_template": "Create deck:\n\n{{input}}\n\nHighlights:\n{{step_2}}", "input_dependencies": ["step_2"]},
                        "required": True
                    },
                    {
                        "step_id": "step_4", "order": 4,
                        "name": "Compile Final PDF",
                        "description": "Compile PDF report package.",
                        "type": "CHILD_ENTITY_INVOCATION",
                        "target": {"entity_id": rb_pdf_id, "prompt_template": "Compile PDF:\n\n{{step_2}}", "input_dependencies": ["step_2"]},
                        "required": True
                    }
                ]
            },
            "dynamic_planning": {"enabled": False}
        }
    })
    print(f"  ✅ Report Builder patched: excel={rb_excel_id}, docx={rb_docx_id}, pptx={rb_pptx_id}, pdf={rb_pdf_id}")

    # --- Patch QA Agent ---
    qa_pipeline_id = entity_ids["qa_pipeline_skill"]
    client.update_entity(entity_ids["qa_archiver_agent"], {
        "planning": {
            "static_plan": {
                "enabled": True,
                "fallback_behavior": "STRICT",
                "steps": [{
                    "step_id": "step_1", "order": 1,
                    "name": "QA Pipeline",
                    "description": "Validate and archive.",
                    "type": "CHILD_ENTITY_INVOCATION",
                    "target": {"entity_id": qa_pipeline_id, "prompt_template": "Validate and archive:\n\n{{input}}"},
                    "required": True
                }]
            },
            "dynamic_planning": {"enabled": False}
        }
    })
    print(f"  ✅ QA Agent patched: qa_pipeline={qa_pipeline_id}")

    # --- Patch SKILLs with real ACTION UUIDs ---
    print("\n  Patching SKILLs with real ACTION UUIDs...")

    skill_action_uuid_patches = {
        "data_pipeline_skill": [
            ("Fetch Raw Data", entity_ids["fetch_data_action"], "{{input}}"),
            ("Clean and Transform", entity_ids["clean_transform_action"], "Clean and transform this raw data for analysis:\n\n{{step_1}}"),
        ],
        "analytics_engine_skill": [
            ("Statistical Analysis", entity_ids["statistical_analysis_action"], "Perform statistical analysis on this data:\n\n{{input}}"),
            ("Anomaly Detection & Forecasting", entity_ids["anomaly_forecasting_action"], "Using this statistical profile:\n\n{{step_1}}\n\nDetect anomalies and generate forecasts:\n\n{{input}}"),
        ],
        "chart_generator_skill": [
            ("Generate All Charts", entity_ids["generate_charts_action"], "Generate business intelligence charts from this data:\n\n{{input}}"),
        ],
        "excel_builder_skill": [
            ("Build Workbook", entity_ids["build_workbook_action"], "Create an Excel workbook from:\n\n{{input}}"),
        ],
        "narrative_writer_skill": [
            ("Write Report", entity_ids["write_docx_report_action"], "Write a comprehensive business report from:\n\n{{input}}"),
        ],
        "deck_builder_skill": [
            ("Build Deck", entity_ids["build_exec_deck_action"], "Create an executive presentation from:\n\n{{input}}"),
        ],
        "pdf_finalizer_skill": [
            ("Compile PDF", entity_ids["compile_pdf_action"], "Compile this report content into a professional PDF:\n\n{{input}}"),
        ],
        "qa_pipeline_skill": [
            ("Consistency Check", entity_ids["consistency_check_action"], "Validate consistency across these documents:\n\n{{input}}"),
            ("Archive Outputs", entity_ids["archive_outputs_action"], "Archive these report outputs. QA result:\n\n{{step_1}}\n\nDocuments:\n\n{{input}}"),
        ],
    }

    for skill_key, steps_data in skill_action_uuid_patches.items():
        steps = []
        for i, (name, action_id, prompt) in enumerate(steps_data, 1):
            step = {
                "step_id": f"step_{i}", "order": i,
                "name": name,
                "type": "CHILD_ENTITY_INVOCATION",
                "target": {"entity_id": action_id, "prompt_template": prompt},
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

    # ========================================
    # Summary
    # ========================================
    print("\n" + "=" * 60)
    print("✅ Autonomous BI Engine Setup Complete!")
    print("=" * 60)
    print(f"\nTotal entities created: {len(entity_ids)}")

    print("\n📊 Entity Hierarchy:")
    print(f"  PROCESS: 📊 Autonomous BI Engine → {entity_ids['bi_engine_process']}")
    print(f"  ├── AGENT: Data Processor → {entity_ids['data_processor_agent']}")
    print(f"  │   ├── SKILL: Data Pipeline → {entity_ids['data_pipeline_skill']}")
    print(f"  │   │   ├── ACTION: Fetch Data → {entity_ids['fetch_data_action']}")
    print(f"  │   │   └── ACTION: Clean & Transform → {entity_ids['clean_transform_action']}")
    print(f"  │   ├── SKILL: Analytics Engine → {entity_ids['analytics_engine_skill']}")
    print(f"  │   │   ├── ACTION: Statistical Analysis → {entity_ids['statistical_analysis_action']}")
    print(f"  │   │   └── ACTION: Anomaly & Forecasting → {entity_ids['anomaly_forecasting_action']}")
    print(f"  │   └── SKILL: Chart Generator → {entity_ids['chart_generator_skill']}")
    print(f"  │       └── ACTION: Generate Charts → {entity_ids['generate_charts_action']}")
    print(f"  ├── AGENT: Report Builder → {entity_ids['report_builder_agent']}")
    print(f"  │   ├── SKILL: Excel Builder → {entity_ids['excel_builder_skill']}")
    print(f"  │   │   └── ACTION: Build Workbook → {entity_ids['build_workbook_action']}")
    print(f"  │   ├── SKILL: Narrative Writer → {entity_ids['narrative_writer_skill']}")
    print(f"  │   │   └── ACTION: Write DOCX Report → {entity_ids['write_docx_report_action']}")
    print(f"  │   ├── SKILL: Deck Builder → {entity_ids['deck_builder_skill']}")
    print(f"  │   │   └── ACTION: Build Exec Deck → {entity_ids['build_exec_deck_action']}")
    print(f"  │   └── SKILL: PDF Finalizer → {entity_ids['pdf_finalizer_skill']}")
    print(f"  │       └── ACTION: Compile PDF → {entity_ids['compile_pdf_action']}")
    print(f"  └── AGENT: QA & Delivery → {entity_ids['qa_archiver_agent']}")
    print(f"      └── SKILL: QA Pipeline → {entity_ids['qa_pipeline_skill']}")
    print(f"          ├── ACTION: Consistency Check → {entity_ids['consistency_check_action']}")
    print(f"          └── ACTION: Archive Outputs → {entity_ids['archive_outputs_action']}")

    # Save entity IDs
    output_path = os.path.join(os.path.dirname(__file__), "entity_ids.json")
    with open(output_path, "w") as f:
        json.dump(entity_ids, f, indent=2)
    print(f"\nEntity IDs saved to: {output_path}")
    print(f"\nNext: python trigger_bi_execution.py")


if __name__ == "__main__":
    main()

"""Layer 3: AGENT entity definitions for Autonomous BI Engine."""

AGENTS = [
    {
        "key": "data_processor_agent",
        "payload": {
            "name": "bi-data-processor",
            "display_name": "BI Data Processor & Analyst",
            "description": "Autonomous agent that orchestrates the complete data processing pipeline: ingestion, cleaning, statistical analysis, anomaly detection, forecasting, and chart generation.",
            "goal": "Process raw business data into actionable analytics: clean datasets, statistical profiles, anomaly reports, forecasts, and visualizations.",
            "type": "AGENT", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "data-agent", "analytics", "orchestrator"],
            "identity": {
                "system_prompt": (
                    "You are the Data Processor Agent — a senior data scientist orchestrating a complete analytics pipeline.\n\n"
                    "## Your Process:\n"
                    "1. **Data Ingestion**: Invoke bi-data-pipeline to fetch and clean the data\n"
                    "2. **Analytics**: Invoke bi-analytics-engine to run statistical analysis, anomaly detection, and forecasting\n"
                    "3. **Visualization**: Invoke bi-chart-generator to create business charts\n\n"
                    "## Critical Rules:\n"
                    "- Each step builds on the previous — pass outputs forward\n"
                    "- If data ingestion fails, generate realistic sample data instead\n"
                    "- Ensure all analytics reference the same cleaned dataset\n"
                    "- Charts must reflect the actual analytics findings"
                ),
                "behavioral_constraints": [
                    "Always run all 3 phases: pipeline → analytics → charts",
                    "Pass the full data context between phases",
                    "If real data unavailable, generate sample data with realistic patterns",
                    "Checkpoint after each phase completion"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 2, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "thinking", "temperature": 0.3, "reasoning_mode": "REFLECTION", "goal_validation_interval": 2},
                "retry_policy": {"max_retries": 2, "backoff_strategy": "EXPONENTIAL"},
                "context_policy": {"type": "SLIDING_WINDOW", "max_chars": 30000, "summarize_threshold": 25000, "preserve_keys": ["data_summary", "analytics_results", "chart_paths"]},
                "review_mechanism": {"enabled": True, "review_prompt": "Evaluate data processing completeness: (1) Data cleaned? (2) Stats computed? (3) Anomalies detected? (4) Forecasts generated? (5) Charts created?", "on_failure": "RETRY"}
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "fallback_behavior": "ADAPTIVE",
                    "steps": [
                        {
                            "step_id": "step_1", "order": 1,
                            "name": "Data Pipeline",
                            "description": "Invoke the data pipeline skill to fetch, clean, and transform data.",
                            "type": "CHILD_ENTITY_INVOCATION",
                            "target": {"entity_id": "__PLACEHOLDER__", "prompt_template": "{{input}}"},
                            "required": True
                        },
                        {
                            "step_id": "step_2", "order": 2,
                            "name": "Analytics Engine",
                            "description": "Run statistical analysis, anomaly detection, and forecasting on the cleaned data.",
                            "type": "CHILD_ENTITY_INVOCATION",
                            "target": {"entity_id": "__PLACEHOLDER__", "prompt_template": "Analyze this cleaned data:\n\n{{step_1}}", "input_dependencies": ["step_1"]},
                            "required": True
                        },
                        {
                            "step_id": "step_3", "order": 3,
                            "name": "Chart Generation",
                            "description": "Generate business visualizations from the analytics results.",
                            "type": "CHILD_ENTITY_INVOCATION",
                            "target": {"entity_id": "__PLACEHOLDER__", "prompt_template": "Generate charts from this analytics data:\n\nCLEANED DATA:\n{{step_1}}\n\nANALYTICS:\n{{step_2}}", "input_dependencies": ["step_1", "step_2"]},
                            "required": True
                        }
                    ]
                },
                "dynamic_planning": {"enabled": False}
            },
            "capabilities": {
                "tools": [{"tool_id": "terminal_tool"}, {"tool_id": "sandbox_executor"}],
                "memory": {"enabled": True, "mode": "CORTEX", "memory_scope": "INTELLIGENCE_ONLY", "cortex_config": {"max_children": 12, "auto_checkpoint": True, "context_budget_pct": 40, "resume_enabled": True}},
                "context_engineering": {"inject_cortex_viewport": True, "inject_episodic_memory": False, "inject_semantic_context": True, "no_truncation": True}
            },
            "governance": {"timeout_ms": 900000, "max_cost_usd": 5.00, "max_recursion_depth": 4, "execution_limits": {"max_tool_calls": 30}},
            "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True}
        }
    },
    {
        "key": "report_builder_agent",
        "payload": {
            "name": "bi-report-builder",
            "display_name": "BI Report Builder",
            "description": "Autonomous report generation agent that produces all business deliverables: Excel workbook, DOCX narrative report, PPTX executive deck, and PDF final package.",
            "goal": "Transform analytics results into a complete suite of professional business documents — Excel, DOCX, PPTX, and PDF.",
            "type": "AGENT", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "report-agent", "document-generation"],
            "identity": {
                "system_prompt": (
                    "You are the Report Builder Agent — a senior business analyst who produces executive-quality deliverables.\n\n"
                    "## Your Document Pipeline:\n"
                    "1. **Excel Workbook**: Raw data + KPI dashboard + pivot summaries\n"
                    "2. **DOCX Report**: Narrative analysis with exec summary, deep-dive, recommendations\n"
                    "3. **PPTX Deck**: 8-10 slide executive presentation\n"
                    "4. **PDF Package**: Final polished report for distribution\n\n"
                    "## Critical Rules:\n"
                    "- All documents must contain the SAME numbers — consistency is paramount\n"
                    "- Use the analytics data provided, do not invent new numbers\n"
                    "- Each document format serves a different audience: Excel for analysts, DOCX for managers, PPTX for executives, PDF for external"
                ),
                "behavioral_constraints": [
                    "All 4 document types must be generated",
                    "Same KPI numbers must appear in every document",
                    "DOCX recommendations must match PPTX recommendations",
                    "Generate documents sequentially — Excel → DOCX → PPTX → PDF"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 2, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.4, "reasoning_mode": "REFLECTION"},
                "context_policy": {"type": "FULL", "summarize_threshold": 30000, "preserve_keys": ["analytics_data", "excel_summary", "report_content"]},
                "review_mechanism": {"enabled": True, "review_prompt": "Verify all 4 documents were generated: Excel, DOCX, PPTX, PDF. Check that key metrics are consistent across all.", "on_failure": "RETRY"}
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "fallback_behavior": "STRICT",
                    "steps": [
                        {
                            "step_id": "step_1", "order": 1,
                            "name": "Build Excel Workbook",
                            "description": "Create multi-sheet Excel workbook with data and dashboards.",
                            "type": "CHILD_ENTITY_INVOCATION",
                            "target": {"entity_id": "__PLACEHOLDER__", "prompt_template": "Create Excel workbook from analytics:\n\n{{input}}"},
                            "required": True
                        },
                        {
                            "step_id": "step_2", "order": 2,
                            "name": "Write Narrative Report",
                            "description": "Write comprehensive DOCX narrative report.",
                            "type": "CHILD_ENTITY_INVOCATION",
                            "target": {"entity_id": "__PLACEHOLDER__", "prompt_template": "Write a narrative business report using this analytics data:\n\n{{input}}\n\nExcel summary:\n{{step_1}}", "input_dependencies": ["step_1"]},
                            "required": True
                        },
                        {
                            "step_id": "step_3", "order": 3,
                            "name": "Build Executive Deck",
                            "description": "Create PPTX executive presentation.",
                            "type": "CHILD_ENTITY_INVOCATION",
                            "target": {"entity_id": "__PLACEHOLDER__", "prompt_template": "Create executive deck from:\n\nAnalytics:\n{{input}}\n\nReport highlights:\n{{step_2}}", "input_dependencies": ["step_2"]},
                            "required": True
                        },
                        {
                            "step_id": "step_4", "order": 4,
                            "name": "Compile Final PDF",
                            "description": "Compile the final PDF report package.",
                            "type": "CHILD_ENTITY_INVOCATION",
                            "target": {"entity_id": "__PLACEHOLDER__", "prompt_template": "Compile final PDF from report:\n\n{{step_2}}", "input_dependencies": ["step_2"]},
                            "required": True
                        }
                    ]
                },
                "dynamic_planning": {"enabled": False}
            },
            "capabilities": {
                "tools": [{"tool_id": "excel_tool"}, {"tool_id": "docx_tool"}, {"tool_id": "pptx_tool"}, {"tool_id": "pdf_generator"}],
                "memory": {"enabled": True, "mode": "CORTEX", "memory_scope": "INTELLIGENCE_ONLY", "cortex_config": {"auto_checkpoint": True, "context_budget_pct": 50, "resume_enabled": True}},
                "context_engineering": {"inject_cortex_viewport": True, "inject_episodic_memory": False, "no_truncation": True}
            },
            "governance": {"timeout_ms": 900000, "max_cost_usd": 5.00, "max_recursion_depth": 3},
            "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True}
        }
    },
    {
        "key": "qa_archiver_agent",
        "payload": {
            "name": "bi-qa-archiver",
            "display_name": "BI QA & Delivery Agent",
            "description": "Quality assurance agent that validates cross-document consistency and archives all report artifacts for delivery.",
            "goal": "Ensure data integrity across all generated documents and organize outputs for clean delivery.",
            "type": "AGENT", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "qa-agent", "validation", "delivery"],
            "identity": {
                "system_prompt": (
                    "You are the QA & Delivery Agent — a meticulous quality controller.\n\n"
                    "## Your Process:\n"
                    "1. **Validate**: Check that key metrics are consistent across Excel, DOCX, PPTX, and PDF\n"
                    "2. **Archive**: Organize all outputs into a dated folder with a manifest\n\n"
                    "## Quality Standards:\n"
                    "- Revenue, cost, margin, and customer numbers must match across ALL documents\n"
                    "- Any discrepancy >1% is a CRITICAL failure\n"
                    "- Archive must include every generated artifact"
                ),
                "behavioral_constraints": [
                    "Run consistency check before archiving",
                    "Flag any cross-document discrepancies",
                    "Archive includes manifest.json listing all files",
                    "Report overall QA verdict: PASS or FAIL"
                ]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 2, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 20000}
            },
            "planning": {
                "static_plan": {
                    "enabled": True,
                    "fallback_behavior": "STRICT",
                    "steps": [
                        {
                            "step_id": "step_1", "order": 1,
                            "name": "QA Pipeline",
                            "description": "Run cross-document validation and archive outputs.",
                            "type": "CHILD_ENTITY_INVOCATION",
                            "target": {"entity_id": "__PLACEHOLDER__", "prompt_template": "Validate and archive these report outputs:\n\n{{input}}"},
                            "required": True
                        }
                    ]
                },
                "dynamic_planning": {"enabled": False}
            },
            "capabilities": {
                "tools": [{"tool_id": "sandbox_executor"}, {"tool_id": "terminal_tool"}],
                "memory": {"enabled": True, "mode": "CORTEX", "memory_scope": "INTELLIGENCE_ONLY", "cortex_config": {"auto_checkpoint": True}},
                "context_engineering": {"inject_cortex_viewport": True, "inject_episodic_memory": False, "no_truncation": True}
            },
            "governance": {"timeout_ms": 300000, "max_cost_usd": 1.00, "max_recursion_depth": 3},
            "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True}
        }
    },
]

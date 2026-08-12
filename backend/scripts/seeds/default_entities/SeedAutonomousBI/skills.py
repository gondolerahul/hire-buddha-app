"""Layer 2: SKILL entity definitions for Autonomous BI Engine."""

SKILLS = [
    {
        "key": "data_pipeline_skill",
        "payload": {
            "name": "bi-data-pipeline",
            "display_name": "BI Data Pipeline",
            "description": "End-to-end data ingestion pipeline: fetches raw data from sources and transforms it into clean, analysis-ready datasets.",
            "goal": "Produce a clean, validated, analysis-ready dataset from raw data sources.",
            "type": "SKILL", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "data-pipeline", "etl"],
            "identity": {
                "system_prompt": "You orchestrate a 2-step data pipeline: (1) Fetch raw data using terminal commands, (2) Clean and transform using pandas. Pass the raw data output from step 1 into step 2.",
                "behavioral_constraints": ["Fetch must complete before transform begins", "Output must include both raw data stats and cleaned data stats"]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.3, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 15000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [
                    {"step_id": "step_1", "order": 1, "name": "Fetch Raw Data", "description": "Use terminal to fetch raw business data from configured sources", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER_fetch_data__", "prompt_template": "{{input}}"}, "required": True},
                    {"step_id": "step_2", "order": 2, "name": "Clean and Transform", "description": "Transform raw data into clean analysis-ready format", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER_clean_transform__", "prompt_template": "Clean and transform this raw data for analysis:\n\n{{step_1}}", "input_dependencies": ["step_1"]}, "required": True}
                ]},
                "dynamic_planning": {"enabled": False}
            },
            "capabilities": {"tools": [{"tool_id": "terminal_tool"}, {"tool_id": "sandbox_executor"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.50}
        }
    },
    {
        "key": "analytics_engine_skill",
        "payload": {
            "name": "bi-analytics-engine",
            "display_name": "BI Analytics Engine",
            "description": "Full analytics suite: statistical analysis followed by anomaly detection and forecasting.",
            "goal": "Produce comprehensive analytics including descriptive stats, trend analysis, anomaly detection, and forward-looking forecasts.",
            "type": "SKILL", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "analytics", "statistics", "forecasting"],
            "identity": {
                "system_prompt": "You orchestrate a 2-step analytics process: (1) Run statistical analysis, (2) Run anomaly detection and forecasting. Each step builds on the previous.",
                "behavioral_constraints": ["Statistical analysis must complete before anomaly detection", "Both steps must use the same underlying dataset"]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.2, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 20000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [
                    {"step_id": "step_1", "order": 1, "name": "Statistical Analysis", "description": "Run comprehensive statistical analysis", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER_stat_analysis__", "prompt_template": "Perform statistical analysis on this data:\n\n{{input}}"}, "required": True},
                    {"step_id": "step_2", "order": 2, "name": "Anomaly Detection & Forecasting", "description": "Detect anomalies and generate forecasts", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER_anomaly_forecast__", "prompt_template": "Using this statistical profile:\n\n{{step_1}}\n\nDetect anomalies and generate forecasts for the dataset:\n\n{{input}}", "input_dependencies": ["step_1"]}, "required": True}
                ]},
                "dynamic_planning": {"enabled": False}
            },
            "capabilities": {"tools": [{"tool_id": "sandbox_executor"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 300000, "max_cost_usd": 0.60}
        }
    },
    {
        "key": "chart_generator_skill",
        "payload": {
            "name": "bi-chart-generator",
            "display_name": "BI Chart Generator",
            "description": "Creates publication-quality business charts and visualizations using matplotlib/seaborn.",
            "goal": "Generate a complete set of business charts that visually communicate the data story.",
            "type": "SKILL", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "visualization", "charts"],
            "identity": {
                "system_prompt": "You manage the chart generation pipeline. Invoke the chart generator action with the analytics data to produce all required visualizations.",
                "behavioral_constraints": ["Must produce at least 3 different chart types", "All charts must be saved as PNG files"]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.3, "reasoning_mode": "REACT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 15000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [
                    {"step_id": "step_1", "order": 1, "name": "Generate All Charts", "description": "Create the full suite of business visualizations", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER_gen_charts__", "prompt_template": "Generate business intelligence charts from this data:\n\n{{input}}"}, "required": True}
                ]}
            },
            "capabilities": {"tools": [{"tool_id": "sandbox_executor"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 180000, "max_cost_usd": 0.30}
        }
    },
    {
        "key": "excel_builder_skill",
        "payload": {
            "name": "bi-excel-builder",
            "display_name": "BI Excel Builder",
            "description": "Creates comprehensive Excel workbooks with raw data, KPI dashboards, and pivot summaries.",
            "goal": "Produce a multi-sheet Excel workbook serving as both data repository and interactive dashboard.",
            "type": "SKILL", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "excel", "dashboard"],
            "identity": {
                "system_prompt": "You manage Excel workbook creation. Invoke the workbook builder with processed data and analytics.",
                "behavioral_constraints": ["Workbook must contain at least 3 sheets", "Include conditional formatting for KPIs"]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.3, "reasoning_mode": "REACT"}, "context_policy": {"type": "FULL", "summarize_threshold": 20000}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Build Workbook", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER_build_workbook__", "prompt_template": "Create an Excel workbook from:\n\n{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "excel_tool"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 180000, "max_cost_usd": 0.20}
        }
    },
    {
        "key": "narrative_writer_skill",
        "payload": {
            "name": "bi-narrative-writer",
            "display_name": "BI Narrative Report Writer",
            "description": "Writes comprehensive narrative business reports in DOCX format.",
            "goal": "Produce a professional narrative report that explains the numbers in business context.",
            "type": "SKILL", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "docx", "narrative"],
            "identity": {
                "system_prompt": "You manage narrative report creation. Invoke the DOCX writer with analytics data and insights.",
                "behavioral_constraints": ["Report must include exec summary, analysis, and recommendations"]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.5, "reasoning_mode": "CHAIN_OF_THOUGHT"}, "context_policy": {"type": "FULL", "summarize_threshold": 25000}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Write Report", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER_write_docx__", "prompt_template": "Write a comprehensive business report from:\n\n{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "docx_tool"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 240000, "max_cost_usd": 0.40}
        }
    },
    {
        "key": "deck_builder_skill",
        "payload": {
            "name": "bi-deck-builder",
            "display_name": "BI Executive Deck Builder",
            "description": "Creates executive presentation decks in PPTX format.",
            "goal": "Build a board-ready presentation communicating key metrics and recommendations.",
            "type": "SKILL", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "pptx", "presentation"],
            "identity": {
                "system_prompt": "You manage executive deck creation. Invoke the PPTX builder with analytics data and insights.",
                "behavioral_constraints": ["Deck must have 8-10 slides", "Maximum 6 bullets per slide"]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.4, "reasoning_mode": "CHAIN_OF_THOUGHT"}, "context_policy": {"type": "FULL", "summarize_threshold": 20000}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Build Deck", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER_build_deck__", "prompt_template": "Create an executive presentation from:\n\n{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "pptx_tool"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 240000, "max_cost_usd": 0.30}
        }
    },
    {
        "key": "pdf_finalizer_skill",
        "payload": {
            "name": "bi-pdf-finalizer",
            "display_name": "BI PDF Finalizer",
            "description": "Compiles the final polished PDF report package.",
            "goal": "Produce a publication-ready PDF combining all analysis into a single professional document.",
            "type": "SKILL", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "pdf", "final-output"],
            "identity": {
                "system_prompt": "You manage PDF compilation. Invoke the PDF compiler with the full report content.",
                "behavioral_constraints": ["PDF must include table of contents", "Preserve all formatting and citations"]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {"reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "REACT"}},
            "planning": {"static_plan": {"enabled": True, "steps": [{"step_id": "step_1", "order": 1, "name": "Compile PDF", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER_compile_pdf__", "prompt_template": "Compile this report content into a professional PDF:\n\n{{input}}"}, "required": True}]}},
            "capabilities": {"tools": [{"tool_id": "pdf_generator"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 180000, "max_cost_usd": 0.15}
        }
    },
    {
        "key": "qa_pipeline_skill",
        "payload": {
            "name": "bi-qa-pipeline",
            "display_name": "BI QA Pipeline",
            "description": "Quality assurance pipeline: validates cross-document consistency then archives all outputs.",
            "goal": "Ensure all generated documents contain consistent data and organize them for delivery.",
            "type": "SKILL", "version": "1.0.0", "status": "ACTIVE",
            "tags": ["bi-engine", "qa", "validation", "archive"],
            "identity": {
                "system_prompt": "You manage the QA and delivery pipeline: (1) Validate consistency across all generated documents, (2) Archive all outputs with a manifest.",
                "behavioral_constraints": ["Consistency check must pass before archiving", "Archive must include all generated artifacts"]
            },
            "hierarchy": {"is_atomic": False, "composition_depth": 1, "children": []},
            "logic_gate": {
                "reasoning_config": {"task_type": "text_generation", "temperature": 0.1, "reasoning_mode": "CHAIN_OF_THOUGHT"},
                "context_policy": {"type": "FULL", "summarize_threshold": 20000}
            },
            "planning": {
                "static_plan": {"enabled": True, "steps": [
                    {"step_id": "step_1", "order": 1, "name": "Consistency Check", "description": "Validate numbers match across all documents", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER_consistency__", "prompt_template": "Validate consistency across these documents:\n\n{{input}}"}, "required": True},
                    {"step_id": "step_2", "order": 2, "name": "Archive Outputs", "description": "Organize and archive all report artifacts", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_id": "__PLACEHOLDER_archive__", "prompt_template": "Archive these report outputs. QA result:\n\n{{step_1}}\n\nDocuments:\n\n{{input}}", "input_dependencies": ["step_1"]}, "required": True}
                ]}
            },
            "capabilities": {"tools": [{"tool_id": "sandbox_executor"}, {"tool_id": "terminal_tool"}], "memory": {"enabled": True, "mode": "CORTEX"}},
            "governance": {"timeout_ms": 120000, "max_cost_usd": 0.20}
        }
    },
]

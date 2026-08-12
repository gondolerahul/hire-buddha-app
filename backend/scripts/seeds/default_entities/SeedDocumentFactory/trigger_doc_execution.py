#!/usr/bin/env python3
"""
Document Factory Engine — Trigger Script
==========================================
Triggers document generation with a sample request.

Usage:
    python trigger_doc_execution.py
    python trigger_doc_execution.py --request "Create a quarterly sales report as PPTX"
"""

import json, os, sys

sys.path.insert(0, os.path.dirname(__file__))
from config import APIClient


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Trigger Document Factory execution")
    parser.add_argument("--request", type=str, default=None, help="Custom document request")
    parser.add_argument("--entity-id", type=str, default=None, help="Specific entity ID to trigger")
    args = parser.parse_args()

    # Load entity IDs
    ids_path = os.path.join(os.path.dirname(__file__), "entity_ids.json")
    if not os.path.exists(ids_path):
        print("❌ entity_ids.json not found. Run create_doc_entities.py first.")
        sys.exit(1)

    with open(ids_path) as f:
        entity_ids = json.load(f)

    # Determine target entity
    target_id = args.entity_id or entity_ids.get("doc_factory_process")
    if not target_id:
        print("❌ No target entity found. Provide --entity-id or ensure doc_factory_process exists.")
        sys.exit(1)

    # Build request
    default_request = (
        "Create a comprehensive Q4 2024 Business Performance Report package:\n\n"
        "1. **PPTX**: Executive slide deck (12-15 slides) with:\n"
        "   - Revenue: $4.2M (+15% YoY)\n"
        "   - New customers: 127\n"
        "   - CAC: $2,340\n"
        "   - NPS: 72\n"
        "   - Use a modern dark theme with data visualizations\n\n"
        "2. **XLSX**: Financial model with:\n"
        "   - Revenue breakdown by product line (3 products)\n"
        "   - Monthly P&L for Q4 (Oct, Nov, Dec)\n"
        "   - Customer metrics dashboard\n"
        "   - All calculations must use formulas\n\n"
        "3. **DOCX**: Board memo summarizing key findings and recommendations\n\n"
        "Ensure all documents use consistent numbers and branding."
    )

    request_text = args.request or default_request

    # Trigger execution
    client = APIClient()
    print("=" * 60)
    print("📄 Document Factory Engine — Triggering Execution")
    print("=" * 60)
    print(f"Target entity: {target_id}")
    print(f"Request:\n{request_text[:200]}{'...' if len(request_text) > 200 else ''}")

    # NOTE on enabling Phase 11: the AgentLoop master switch (agent_loop.enabled)
    # and meta_agent.board_routing both default OFF. The /execute endpoint does
    # NOT accept a run-scope flag override, so the switches are carried on each
    # seeded entity instead — in metadata_extensions.feature_flags (written by
    # phase11.py at create time). The execution gate
    # (core/execution_engine.py::execute_run) reads exactly that channel via
    # entity_extras, so every entity in this hierarchy routes through the new
    # agent kernel automatically. Nothing extra is needed here.
    #
    # The /execute endpoint schema (schemas/execution.py::ExecutionRunCreate) is
    # strict: it accepts ONLY {entity_id, input_data}. input_data is the dict the
    # entity's io_contract expects — here {"input": <request text>}. (Older
    # versions of this script sent input/execution_mode/context at the top level,
    # which the schema rejects with HTTP 422.)
    trigger_payload = {
        "entity_id": target_id,
        "input_data": {"input": request_text},
    }

    try:
        resp = client.session.post(f"{client.base_url}/ai/execute", json=trigger_payload)
        if resp.status_code in (200, 201, 202):
            result = resp.json()
            print(f"\n✅ Execution triggered!")
            print(f"Execution ID: {result.get('execution_id', 'N/A')}")
            print(f"Status: {result.get('status', 'STARTED')}")
        else:
            print(f"\n❌ Trigger failed: {resp.status_code}")
            print(f"Response: {resp.text[:500]}")
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    main()

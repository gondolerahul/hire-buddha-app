"""JSON columns become JSONB, except three whose key order is their content (DM-13)

Revision ID: dm13_jsonb
Revises: dm14_metadata_columns
Create Date: 2026-10-01

Older tables used ``json`` and newer ones ``jsonb``, a split that ran through
``hierarchical_entities``. ``json`` keeps the text as written, so every read
re-parses it, and it has no equality or containment operators and no index
support. Twenty-seven columns move to ``jsonb``.

Three stay ``json`` on purpose, because ``jsonb`` re-sorts object keys and
their order means something:

- ``execution_runs.context_state``: key order is step order. The step
  executor keeps the most recent steps when it trims, and a resumed run reads
  the state back.
- ``hierarchical_entities.io_contract``: the schemas' property order is the
  Execute form's field order and the output's section order.
- ``tool_registry_entries.function_schema``: an authored JSON Schema, shown
  back in the editor and sent to the model as written.

``jsonb`` rejects the ``\\u0000`` escape that ``json`` accepts. No stored
value has one (checked before the change), and ``src/common/database.py``
now drops NUL characters from JSON it writes. The ``kpi_daily_rollup``
view reads ``tags``, so it is dropped and rebuilt around the change.
"""
from typing import Sequence, Union

from alembic import op

from migrations.kpi_rollup_view import rebuilt

revision: str = "dm13_jsonb"
down_revision: Union[str, Sequence[str], None] = "dm14_metadata_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = {
    "artifacts": ["artifact_metadata"],
    "call_content": ["content_metadata"],
    "execution_runs": ["input_data", "dynamic_plan", "result_data"],
    "feature_flags": ["value_json"],
    "hierarchical_entities": ["tags", "identity", "hierarchy", "logic_gate", "planning", "capabilities",
                              "governance", "observability", "metadata_extensions"],
    "human_approvals": ["context_snapshot", "notification_channels"],
    "integration_registry": ["service_metadata"],
    "llm_interaction_logs": ["log_metadata"],
    "payment_transactions": ["transaction_metadata"],
    "social_connections": ["scopes", "oauth_metadata"],
    "tool_interaction_logs": ["input_parameters", "output_result", "log_metadata"],
    "tool_registry_entries": ["configuration"],
    "usage_logs": ["log_metadata"],
}


def _alter(to: str) -> None:
    for table, columns in COLUMNS.items():
        changes = ", ".join(f"ALTER COLUMN {c} TYPE {to} USING {c}::{to}" for c in columns)
        op.execute(f"ALTER TABLE {table} {changes}")


def upgrade() -> None:
    with rebuilt():  # kpi_daily_rollup reads hierarchical_entities.tags
        _alter("jsonb")


def downgrade() -> None:
    with rebuilt():
        _alter("json")

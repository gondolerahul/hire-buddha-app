"""Phase 11: execution_trace_events — per-iteration transparency spans

Adds the append-only span table that backs the Execution Detail "what happened
inside each iteration" view: one row per unit of work (iteration → executor →
step → tool / llm / child), written by ``src.ai.core.trace.TraceRecorder``.

Kept separate from the CORTEX memory tables so trace data can be pruned
independently and never pollutes semantic memory.

Revision ID: p11_execution_trace_events
Revises: p11t10_cortex_entity_nullable
Create Date: 2026-06-02
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "p11_execution_trace_events"      # 26 chars — under the 32-char cap
down_revision = "p11t10_cortex_entity_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_trace_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("execution_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_id", UUID(as_uuid=True), nullable=True),
        sa.Column("span_id", UUID(as_uuid=True), nullable=False),
        sa.Column("parent_span_id", UUID(as_uuid=True), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="running"),
        sa.Column("seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("child_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_execution_trace_events_run_seq",
        "execution_trace_events", ["run_id", "seq"],
    )
    op.create_index(
        "ix_execution_trace_events_run_iter",
        "execution_trace_events", ["run_id", "iteration"],
    )
    op.create_index(
        "ix_execution_trace_events_run_parent",
        "execution_trace_events", ["run_id", "parent_span_id"],
    )
    op.create_index(
        "ix_execution_trace_events_span",
        "execution_trace_events", ["span_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_execution_trace_events_span",
                  table_name="execution_trace_events")
    op.drop_index("ix_execution_trace_events_run_parent",
                  table_name="execution_trace_events")
    op.drop_index("ix_execution_trace_events_run_iter",
                  table_name="execution_trace_events")
    op.drop_index("ix_execution_trace_events_run_seq",
                  table_name="execution_trace_events")
    op.drop_table("execution_trace_events")

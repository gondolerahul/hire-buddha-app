"""drop_v1_memory_tables

Revision ID: mem1a2b3c4d5
Revises: m0b1e0d1a200
Create Date: 2026-09-28

Retires v1 memory storage. Episodes live in per-entity Episodic Trees and
uploaded documents in Knowledge Trees (cortex_trees / cortex_nodes), so the
flat ``episodic_memories`` table and the ``document_chunks`` RAG table have no
readers or writers left.

Existing rows are dropped, not migrated: copy anything you need out of these
two tables before upgrading. ``downgrade`` recreates the empty tables.
"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'mem1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'm0b1e0d1a200'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_chunks")
    op.execute("DROP TABLE IF EXISTS episodic_memories")


def downgrade() -> None:
    op.create_table(
        "episodic_memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_id", UUID(as_uuid=True), sa.ForeignKey("hierarchical_entities.id"), nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("execution_runs.id"), nullable=True),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("total_cost_usd", sa.String(20), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("metadata_info", sa.JSON(), nullable=True),
        sa.Column("channel", sa.String(50), nullable=True),
        sa.Column("tree_id", UUID(as_uuid=True), sa.ForeignKey("cortex_trees.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_episodic_memories_entity_id", "episodic_memories", ["entity_id"])
    op.create_index("ix_episodic_memories_user_id", "episodic_memories", ["user_id"])

    op.create_table(
        "document_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("chunk_index", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(768), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

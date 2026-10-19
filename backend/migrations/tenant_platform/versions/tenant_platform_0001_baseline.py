"""Tenant platform baseline: a tenant's tables as the old chain left them (Phase 14 WS2 2.7).

The old chain's 101 revisions squashed, for the tenant plane: every table of
``bases.TENANT`` as ``alembic upgrade head`` built it at ``p14_run_settlement``
(columns, server defaults, indexes, check and unique constraints, foreign keys,
the CORTEX enum types) and the ``kpi_daily_rollup`` view. Rendered by Alembic's
autogenerate from a database that chain built, so a database stamped at the cut
and one built from here are the same; the models match it (``alembic check``,
``tests/integration/test_migration_trees.py``) except where ``migrations/envlib.py``
says why.

Names are unqualified: ``env.py`` puts the target schema first on the
``search_path`` — ``platform`` in a tenant database, ``public`` in the shared
database of ``TENANCY_MODE=single``. Foreign keys come last, after every table
exists (two pairs of tables refer to each other).

Revision ID: tenant_platform_0001_baseline
Revises:
Create Date: 2026-10-19
"""
from typing import Sequence, Union

from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'tenant_platform_0001_baseline'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (name, table, referred table, columns, referred columns, ON DELETE)
FOREIGN_KEYS = [
    ('artifacts_agent_id_fkey', 'artifacts', 'hierarchical_entities', ['agent_id'], ['id'], None),
    ('artifacts_campaign_id_fkey', 'artifacts', 'campaigns', ['campaign_id'], ['id'], 'SET NULL'),
    ('artifacts_run_id_fkey', 'artifacts', 'execution_runs', ['run_id'], ['id'], None),
    ('call_content_call_log_id_fkey', 'call_content', 'call_logs', ['call_log_id'], ['id'], None),
    ('fk_call_content_audio_artifact', 'call_content', 'artifacts', ['audio_artifact_id'], ['id'], None),
    ('call_logs_agent_id_fkey', 'call_logs', 'hierarchical_entities', ['agent_id'], ['id'], None),
    ('campaign_assignees_campaign_id_fkey', 'campaign_assignees', 'campaigns', ['campaign_id'], ['id'], 'CASCADE'),
    ('campaign_calls_campaign_id_fkey', 'campaign_calls', 'campaigns', ['campaign_id'], ['id'], None),
    ('campaign_calls_voice_session_id_fkey', 'campaign_calls', 'voice_sessions', ['voice_session_id'], ['id'], None),
    ('campaigns_agent_id_fkey', 'campaigns', 'hierarchical_entities', ['agent_id'], ['id'], None),
    ('conversation_history_agent_id_fkey', 'conversation_history', 'hierarchical_entities', ['agent_id'], ['id'], None),
    ('cortex_edges_source_node_id_fkey', 'cortex_edges', 'cortex_nodes', ['source_node_id'], ['id'], 'CASCADE'),
    ('cortex_edges_target_node_id_fkey', 'cortex_edges', 'cortex_nodes', ['target_node_id'], ['id'], 'CASCADE'),
    ('cortex_nodes_execution_run_id_fkey', 'cortex_nodes', 'execution_runs', ['execution_run_id'], ['id'], None),
    ('cortex_nodes_parent_id_fkey', 'cortex_nodes', 'cortex_nodes', ['parent_id'], ['id'], 'SET NULL'),
    ('cortex_nodes_tree_id_fkey', 'cortex_nodes', 'cortex_trees', ['tree_id'], ['id'], 'CASCADE'),
    ('cortex_trees_entity_id_fkey', 'cortex_trees', 'hierarchical_entities', ['entity_id'], ['id'], None),
    ('fk_cortex_trees_output_root', 'cortex_trees', 'cortex_nodes', ['output_root_id'], ['id'], 'SET NULL'),
    ('fk_cortex_trees_resume_cursor', 'cortex_trees', 'cortex_nodes', ['resume_cursor_id'], ['id'], 'SET NULL'),
    ('fk_cortex_trees_root_node', 'cortex_trees', 'cortex_nodes', ['root_node_id'], ['id'], 'SET NULL'),
    ('fk_cortex_trees_run_id', 'cortex_trees', 'execution_runs', ['run_id'], ['id'], 'SET NULL'),
    ('documents_entity_id_fkey', 'documents', 'hierarchical_entities', ['entity_id'], ['id'], None),
    ('entity_assets_entity_version_id_fkey', 'entity_assets', 'entity_versions', ['entity_version_id'], ['id'], 'CASCADE'),
    ('entity_versions_entity_id_fkey', 'entity_versions', 'hierarchical_entities', ['entity_id'], ['id'], None),
    ('execution_runs_entity_id_fkey', 'execution_runs', 'hierarchical_entities', ['entity_id'], ['id'], None),
    ('execution_runs_entity_version_id_fkey', 'execution_runs', 'entity_versions', ['entity_version_id'], ['id'], None),
    ('execution_runs_parent_run_id_fkey', 'execution_runs', 'execution_runs', ['parent_run_id'], ['id'], None),
    ('execution_runs_retry_of_run_id_fkey', 'execution_runs', 'execution_runs', ['retry_of_run_id'], ['id'], None),
    ('execution_trace_events_run_id_fkey', 'execution_trace_events', 'execution_runs', ['run_id'], ['id'], 'CASCADE'),
    ('fk_execution_trace_events_run_company', 'execution_trace_events', 'execution_runs', ['run_id', 'company_id'], ['id', 'company_id'], 'CASCADE'),
    ('fk_entities_template_source', 'hierarchical_entities', 'hierarchical_entities', ['template_source_id'], ['id'], 'SET NULL'),
    ('fk_hierarchical_entities_active_version', 'hierarchical_entities', 'entity_versions', ['active_version_id'], ['id'], None),
    ('hierarchical_entities_parent_id_fkey', 'hierarchical_entities', 'hierarchical_entities', ['parent_id'], ['id'], None),
    ('fk_human_approvals_run_company', 'human_approvals', 'execution_runs', ['run_id', 'company_id'], ['id', 'company_id'], None),
    ('lead_queue_agent_id_fkey', 'lead_queue', 'hierarchical_entities', ['agent_id'], ['id'], None),
    ('lead_queue_voice_session_id_fkey', 'lead_queue', 'voice_sessions', ['voice_session_id'], ['id'], None),
    ('fk_llm_interaction_logs_run_company', 'llm_interaction_logs', 'execution_runs', ['run_id', 'company_id'], ['id', 'company_id'], None),
    ('mobile_call_attempts_agent_id_fkey', 'mobile_call_attempts', 'hierarchical_entities', ['agent_id'], ['id'], None),
    ('mobile_call_attempts_campaign_call_id_fkey', 'mobile_call_attempts', 'campaign_calls', ['campaign_call_id'], ['id'], None),
    ('mobile_call_attempts_campaign_id_fkey', 'mobile_call_attempts', 'campaigns', ['campaign_id'], ['id'], None),
    ('mobile_call_attempts_run_id_fkey', 'mobile_call_attempts', 'mobile_campaign_runs', ['run_id'], ['id'], None),
    ('mobile_call_attempts_voice_session_id_fkey', 'mobile_call_attempts', 'voice_sessions', ['voice_session_id'], ['id'], None),
    ('mobile_call_events_attempt_id_fkey', 'mobile_call_events', 'mobile_call_attempts', ['attempt_id'], ['id'], 'CASCADE'),
    ('mobile_campaign_runs_campaign_id_fkey', 'mobile_campaign_runs', 'campaigns', ['campaign_id'], ['id'], None),
    ('fk_run_subjects_run_company', 'run_subjects', 'execution_runs', ['run_id', 'company_id'], ['id', 'company_id'], 'CASCADE'),
    ('fk_tool_interaction_logs_run_company', 'tool_interaction_logs', 'execution_runs', ['run_id', 'company_id'], ['id', 'company_id'], None),
    ('trigger_firings_event_id_fkey', 'trigger_firings', 'events', ['event_id'], ['id'], None),
    ('trigger_firings_trigger_id_fkey', 'trigger_firings', 'triggers', ['trigger_id'], ['id'], 'CASCADE'),
    ('triggers_entity_id_fkey', 'triggers', 'hierarchical_entities', ['entity_id'], ['id'], 'CASCADE'),
    ('voice_sessions_agent_id_fkey', 'voice_sessions', 'hierarchical_entities', ['agent_id'], ['id'], None),
    ('whatsapp_sessions_agent_id_fkey', 'whatsapp_sessions', 'hierarchical_entities', ['agent_id'], ['id'], None),
]
ENUM_TYPES = ('cortex_node_status', 'cortex_node_type', 'cortex_tree_status', 'memory_domain', 'scope_level')

# The view as the old chain left it (``migrations/kpi_rollup_view.py``
# ``CREATE_VIEW_UTC``): days bucketed in UTC. A revision that changes a column
# it reads wraps the change in ``kpi_rollup_view.rebuilt``.
KPI_DAILY_ROLLUP = """
CREATE MATERIALIZED VIEW kpi_daily_rollup AS
SELECT
    date_trunc('day', er.completed_at AT TIME ZONE 'UTC') AS day,
    er.company_id,
    COALESCE(
        (e.tags::jsonb)->>0,
        'untagged'
    ) AS primary_tag,
    COUNT(*) AS runs_total,
    SUM(CASE WHEN er.status = 'COMPLETED' THEN 1 ELSE 0 END) AS runs_completed,
    SUM(CASE WHEN er.status = 'FAILED'    THEN 1 ELSE 0 END) AS runs_failed,
    SUM(CASE WHEN er.status = 'PAUSED'    THEN 1 ELSE 0 END) AS runs_paused,
    COALESCE(SUM(er.total_cost_usd), 0)::numeric(18, 6) AS cost_usd,
    COALESCE(SUM(er.total_tokens), 0) AS tokens
FROM execution_runs er
JOIN hierarchical_entities e ON e.id = er.entity_id
WHERE er.completed_at IS NOT NULL
GROUP BY 1, 2, 3
"""
KPI_DAILY_ROLLUP_INDEX = "CREATE UNIQUE INDEX kpi_daily_rollup_uniq ON kpi_daily_rollup(day, company_id, primary_tag)"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.create_table('api_keys',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.TEXT(), nullable=False),
    sa.Column('prefix', sa.TEXT(), nullable=False),
    sa.Column('key_hash', sa.TEXT(), nullable=False),
    sa.Column('scopes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('external', sa.BOOLEAN(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_by', sa.TEXT(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('revoked_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name='api_keys_pkey'),
    sa.UniqueConstraint('key_hash', name='uq_api_keys_hash')
    )
    op.create_table('audit_log',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('actor', sa.TEXT(), nullable=False),
    sa.Column('action', sa.TEXT(), nullable=False),
    sa.Column('object', sa.TEXT(), nullable=False),
    sa.Column('record_id', sa.UUID(), nullable=False),
    sa.Column('changed_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name='audit_log_pkey')
    )
    op.create_index('ix_audit_log_record', 'audit_log', ['object', 'record_id', 'at'], unique=False)
    op.create_table('contact_uploads',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('uploaded_by', sa.UUID(), nullable=False),
    sa.Column('filename', sa.VARCHAR(length=255), nullable=False),
    sa.Column('file_type', sa.VARCHAR(length=10), nullable=False),
    sa.Column('total_rows', sa.INTEGER(), nullable=False),
    sa.Column('valid_rows', sa.INTEGER(), nullable=False),
    sa.Column('invalid_rows', sa.INTEGER(), nullable=False),
    sa.Column('duplicate_rows', sa.INTEGER(), nullable=False),
    sa.Column('columns', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('phone_column', sa.VARCHAR(length=255), nullable=True),
    sa.Column('valid_contacts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('errors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('consumed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('expires_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name='contact_uploads_pkey')
    )
    op.create_index('ix_contact_uploads_company_id', 'contact_uploads', ['company_id'], unique=False)
    op.create_table('cortex_nodes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tree_id', sa.UUID(), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('node_type', postgresql.ENUM('root', 'knowledge', 'finding', 'task', 'output', 'checkpoint', 'group', 'document', 'section', 'chunk', 'observation', 'pattern', 'suggestion', 'instruction', 'strategy', 'preference', 'episode', 'episode_group', 'snapshot', 'health_record', 'health_root', name='cortex_node_type'), nullable=False),
    sa.Column('title', sa.VARCHAR(length=500), nullable=False),
    sa.Column('summary', sa.TEXT(), nullable=True),
    sa.Column('content', sa.TEXT(), nullable=True),
    sa.Column('content_tokens', sa.INTEGER(), server_default=sa.text('0'), nullable=True),
    sa.Column('status', postgresql.ENUM('pending', 'active', 'complete', 'summarised', name='cortex_node_status'), server_default=sa.text("'pending'::cortex_node_status"), nullable=False),
    sa.Column('source_ref', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('execution_run_id', sa.UUID(), nullable=True),
    sa.Column('depth', sa.INTEGER(), server_default=sa.text('0'), nullable=True),
    sa.Column('sibling_order', sa.INTEGER(), server_default=sa.text('0'), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
    sa.Column('metadata_extra', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('embedding', Vector(dim=768), nullable=True),
    sa.Column('embedding_model', sa.VARCHAR(length=100), nullable=True),
    sa.Column('cross_refs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('access_count', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('last_accessed_at', postgresql.TIMESTAMP(), nullable=True),
    sa.Column('importance_score', sa.NUMERIC(precision=5, scale=3), server_default=sa.text('0.500'), nullable=False),
    sa.PrimaryKeyConstraint('id', name='cortex_nodes_pkey')
    )
    op.create_index('ix_cortex_nodes_created_at', 'cortex_nodes', ['created_at'], unique=False)
    op.create_index('ix_cortex_nodes_embedding', 'cortex_nodes', ['embedding'], unique=False, postgresql_ops={'embedding': 'vector_cosine_ops'}, postgresql_with={'m': '16', 'ef_construction': '64'}, postgresql_using='hnsw')
    op.create_index('ix_cortex_nodes_importance', 'cortex_nodes', [sa.literal_column('importance_score DESC')], unique=False)
    op.create_index('ix_cortex_nodes_parent_id', 'cortex_nodes', ['parent_id'], unique=False)
    op.create_index('ix_cortex_nodes_status', 'cortex_nodes', ['status'], unique=False)
    op.create_index('ix_cortex_nodes_tree_id', 'cortex_nodes', ['tree_id'], unique=False)
    op.create_index('ix_cortex_nodes_tree_parent', 'cortex_nodes', ['tree_id', 'parent_id'], unique=False)
    op.create_index('ix_cortex_nodes_tree_type', 'cortex_nodes', ['tree_id', 'node_type'], unique=False)
    op.create_index('ix_cortex_nodes_tree_type_status', 'cortex_nodes', ['tree_id', 'node_type', 'status'], unique=False)
    op.create_table('cortex_trees',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('entity_id', sa.UUID(), nullable=True),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('task_description', sa.TEXT(), nullable=True),
    sa.Column('status', postgresql.ENUM('active', 'suspended', 'complete', 'archived', name='cortex_tree_status'), server_default=sa.text("'active'::cortex_tree_status"), nullable=False),
    sa.Column('total_nodes', sa.INTEGER(), server_default=sa.text('0'), nullable=True),
    sa.Column('root_node_id', sa.UUID(), nullable=True),
    sa.Column('output_root_id', sa.UUID(), nullable=True),
    sa.Column('resume_cursor_id', sa.UUID(), nullable=True),
    sa.Column('max_children', sa.INTEGER(), server_default=sa.text('12'), nullable=True),
    sa.Column('page_size_tokens', sa.INTEGER(), server_default=sa.text('8000'), nullable=True),
    sa.Column('context_budget_pct', sa.INTEGER(), server_default=sa.text('40'), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
    sa.Column('last_active_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
    sa.Column('resume_schedule', sa.VARCHAR(length=100), nullable=True),
    sa.Column('next_resume_at', postgresql.TIMESTAMP(), nullable=True),
    sa.Column('memory_domain', postgresql.ENUM('knowledge', 'experience', 'intelligence', 'episodic', name='memory_domain'), server_default=sa.text("'knowledge'::memory_domain"), nullable=False),
    sa.Column('scope_level', postgresql.ENUM('app', 'partner', 'tenant', 'user', 'entity', 'runtime', name='scope_level'), server_default=sa.text("'runtime'::scope_level"), nullable=False),
    sa.Column('app_id', sa.UUID(), nullable=True),
    sa.Column('partner_id', sa.UUID(), nullable=True),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('tree_category', sa.VARCHAR(length=100), nullable=True),
    sa.Column('expires_at', postgresql.TIMESTAMP(), nullable=True),
    sa.Column('is_persistent', sa.BOOLEAN(), server_default=sa.text('true'), nullable=False),
    sa.Column('last_consolidated_at', postgresql.TIMESTAMP(), nullable=True),
    sa.Column('consolidation_generation', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('source_run_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id', name='cortex_trees_pkey')
    )
    op.create_index('ix_cortex_trees_company_id', 'cortex_trees', ['company_id'], unique=False)
    op.create_index('ix_cortex_trees_domain_scope', 'cortex_trees', ['memory_domain', 'scope_level'], unique=False)
    op.create_index('ix_cortex_trees_entity_id', 'cortex_trees', ['entity_id'], unique=False)
    op.create_index('ix_cortex_trees_next_resume', 'cortex_trees', ['next_resume_at'], unique=False, postgresql_where='(next_resume_at IS NOT NULL)')
    op.create_index('ix_cortex_trees_scope_company', 'cortex_trees', ['scope_level', 'company_id'], unique=False)
    op.create_index('ix_cortex_trees_scope_entity', 'cortex_trees', ['scope_level', 'entity_id'], unique=False, postgresql_where='(entity_id IS NOT NULL)')
    op.create_index('ix_cortex_trees_scope_user', 'cortex_trees', ['scope_level', 'user_id'], unique=False, postgresql_where='(user_id IS NOT NULL)')
    op.create_index('ix_cortex_trees_status', 'cortex_trees', ['status'], unique=False)
    op.create_table('email_connections',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('email_address', sa.VARCHAR(), nullable=False),
    sa.Column('encrypted_app_password', sa.TEXT(), nullable=False),
    sa.Column('imap_host', sa.VARCHAR(), server_default=sa.text("'imap.gmail.com'::character varying"), nullable=False),
    sa.Column('imap_port', sa.INTEGER(), server_default=sa.text('993'), nullable=False),
    sa.Column('smtp_host', sa.VARCHAR(), server_default=sa.text("'smtp.gmail.com'::character varying"), nullable=False),
    sa.Column('smtp_port', sa.INTEGER(), server_default=sa.text('587'), nullable=False),
    sa.Column('provider_type', sa.VARCHAR(), server_default=sa.text("'gmail'::character varying"), nullable=False),
    sa.Column('folder_prefix', sa.VARCHAR(), nullable=True),
    sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), nullable=False),
    sa.Column('last_connected_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('status', sa.VARCHAR(), server_default=sa.text("'active'::character varying"), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id', name='email_connections_pkey'),
    sa.UniqueConstraint('company_id', 'email_address', name='uq_email_connection_company_email')
    )
    op.create_table('entity_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('entity_id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=True),
    sa.Column('version_number', sa.INTEGER(), nullable=False),
    sa.Column('label', sa.VARCHAR(), nullable=True),
    sa.Column('snapshot', postgresql.JSON(astext_type=sa.Text()), nullable=False),
    sa.Column('content_hash', sa.VARCHAR(length=64), nullable=False),
    sa.Column('published', sa.BOOLEAN(), server_default=sa.text('false'), nullable=False),
    sa.Column('published_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('published_by', sa.UUID(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name='entity_versions_pkey'),
    sa.UniqueConstraint('entity_id', 'version_number', name='uq_entity_versions_number')
    )
    op.create_index('ix_entity_versions_content', 'entity_versions', ['entity_id', 'content_hash'], unique=False)
    op.create_index('uq_entity_versions_published_content', 'entity_versions', ['entity_id', 'content_hash'], unique=True, postgresql_where='published')
    op.create_table('events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('type', sa.TEXT(), nullable=False),
    sa.Column('source', sa.TEXT(), nullable=False),
    sa.Column('subject', sa.TEXT(), nullable=True),
    sa.Column('time', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('received_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('dedupe_key', sa.TEXT(), nullable=False),
    sa.Column('trust', sa.TEXT(), nullable=False),
    sa.Column('causation_id', sa.UUID(), nullable=True),
    sa.Column('correlation_id', sa.UUID(), nullable=True),
    sa.Column('chain_depth', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('data_ref', sa.TEXT(), nullable=True),
    sa.Column('status', sa.TEXT(), server_default=sa.text("'received'::text"), nullable=False),
    sa.Column('attempts', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('last_error', sa.TEXT(), nullable=True),
    sa.Column('routed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.CheckConstraint("status = ANY (ARRAY['received'::text, 'routed'::text, 'parked'::text, 'dead'::text])", name='ck_events_status'),
    sa.CheckConstraint("trust = ANY (ARRAY['verified'::text, 'unverified'::text, 'internal'::text])", name='ck_events_trust'),
    sa.PrimaryKeyConstraint('id', name='events_pkey'),
    sa.UniqueConstraint('company_id', 'dedupe_key', name='uq_events_company_dedupe')
    )
    op.create_index('ix_events_pending', 'events', ['status', 'received_at'], unique=False, postgresql_where="(status = ANY (ARRAY['received'::text, 'parked'::text]))")
    op.create_index('ix_events_type_time', 'events', ['type', 'time'], unique=False)
    op.create_table('hierarchical_entities',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('type', sa.VARCHAR(), nullable=False),
    sa.Column('name', sa.VARCHAR(), nullable=False),
    sa.Column('description', sa.TEXT(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('version', sa.VARCHAR(), server_default=sa.text("'1.0.0'::character varying"), nullable=False),
    sa.Column('status', sa.VARCHAR(), server_default=sa.text("'ACTIVE'::character varying"), nullable=False),
    sa.Column('display_name', sa.VARCHAR(), nullable=True),
    sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('identity', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('hierarchy', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('logic_gate', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('planning', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('capabilities', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('governance', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('io_contract', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('observability', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('metadata_extensions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('goal', sa.TEXT(), nullable=True),
    sa.Column('is_template', sa.BOOLEAN(), server_default=sa.text('false'), nullable=False),
    sa.Column('template_source_id', sa.UUID(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('deleted_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('active_version_id', sa.UUID(), nullable=True),
    sa.CheckConstraint("type IN ('ACTION', 'SKILL', 'AGENT', 'PROCESS', 'LOOP', 'GRAPH')", name='ck_hierarchical_entities_type'),
    sa.PrimaryKeyConstraint('id', name='hierarchical_entities_pkey')
    )
    op.create_index('idx_entities_not_deleted', 'hierarchical_entities', ['company_id', 'type'], unique=False, postgresql_where="((status)::text <> 'DELETED'::text)")
    op.create_index('ix_hierarchical_entities_is_template', 'hierarchical_entities', ['is_template'], unique=False)
    op.create_table('mobile_client_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('device_id', sa.UUID(), nullable=True),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('attempt_id', sa.UUID(), nullable=True),
    sa.Column('seq', sa.INTEGER(), nullable=False),
    sa.Column('level', sa.VARCHAR(length=10), nullable=False),
    sa.Column('tag', sa.VARCHAR(length=64), nullable=False),
    sa.Column('message', sa.TEXT(), nullable=False),
    sa.Column('fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('app_version', sa.VARCHAR(length=50), nullable=True),
    sa.Column('device_ts', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('received_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name='mobile_client_logs_pkey')
    )
    op.create_index('ix_mobile_client_logs_attempt_id', 'mobile_client_logs', ['attempt_id'], unique=False)
    op.create_index('ix_mobile_client_logs_company_id', 'mobile_client_logs', ['company_id'], unique=False)
    op.create_index('ix_mobile_logs_company_time', 'mobile_client_logs', ['company_id', 'received_at'], unique=False)
    op.create_index('ix_mobile_logs_device_time', 'mobile_client_logs', ['device_id', 'received_at'], unique=False)
    op.create_table('records_settings',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('agents_auto_approve_additive', sa.BOOLEAN(), server_default=sa.text('false'), nullable=False),
    sa.Column('updated_by', sa.TEXT(), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('company_id', name='records_settings_pkey')
    )
    op.create_table('schema_blueprints',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.INTEGER(), nullable=False),
    sa.Column('status', sa.TEXT(), nullable=False),
    sa.Column('document', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('change_id', sa.UUID(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status = ANY (ARRAY['active'::text, 'superseded'::text])", name='ck_schema_blueprints_status'),
    sa.PrimaryKeyConstraint('id', name='schema_blueprints_pkey'),
    sa.UniqueConstraint('company_id', 'version', name='uq_schema_blueprints_company_version')
    )
    op.create_index('uq_schema_blueprints_active', 'schema_blueprints', ['company_id'], unique=True, postgresql_where="(status = 'active'::text)")
    op.create_table('schema_changes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.TEXT(), nullable=False),
    sa.Column('operations', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('reason', sa.TEXT(), nullable=True),
    sa.Column('actor_kind', sa.TEXT(), nullable=False),
    sa.Column('actor_id', sa.TEXT(), nullable=True),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('base_version', sa.INTEGER(), nullable=False),
    sa.Column('result_version', sa.INTEGER(), nullable=True),
    sa.Column('plan', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('impact', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.TEXT(), nullable=True),
    sa.Column('decided_by', sa.TEXT(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('decided_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('applied_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.CheckConstraint("actor_kind = ANY (ARRAY['user'::text, 'agent'::text, 'platform'::text, 'key'::text])", name='ck_schema_changes_actor'),
    sa.CheckConstraint("status = ANY (ARRAY['proposed'::text, 'awaiting_approval'::text, 'applied'::text, 'rejected'::text, 'failed'::text])", name='ck_schema_changes_status'),
    sa.PrimaryKeyConstraint('id', name='schema_changes_pkey')
    )
    op.create_index('ix_schema_changes_company_created', 'schema_changes', ['company_id', 'created_at'], unique=False)
    op.create_table('social_connections',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('platform', sa.VARCHAR(length=50), nullable=False),
    sa.Column('account_name', sa.VARCHAR(length=255), nullable=True),
    sa.Column('encrypted_access_token', sa.TEXT(), nullable=False),
    sa.Column('encrypted_refresh_token', sa.TEXT(), nullable=True),
    sa.Column('token_expires_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('platform_user_id', sa.VARCHAR(length=255), nullable=True),
    sa.Column('platform_page_id', sa.VARCHAR(length=255), nullable=True),
    sa.Column('scopes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::json"), nullable=True),
    sa.Column('oauth_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), nullable=False),
    sa.Column('status', sa.VARCHAR(length=50), server_default=sa.text("'active'::character varying"), nullable=False),
    sa.Column('last_used_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id', name='social_connections_pkey'),
    sa.UniqueConstraint('company_id', 'platform', 'platform_user_id', name='uq_social_connection_company_platform_user')
    )
    op.create_index('ix_social_connections_company_platform', 'social_connections', ['company_id', 'platform'], unique=False)
    op.create_table('waits',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('step_ref', sa.TEXT(), nullable=False),
    sa.Column('event_type', sa.TEXT(), nullable=True),
    sa.Column('match', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('deadline_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('status', sa.TEXT(), server_default=sa.text("'waiting'::text"), nullable=False),
    sa.Column('satisfied_by_event_id', sa.UUID(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status = ANY (ARRAY['waiting'::text, 'satisfied'::text, 'expired'::text, 'cancelled'::text])", name='ck_waits_status'),
    sa.PrimaryKeyConstraint('id', name='waits_pkey')
    )
    op.create_index('ix_waits_run', 'waits', ['run_id'], unique=False)
    op.create_index('ix_waits_waiting_type', 'waits', ['event_type'], unique=False, postgresql_where="(status = 'waiting'::text)")
    op.create_table('call_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('voice_session_id', sa.UUID(), nullable=True),
    sa.Column('agent_id', sa.UUID(), nullable=True),
    sa.Column('direction', sa.VARCHAR(length=20), nullable=True),
    sa.Column('status', sa.VARCHAR(length=30), nullable=True),
    sa.Column('duration_seconds', sa.INTEGER(), nullable=True),
    sa.Column('from_number', sa.VARCHAR(length=30), nullable=True),
    sa.Column('to_number', sa.VARCHAR(length=30), nullable=True),
    sa.Column('provider', sa.VARCHAR(length=30), nullable=True),
    sa.Column('call_cost_usd', sa.NUMERIC(precision=10, scale=6), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name='call_logs_pkey')
    )
    op.create_index('idx_call_logs_agent', 'call_logs', ['agent_id'], unique=False)
    op.create_index('idx_call_logs_company', 'call_logs', ['company_id'], unique=False)
    op.create_index('idx_call_logs_created_at', 'call_logs', ['created_at'], unique=False)
    op.create_table('campaigns',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.VARCHAR(length=255), nullable=False),
    sa.Column('description', sa.TEXT(), nullable=True),
    sa.Column('total_contacts', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('contact_list', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('provider', sa.VARCHAR(length=20), server_default=sa.text("'twilio'::character varying"), nullable=False),
    sa.Column('call_script_template', sa.TEXT(), nullable=True),
    sa.Column('scheduled_start', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('scheduled_end', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('max_concurrent_calls', sa.INTEGER(), server_default=sa.text('5'), nullable=False),
    sa.Column('max_calls_per_hour', sa.INTEGER(), nullable=True),
    sa.Column('status', sa.VARCHAR(length=20), server_default=sa.text("'draft'::character varying"), nullable=False),
    sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('calls_initiated', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('calls_completed', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('calls_failed', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('outcome_distribution', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('campaign_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('execution_mode', sa.VARCHAR(length=30), server_default=sa.text("'server_dialer'::character varying"), nullable=False),
    sa.Column('contact_upload_id', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name='campaigns_pkey')
    )
    op.create_index('idx_campaigns_agent', 'campaigns', ['agent_id'], unique=False)
    op.create_index('idx_campaigns_company', 'campaigns', ['company_id'], unique=False)
    op.create_index('idx_campaigns_created_by', 'campaigns', ['created_by'], unique=False)
    op.create_index('idx_campaigns_status', 'campaigns', ['status'], unique=False)
    op.create_table('conversation_history',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('channel', sa.VARCHAR(length=20), nullable=False),
    sa.Column('turn_number', sa.INTEGER(), nullable=False),
    sa.Column('speaker', sa.VARCHAR(length=20), nullable=False),
    sa.Column('message_type', sa.VARCHAR(length=20), nullable=True),
    sa.Column('content', sa.TEXT(), nullable=True),
    sa.Column('audio_duration_ms', sa.INTEGER(), nullable=True),
    sa.Column('timestamp', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('message_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id', name='conversation_history_pkey')
    )
    op.create_index('idx_conversation_company', 'conversation_history', ['company_id'], unique=False)
    op.create_index('idx_conversation_customer_agent', 'conversation_history', ['customer_id', 'agent_id', sa.literal_column('"timestamp" DESC')], unique=False)
    op.create_index('idx_conversation_session', 'conversation_history', ['session_id'], unique=False)
    op.create_table('cortex_edges',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('source_node_id', sa.UUID(), nullable=False),
    sa.Column('target_node_id', sa.UUID(), nullable=False),
    sa.Column('edge_type', sa.VARCHAR(length=50), nullable=False),
    sa.Column('weight', sa.NUMERIC(precision=5, scale=4), server_default=sa.text('0.5000'), nullable=True),
    sa.Column('traversal_count', sa.INTEGER(), server_default=sa.text('0'), nullable=True),
    sa.Column('last_traversed_at', postgresql.TIMESTAMP(), nullable=True),
    sa.Column('created_by', sa.VARCHAR(length=50), nullable=True),
    sa.Column('edge_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id', name='cortex_edges_pkey'),
    sa.UniqueConstraint('source_node_id', 'target_node_id', 'edge_type', name='uq_cortex_edges_src_tgt_type')
    )
    op.create_index('ix_cortex_edges_source', 'cortex_edges', ['source_node_id'], unique=False)
    op.create_index('ix_cortex_edges_target', 'cortex_edges', ['target_node_id'], unique=False)
    op.create_index('ix_cortex_edges_type_weight', 'cortex_edges', ['edge_type', sa.literal_column('weight DESC')], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('filename', sa.VARCHAR(), nullable=False),
    sa.Column('file_type', sa.VARCHAR(), nullable=False),
    sa.Column('file_size', sa.BIGINT(), nullable=True),
    sa.Column('upload_status', sa.VARCHAR(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('entity_id', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name='documents_pkey')
    )
    op.create_table('entity_assets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('entity_version_id', sa.UUID(), nullable=False),
    sa.Column('path', sa.VARCHAR(), nullable=False),
    sa.Column('content_hash', sa.VARCHAR(length=64), nullable=False),
    sa.Column('language', sa.VARCHAR(), nullable=True),
    sa.Column('body', sa.TEXT(), nullable=False),
    sa.Column('size_bytes', sa.INTEGER(), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name='entity_assets_pkey'),
    sa.UniqueConstraint('entity_version_id', 'path', name='uq_entity_assets_path')
    )
    op.create_index('ix_entity_assets_version', 'entity_assets', ['entity_version_id'], unique=False)
    op.create_table('execution_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('entity_id', sa.UUID(), nullable=False),
    sa.Column('parent_run_id', sa.UUID(), nullable=True),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.VARCHAR(), nullable=True),
    sa.Column('input_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('dynamic_plan', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('result_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('context_state', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('error_message', sa.TEXT(), nullable=True),
    sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('total_cost_usd', sa.NUMERIC(precision=10, scale=4), nullable=True),
    sa.Column('total_tokens', sa.INTEGER(), nullable=True),
    sa.Column('execution_time_ms', sa.INTEGER(), nullable=True),
    sa.Column('trace_id', sa.UUID(), nullable=True),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('csat_score', sa.INTEGER(), nullable=True),
    sa.Column('csat_comment', sa.TEXT(), nullable=True),
    sa.Column('billed_amount', sa.NUMERIC(precision=14, scale=6), nullable=True),
    sa.Column('retry_of_run_id', sa.UUID(), nullable=True),
    sa.Column('depth', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('max_depth', sa.INTEGER(), nullable=True),
    sa.Column('entity_version_id', sa.UUID(), nullable=True),
    sa.Column('trigger_id', sa.UUID(), nullable=True),
    sa.Column('event_id', sa.UUID(), nullable=True),
    sa.Column('correlation_id', sa.UUID(), nullable=True),
    sa.Column('chain_depth', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.PrimaryKeyConstraint('id', name='execution_runs_pkey'),
    sa.UniqueConstraint('id', 'company_id', name='uq_execution_runs_id_company')
    )
    op.create_index('ix_execution_runs_company_created', 'execution_runs', ['company_id', 'created_at'], unique=False)
    op.create_index('ix_execution_runs_entity_created', 'execution_runs', ['entity_id', 'created_at'], unique=False)
    op.create_index('ix_execution_runs_entity_version_id', 'execution_runs', ['entity_version_id'], unique=False)
    op.create_index('ix_execution_runs_parent_run_id', 'execution_runs', ['parent_run_id'], unique=False)
    op.create_index('ix_execution_runs_retry_of_run_id', 'execution_runs', ['retry_of_run_id'], unique=False)
    op.create_index('ix_execution_runs_trigger_id', 'execution_runs', ['trigger_id'], unique=False)
    op.create_table('triggers',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.TEXT(), nullable=False),
    sa.Column('kind', sa.TEXT(), nullable=False),
    sa.Column('enabled', sa.BOOLEAN(), server_default=sa.text('true'), nullable=False),
    sa.Column('entity_id', sa.UUID(), nullable=False),
    sa.Column('entity_version_id', sa.UUID(), nullable=True),
    sa.Column('input_template', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('event_type', sa.TEXT(), nullable=True),
    sa.Column('filter', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('cron', sa.TEXT(), nullable=True),
    sa.Column('timezone', sa.TEXT(), nullable=True),
    sa.Column('run_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('until_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('max_firings', sa.INTEGER(), nullable=True),
    sa.Column('catch_up', sa.TEXT(), nullable=True),
    sa.Column('overlap', sa.TEXT(), nullable=True),
    sa.Column('max_concurrency', sa.INTEGER(), nullable=True),
    sa.Column('rate_per_hour', sa.INTEGER(), nullable=True),
    sa.Column('condition', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('scope', sa.TEXT(), nullable=True),
    sa.Column('created_by_kind', sa.TEXT(), nullable=False),
    sa.Column('created_by_id', sa.UUID(), nullable=True),
    sa.Column('created_by_run_id', sa.UUID(), nullable=True),
    sa.Column('next_fire_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('last_fired_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('firings', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('paused_reason', sa.TEXT(), nullable=True),
    sa.Column('version', sa.INTEGER(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("catch_up IS NULL OR (catch_up = ANY (ARRAY['skip'::text, 'once'::text, 'all'::text]))", name='ck_triggers_catch_up'),
    sa.CheckConstraint("created_by_kind = ANY (ARRAY['user'::text, 'agent'::text, 'system'::text])", name='ck_triggers_created_by_kind'),
    sa.CheckConstraint("kind = ANY (ARRAY['schedule'::text, 'timer'::text, 'event'::text, 'data'::text, 'condition'::text, 'manual'::text])", name='ck_triggers_kind'),
    sa.CheckConstraint("overlap IS NULL OR (overlap = ANY (ARRAY['skip'::text, 'queue'::text, 'allow'::text]))", name='ck_triggers_overlap'),
    sa.PrimaryKeyConstraint('id', name='triggers_pkey')
    )
    op.create_index('ix_triggers_entity_id', 'triggers', ['entity_id'], unique=False)
    op.create_index('ix_triggers_event_type', 'triggers', ['event_type'], unique=False, postgresql_where='enabled')
    op.create_table('voice_sessions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('phone_number', sa.VARCHAR(length=20), nullable=False),
    sa.Column('provider', sa.VARCHAR(length=20), nullable=False),
    sa.Column('call_sid', sa.VARCHAR(length=100), nullable=False),
    sa.Column('stream_sid', sa.VARCHAR(length=100), nullable=True),
    sa.Column('direction', sa.VARCHAR(length=20), nullable=True),
    sa.Column('status', sa.VARCHAR(length=20), server_default=sa.text("'initiated'::character varying"), nullable=False),
    sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ended_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('duration_seconds', sa.INTEGER(), nullable=True),
    sa.Column('total_cost_usd', sa.NUMERIC(precision=10, scale=4), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('context_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('conversation_log', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('session_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name='voice_sessions_pkey'),
    sa.UniqueConstraint('call_sid', name='voice_sessions_call_sid_key')
    )
    op.create_index('idx_voice_sessions_agent', 'voice_sessions', ['agent_id'], unique=False)
    op.create_index('idx_voice_sessions_call_sid', 'voice_sessions', ['call_sid'], unique=False)
    op.create_index('idx_voice_sessions_company', 'voice_sessions', ['company_id'], unique=False)
    op.create_index('idx_voice_sessions_customer', 'voice_sessions', ['customer_id'], unique=False)
    op.create_index('idx_voice_sessions_status', 'voice_sessions', ['status'], unique=False)
    op.create_table('whatsapp_sessions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('phone_number', sa.VARCHAR(length=20), nullable=False),
    sa.Column('provider', sa.VARCHAR(length=20), nullable=False),
    sa.Column('conversation_id', sa.VARCHAR(length=100), nullable=False),
    sa.Column('status', sa.VARCHAR(length=20), server_default=sa.text("'active'::character varying"), nullable=False),
    sa.Column('session_window_expires', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_message_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('message_count', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('total_cost_usd', sa.NUMERIC(precision=10, scale=4), server_default=sa.text("'0'::numeric"), nullable=False),
    sa.Column('conversation_log', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('session_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name='whatsapp_sessions_pkey'),
    sa.UniqueConstraint('conversation_id', name='whatsapp_sessions_conversation_id_key')
    )
    op.create_index('idx_whatsapp_sessions_agent', 'whatsapp_sessions', ['agent_id'], unique=False)
    op.create_index('idx_whatsapp_sessions_company', 'whatsapp_sessions', ['company_id'], unique=False)
    op.create_index('idx_whatsapp_sessions_conversation', 'whatsapp_sessions', ['conversation_id'], unique=False)
    op.create_index('idx_whatsapp_sessions_customer', 'whatsapp_sessions', ['customer_id'], unique=False)
    op.create_table('artifacts',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('campaign_id', sa.UUID(), nullable=True),
    sa.Column('agent_id', sa.UUID(), nullable=True),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('origin', sa.VARCHAR(length=30), server_default=sa.text("'system-generated'::character varying"), nullable=False),
    sa.Column('file_category', sa.VARCHAR(length=50), server_default=sa.text("'documents'::character varying"), nullable=False),
    sa.Column('file_name', sa.VARCHAR(length=500), nullable=False),
    sa.Column('file_path', sa.TEXT(), nullable=False),
    sa.Column('file_size', sa.BIGINT(), nullable=True),
    sa.Column('duration_seconds', sa.INTEGER(), nullable=True),
    sa.Column('mime_type', sa.VARCHAR(length=100), nullable=True),
    sa.Column('purpose', sa.TEXT(), nullable=True),
    sa.Column('generated_by', sa.VARCHAR(length=200), nullable=True),
    sa.Column('artifact_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('storage_key', sa.TEXT(), nullable=True),
    sa.PrimaryKeyConstraint('id', name='artifacts_pkey')
    )
    op.create_index('idx_artifacts_agent', 'artifacts', ['agent_id'], unique=False)
    op.create_index('idx_artifacts_campaign', 'artifacts', ['campaign_id'], unique=False)
    op.create_index('idx_artifacts_company', 'artifacts', ['company_id'], unique=False)
    op.create_index('idx_artifacts_created_at', 'artifacts', ['created_at'], unique=False)
    op.create_index('idx_artifacts_file_category', 'artifacts', ['file_category'], unique=False)
    op.create_index('idx_artifacts_origin', 'artifacts', ['origin'], unique=False)
    op.create_table('campaign_assignees',
    sa.Column('campaign_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('assigned_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('campaign_id', 'user_id', name='campaign_assignees_pkey')
    )
    op.create_index('ix_campaign_assignees_user_id', 'campaign_assignees', ['user_id'], unique=False)
    op.create_table('campaign_calls',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('campaign_id', sa.UUID(), nullable=False),
    sa.Column('voice_session_id', sa.UUID(), nullable=True),
    sa.Column('contact_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.VARCHAR(length=20), server_default=sa.text("'pending'::character varying"), nullable=False),
    sa.Column('call_sid', sa.VARCHAR(length=100), nullable=True),
    sa.Column('outcome', sa.VARCHAR(length=50), nullable=True),
    sa.Column('outcome_notes', sa.TEXT(), nullable=True),
    sa.Column('scheduled_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('called_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('duration_seconds', sa.INTEGER(), nullable=True),
    sa.Column('retry_count', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('max_retries', sa.INTEGER(), server_default=sa.text('2'), nullable=False),
    sa.Column('call_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('disposition', sa.VARCHAR(length=30), nullable=True),
    sa.Column('disposition_reason', sa.VARCHAR(length=30), nullable=True),
    sa.Column('leased_by_user_id', sa.UUID(), nullable=True),
    sa.Column('leased_by_device_id', sa.UUID(), nullable=True),
    sa.Column('lease_expires_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('rep_disposition', sa.VARCHAR(length=30), nullable=True),
    sa.Column('rep_note', sa.TEXT(), nullable=True),
    sa.Column('rep_dispositioned_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('rep_dispositioned_by', sa.UUID(), nullable=True),
    sa.Column('disposition_source', sa.VARCHAR(length=10), nullable=True),
    sa.Column('callback_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name='campaign_calls_pkey')
    )
    op.create_index('idx_campaign_calls_campaign', 'campaign_calls', ['campaign_id'], unique=False)
    op.create_index('idx_campaign_calls_disposition', 'campaign_calls', ['disposition'], unique=False)
    op.create_index('idx_campaign_calls_status', 'campaign_calls', ['status'], unique=False)
    op.create_index('idx_campaign_calls_voice_session', 'campaign_calls', ['voice_session_id'], unique=False)
    op.create_index('ix_campaign_calls_lease', 'campaign_calls', ['campaign_id', 'status', 'lease_expires_at'], unique=False)
    op.create_table('execution_trace_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=True),
    sa.Column('span_id', sa.UUID(), nullable=False),
    sa.Column('parent_span_id', sa.UUID(), nullable=True),
    sa.Column('iteration', sa.INTEGER(), nullable=True),
    sa.Column('kind', sa.VARCHAR(length=16), nullable=False),
    sa.Column('name', sa.VARCHAR(length=512), nullable=True),
    sa.Column('status', sa.VARCHAR(length=16), server_default=sa.text("'running'::character varying"), nullable=False),
    sa.Column('seq', sa.BIGINT(), server_default=sa.text("'0'::bigint"), nullable=False),
    sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('ended_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('duration_ms', sa.INTEGER(), nullable=True),
    sa.Column('cost_usd', sa.NUMERIC(precision=12, scale=6), nullable=True),
    sa.Column('tokens_in', sa.INTEGER(), nullable=True),
    sa.Column('tokens_out', sa.INTEGER(), nullable=True),
    sa.Column('child_run_id', sa.UUID(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error_message', sa.TEXT(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name='execution_trace_events_pkey')
    )
    op.create_index('ix_execution_trace_events_run_iter', 'execution_trace_events', ['run_id', 'iteration'], unique=False)
    op.create_index('ix_execution_trace_events_run_parent', 'execution_trace_events', ['run_id', 'parent_span_id'], unique=False)
    op.create_index('ix_execution_trace_events_run_seq', 'execution_trace_events', ['run_id', 'seq'], unique=False)
    op.create_index('ix_execution_trace_events_span', 'execution_trace_events', ['span_id'], unique=False)
    op.create_table('human_approvals',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('checkpoint_trigger', sa.VARCHAR(), nullable=False),
    sa.Column('status', sa.VARCHAR(), nullable=True),
    sa.Column('requested_by', sa.VARCHAR(), nullable=True),
    sa.Column('responded_by', sa.UUID(), nullable=True),
    sa.Column('context_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('reviewer_notes', sa.TEXT(), nullable=True),
    sa.Column('notification_channels', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('timeout_ms', sa.INTEGER(), nullable=True),
    sa.Column('requested_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('responded_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('consumed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name='human_approvals_pkey')
    )
    op.create_index('ix_human_approvals_company_status', 'human_approvals', ['company_id', 'status'], unique=False)
    op.create_index('ix_human_approvals_run_id', 'human_approvals', ['run_id'], unique=False)
    op.create_table('lead_queue',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('lead_id', sa.VARCHAR(length=255), nullable=False),
    sa.Column('phone', sa.VARCHAR(length=20), nullable=False),
    sa.Column('lead_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('ad_source', sa.VARCHAR(length=100), nullable=True),
    sa.Column('project_id', sa.VARCHAR(length=100), nullable=True),
    sa.Column('status', sa.VARCHAR(length=20), server_default=sa.text("'pending'::character varying"), nullable=False),
    sa.Column('priority', sa.INTEGER(), server_default=sa.text('5'), nullable=False),
    sa.Column('attempt_count', sa.INTEGER(), server_default=sa.text('0'), nullable=False),
    sa.Column('max_attempts', sa.INTEGER(), server_default=sa.text('3'), nullable=False),
    sa.Column('last_error', sa.TEXT(), nullable=True),
    sa.Column('correlation_id', sa.VARCHAR(length=100), nullable=True),
    sa.Column('voice_session_id', sa.UUID(), nullable=True),
    sa.Column('call_outcome', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('processed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name='lead_queue_pkey'),
    sa.UniqueConstraint('company_id', 'lead_id', name='uq_lead_queue_company_lead')
    )
    op.create_index('idx_lead_queue_pending', 'lead_queue', ['company_id', 'status', 'priority', 'created_at'], unique=False, postgresql_where="((status)::text = 'pending'::text)")
    op.create_index('idx_lead_queue_voice_session', 'lead_queue', ['voice_session_id'], unique=False)
    op.create_table('llm_interaction_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('model_provider', sa.VARCHAR(), nullable=False),
    sa.Column('model_name', sa.VARCHAR(), nullable=False),
    sa.Column('input_prompt', sa.TEXT(), nullable=False),
    sa.Column('output_response', sa.TEXT(), nullable=False),
    sa.Column('prompt_tokens', sa.INTEGER(), nullable=True),
    sa.Column('completion_tokens', sa.INTEGER(), nullable=True),
    sa.Column('latency_ms', sa.INTEGER(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('cost_usd', sa.NUMERIC(precision=10, scale=6), nullable=True),
    sa.Column('reasoning_mode', sa.VARCHAR(), nullable=True),
    sa.Column('log_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('step_name', sa.VARCHAR(), nullable=True),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id', name='llm_interaction_logs_pkey')
    )
    op.create_index('ix_llm_interaction_logs_company_created', 'llm_interaction_logs', ['company_id', 'created_at'], unique=False)
    op.create_index('ix_llm_interaction_logs_run_id', 'llm_interaction_logs', ['run_id'], unique=False)
    op.create_table('mobile_campaign_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('campaign_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('device_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.VARCHAR(length=20), nullable=False),
    sa.Column('dial_order', sa.VARCHAR(length=20), nullable=False),
    sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('ended_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name='mobile_campaign_runs_pkey')
    )
    op.create_index('ix_mobile_campaign_runs_campaign_id', 'mobile_campaign_runs', ['campaign_id'], unique=False)
    op.create_index('ix_mobile_campaign_runs_company_id', 'mobile_campaign_runs', ['company_id'], unique=False)
    op.create_index('uq_mobile_run_running_per_device', 'mobile_campaign_runs', ['device_id'], unique=True, postgresql_where="status IN ('running', 'paused')")
    op.create_table('run_subjects',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.VARCHAR(length=20), nullable=False),
    sa.Column('value', sa.TEXT(), nullable=False),
    sa.Column('label', sa.TEXT(), nullable=True),
    sa.Column('source', sa.VARCHAR(length=40), nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name='run_subjects_pkey'),
    sa.UniqueConstraint('run_id', 'kind', 'value', name='uq_run_subjects_value')
    )
    op.create_index('ix_run_subjects_run_id', 'run_subjects', ['run_id'], unique=False)
    op.create_table('tool_interaction_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('tool_id', sa.VARCHAR(), nullable=False),
    sa.Column('tool_name', sa.VARCHAR(), nullable=False),
    sa.Column('provider', sa.VARCHAR(), nullable=True),
    sa.Column('input_parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('output_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('success', sa.BOOLEAN(), nullable=True),
    sa.Column('error_message', sa.TEXT(), nullable=True),
    sa.Column('latency_ms', sa.INTEGER(), nullable=True),
    sa.Column('log_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('idempotency_key', sa.VARCHAR(length=255), nullable=True),
    sa.Column('step_name', sa.VARCHAR(length=100), nullable=True),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id', name='tool_interaction_logs_pkey')
    )
    op.create_index('idx_tool_logs_idemp', 'tool_interaction_logs', ['idempotency_key'], unique=False, postgresql_where='(idempotency_key IS NOT NULL)')
    op.create_index('ix_tool_interaction_logs_company_created', 'tool_interaction_logs', ['company_id', 'created_at'], unique=False)
    op.create_index('ix_tool_interaction_logs_run_id', 'tool_interaction_logs', ['run_id'], unique=False)
    op.create_table('trigger_firings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('trigger_id', sa.UUID(), nullable=False),
    sa.Column('event_id', sa.UUID(), nullable=True),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('decided_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('outcome', sa.TEXT(), nullable=False),
    sa.Column('reason', sa.TEXT(), nullable=True),
    sa.CheckConstraint("outcome = ANY (ARRAY['started'::text, 'queued'::text, 'skipped_overlap'::text, 'skipped_rate'::text, 'skipped_chain_depth'::text, 'skipped_condition_false'::text, 'skipped_missed'::text, 'blocked_budget'::text, 'blocked_paused'::text, 'blocked_policy'::text, 'failed'::text])", name='ck_trigger_firings_outcome'),
    sa.PrimaryKeyConstraint('id', name='trigger_firings_pkey'),
    sa.UniqueConstraint('trigger_id', 'event_id', name='uq_trigger_firings_trigger_event')
    )
    op.create_index('ix_trigger_firings_event', 'trigger_firings', ['event_id'], unique=False)
    op.create_index('ix_trigger_firings_trigger_decided', 'trigger_firings', ['trigger_id', 'decided_at'], unique=False)
    op.create_table('call_content',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('call_log_id', sa.UUID(), nullable=False),
    sa.Column('transcript_text', sa.TEXT(), nullable=True),
    sa.Column('summary_text', sa.TEXT(), nullable=True),
    sa.Column('sentiment', sa.VARCHAR(length=20), nullable=True),
    sa.Column('content_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('audio_artifact_id', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('id', name='call_content_pkey')
    )
    op.create_index('idx_call_content_call_log', 'call_content', ['call_log_id'], unique=False)
    op.create_table('mobile_call_attempts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('campaign_id', sa.UUID(), nullable=False),
    sa.Column('campaign_call_id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('device_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('device_cli', sa.VARCHAR(length=20), nullable=True),
    sa.Column('did', sa.VARCHAR(length=20), nullable=False),
    sa.Column('dtmf_token', sa.VARCHAR(length=8), nullable=False),
    sa.Column('dial_order', sa.VARCHAR(length=20), nullable=False),
    sa.Column('status', sa.VARCHAR(length=30), nullable=False),
    sa.Column('identification_method', sa.VARCHAR(length=20), nullable=True),
    sa.Column('identification_conflict', sa.BOOLEAN(), nullable=False),
    sa.Column('assisted', sa.BOOLEAN(), nullable=False),
    sa.Column('voice_session_id', sa.UUID(), nullable=True),
    sa.Column('expires_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('ai_answered_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('ai_ready_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('lead_dialed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('lead_answered_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('merged_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('ended_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('lead_failure_cause', sa.VARCHAR(length=30), nullable=True),
    sa.Column('end_reason', sa.VARCHAR(length=50), nullable=True),
    sa.Column('lead_ring_seconds', sa.INTEGER(), nullable=True),
    sa.Column('conversation_seconds', sa.INTEGER(), nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name='mobile_call_attempts_pkey')
    )
    op.create_index('ix_attempt_cli_lookup', 'mobile_call_attempts', ['device_cli', 'did'], unique=False, postgresql_where="status IN ('pending', 'ai_connected')")
    op.create_index('ix_mobile_call_attempts_campaign_call_id', 'mobile_call_attempts', ['campaign_call_id'], unique=False)
    op.create_index('ix_mobile_call_attempts_campaign_id', 'mobile_call_attempts', ['campaign_id'], unique=False)
    op.create_index('ix_mobile_call_attempts_company_id', 'mobile_call_attempts', ['company_id'], unique=False)
    op.create_index('ix_mobile_call_attempts_run_id', 'mobile_call_attempts', ['run_id'], unique=False)
    op.create_index('ix_mobile_call_attempts_user_id', 'mobile_call_attempts', ['user_id'], unique=False)
    op.create_index('ix_mobile_call_attempts_voice_session_id', 'mobile_call_attempts', ['voice_session_id'], unique=False)
    op.create_index('uq_attempt_open_per_device', 'mobile_call_attempts', ['device_id'], unique=True, postgresql_where="status IN ('pending', 'ai_connected', 'ai_ready', 'unidentified_ready', 'merged')")
    op.create_index('uq_attempt_token_open', 'mobile_call_attempts', ['did', 'dtmf_token'], unique=True, postgresql_where="status IN ('pending', 'ai_connected', 'ai_ready', 'unidentified_ready', 'merged')")
    op.create_table('mobile_call_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('attempt_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.INTEGER(), nullable=False),
    sa.Column('type', sa.VARCHAR(length=40), nullable=False),
    sa.Column('device_ts', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('elapsed_ms', sa.INTEGER(), nullable=True),
    sa.Column('received_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id', name='mobile_call_events_pkey')
    )
    op.create_index('uq_event_seq', 'mobile_call_events', ['attempt_id', 'seq'], unique=True)
    for name, table, referred, columns, referred_columns, ondelete in FOREIGN_KEYS:
        op.create_foreign_key(name, table, referred, columns, referred_columns, ondelete=ondelete)
    op.execute(KPI_DAILY_ROLLUP)
    op.execute(KPI_DAILY_ROLLUP_INDEX)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS kpi_daily_rollup")
    for name, table, *_ in reversed(FOREIGN_KEYS):
        op.drop_constraint(name, table, type_="foreignkey")
    for table in ('mobile_call_events', 'mobile_call_attempts', 'call_content', 'trigger_firings', 'tool_interaction_logs', 'run_subjects', 'mobile_campaign_runs', 'llm_interaction_logs', 'lead_queue', 'human_approvals', 'execution_trace_events', 'campaign_calls', 'campaign_assignees', 'artifacts', 'whatsapp_sessions', 'voice_sessions', 'triggers', 'execution_runs', 'entity_assets', 'documents', 'cortex_edges', 'conversation_history', 'campaigns', 'call_logs', 'waits', 'social_connections', 'schema_changes', 'schema_blueprints', 'records_settings', 'mobile_client_logs', 'hierarchical_entities', 'events', 'entity_versions', 'email_connections', 'cortex_trees', 'cortex_nodes', 'contact_uploads', 'audit_log', 'api_keys'):
        op.drop_table(table)
    for name in ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {name}")

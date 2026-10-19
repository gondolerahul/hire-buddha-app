"""Webhook endpoints run their agents through triggers (Phase 14 WS3 3.9).

Revision ID: p14_webhook_triggers
Revises: p14_automation
Create Date: 2026-10-18

Inbound webhooks now become events routed by triggers (``automation.gateway``).
So that no business sees a change, each active endpoint gets the trigger that
reproduces what ran its events before:

* an endpoint bound to an agent → a trigger for that agent;
* an unbound endpoint of a business with exactly one active top-level agent
  (the old "company's only agent" fallback) → a trigger for that agent, for
  events that do not name an agent themselves (those get their own visible
  trigger the first time they arrive).

Triggers are ``created_by_kind = 'system'``, scope ``webhooks``, ``event_type
'*'`` with the endpoint as subject; the owner sees them in the Control Room.
Data only, on the shared database (single tenancy mode); a business already
on its own database is migrated by the tenant tree (WS2 2.7).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "p14_webhook_triggers"
down_revision: Union[str, Sequence[str], None] = "p14_automation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOT_YET = """NOT EXISTS (SELECT 1 FROM triggers t WHERE t.company_id = e.company_id
              AND t.created_by_kind = 'system' AND t.scope = 'webhooks'
              AND t.filter::text LIKE '%' || 'webhook:' || e.id::text || '%')"""

_COLUMNS = """(id, company_id, name, kind, enabled, entity_id, input_template, event_type, filter, scope,
               created_by_kind, firings, version, created_at, updated_at)"""


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO triggers {_COLUMNS}
        SELECT gen_random_uuid(), e.company_id, left('Webhook: ' || e.name, 200), 'event', true, e.entity_id,
               '{{}}'::jsonb, '*',
               jsonb_build_object('path', 'subject', 'op', 'eq', 'value', 'webhook:' || e.id::text),
               'webhooks', 'system', 0, 1, coalesce(e.created_at, now()), now()
        FROM webhook_endpoints e
        JOIN hierarchical_entities h ON h.id = e.entity_id AND h.status <> 'DELETED'
        WHERE e.is_active AND e.entity_id IS NOT NULL AND {_NOT_YET}
    """)
    op.execute(f"""
        WITH only_agent AS (
            SELECT company_id, (array_agg(id ORDER BY created_at, id))[1] AS entity_id, count(*) AS agents
            FROM hierarchical_entities
            WHERE status = 'ACTIVE' AND is_template IS NOT TRUE AND deleted_at IS NULL AND parent_id IS NULL
            GROUP BY company_id
        )
        INSERT INTO triggers {_COLUMNS}
        SELECT gen_random_uuid(), e.company_id, left('Webhook: ' || e.name || ' (the only agent)', 200), 'event',
               true, o.entity_id, '{{}}'::jsonb, '*',
               jsonb_build_object('all', jsonb_build_array(
                   jsonb_build_object('path', 'subject', 'op', 'eq', 'value', 'webhook:' || e.id::text),
                   jsonb_build_object('path', 'data._gateway.entity_id', 'op', 'exists', 'value', false))),
               'webhooks', 'system', 0, 1, coalesce(e.created_at, now()), now()
        FROM webhook_endpoints e
        JOIN only_agent o ON o.company_id = e.company_id AND o.agents = 1
        WHERE e.is_active AND e.entity_id IS NULL AND {_NOT_YET}
    """)


def downgrade() -> None:
    op.execute("DELETE FROM triggers WHERE created_by_kind = 'system' AND scope = 'webhooks'")

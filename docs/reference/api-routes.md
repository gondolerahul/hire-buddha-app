# API routes — every route the app serves

> Generated from the app by `python scripts/route_census.py --write` (run from `backend/`); `backend/tests/unit/test_route_census.py` fails when a route is added, moved or removed without regenerating it.
> Moved here from the Phase 13 API reference (`docs/history/phase13/17-api-reference.md` §24, frozen); the prose reference for each area lives with its phase's documents.

<!-- route-census:start -->

| Method | Path | Guard | Module |
|---|---|---|---|
| GET | `/` | — | `src.main` |
| GET | `/api/social-connections` *(deprecated)* | signed in | `src.ai.social_router` |
| POST | `/api/social-connections` *(deprecated)* | signed in | `src.ai.social_router` |
| DELETE | `/api/social-connections/{connection_id}` *(deprecated)* | signed in | `src.ai.social_router` |
| POST | `/api/social-connections/{connection_id}/refresh` *(deprecated)* | signed in | `src.ai.social_router` |
| GET | `/api/v1/admin/automation/limits` | signed in | `src.automation.api` |
| PUT | `/api/v1/admin/automation/limits` | signed in | `src.automation.api` |
| POST | `/api/v1/admin/automation/pause` | signed in | `src.automation.api` |
| POST | `/api/v1/admin/automation/resume` | signed in | `src.automation.api` |
| GET | `/api/v1/admin/connectors` | roles: app_admin | `src.connections.api` |
| PATCH | `/api/v1/admin/connectors/{connector_id}` | roles: app_admin | `src.connections.api` |
| GET | `/api/v1/admin/tenant-servers` | roles: app_admin | `src.common.tenancy.api` |
| GET | `/api/v1/admin/tenants` | roles: app_admin | `src.common.tenancy.api` |
| POST | `/api/v1/admin/tenants` | roles: app_admin | `src.common.tenancy.api` |
| GET | `/api/v1/admin/tenants/{company_id}` | roles: app_admin | `src.common.tenancy.api` |
| POST | `/api/v1/admin/tenants/{company_id}/provision` | roles: app_admin | `src.common.tenancy.api` |
| GET | `/api/v1/admin/unrouted-events` | roles: app_admin | `src.connections.api` |
| GET | `/api/v1/ai/admin/admin/decisions` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| POST | `/api/v1/ai/admin/admin/decisions` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/admin/exit_checklist` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/admin/kpi/cost` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/admin/kpi/critic` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/admin/kpi/meta_agent` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/admin/kpi/runs` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/admin/risks` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| POST | `/api/v1/ai/admin/admin/tools/{tool_id}/experimental` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/companies/{company_id}/cost_attribution` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/entities/{entity_id}/bandit_state` | signed in | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/executions/{run_id}/cost_attribution` | signed in | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/executions/{run_id}/health_records` | signed in | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/executions/{run_id}/plan_candidates` | signed in | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/feature_flags/admin` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/feature_flags/explain` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| POST | `/api/v1/ai/admin/feature_flags/invalidate` | roles: app_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/feature_flags/me` | signed in | `src.ai.api.admin` |
| DELETE | `/api/v1/ai/admin/feature_flags/{flag_key}` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| PUT | `/api/v1/ai/admin/feature_flags/{flag_key}` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| POST | `/api/v1/ai/admin/meta/entities/{entity_id}/promote` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/meta/intelligence/anti_patterns` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/meta/intelligence/prompt_candidates` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| POST | `/api/v1/ai/admin/meta/intelligence/prompt_candidates/{node_id}/approve` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/meta/review_queue` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/admin/meta/skill_candidates` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| POST | `/api/v1/ai/admin/meta/skill_candidates/{node_id}/promote` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| POST | `/api/v1/ai/admin/meta/spec_critic` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.admin` |
| GET | `/api/v1/ai/approvals/pending` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/approvals/{approval_id}/respond` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/avatar/upload` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/context-sources/upload` | signed in | `src.ai.router` |
| GET | `/api/v1/ai/documents` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/documents/search` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/documents/upload` | signed in | `src.ai.router` |
| DELETE | `/api/v1/ai/documents/{document_id}` | signed in | `src.ai.router` |
| GET | `/api/v1/ai/documents/{document_id}` | signed in | `src.ai.router` |
| PATCH | `/api/v1/ai/documents/{document_id}` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/documents/{document_id}/file` | signed in | `src.ai.router` |
| GET | `/api/v1/ai/entities` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/entities` | signed in | `src.ai.router` |
| DELETE | `/api/v1/ai/entities/{entity_id}` | signed in | `src.ai.router` |
| GET | `/api/v1/ai/entities/{entity_id}` | signed in | `src.ai.router` |
| PUT | `/api/v1/ai/entities/{entity_id}` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/entities/{entity_id}/convert-to-template` | roles: app_admin | `src.ai.router` |
| GET | `/api/v1/ai/entities/{entity_id}/versions` | signed in | `src.ai.api.versions` |
| POST | `/api/v1/ai/entities/{entity_id}/versions` | signed in | `src.ai.api.versions` |
| GET | `/api/v1/ai/entities/{entity_id}/versions/{version_id}` | signed in | `src.ai.api.versions` |
| DELETE | `/api/v1/ai/entities/{entity_id}/versions/{version_id}/assets/{path:path}` | signed in | `src.ai.api.versions` |
| GET | `/api/v1/ai/entities/{entity_id}/versions/{version_id}/assets/{path:path}` | signed in | `src.ai.api.versions` |
| PUT | `/api/v1/ai/entities/{entity_id}/versions/{version_id}/assets/{path:path}` | signed in | `src.ai.api.versions` |
| POST | `/api/v1/ai/entities/{entity_id}/versions/{version_id}/publish` | roles: app_admin, partner_admin, tenant_admin | `src.ai.api.versions` |
| POST | `/api/v1/ai/entities/{entity_id}/versions/{version_id}/test-run` | signed in | `src.ai.api.versions` |
| POST | `/api/v1/ai/execute` | signed in | `src.ai.router` |
| GET | `/api/v1/ai/executions` | signed in | `src.ai.router` |
| GET | `/api/v1/ai/executions/{execution_id}` | signed in | `src.ai.router` |
| GET | `/api/v1/ai/executions/{execution_id}/agent_state` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/executions/{execution_id}/cancel` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/executions/{execution_id}/csat` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/executions/{execution_id}/refine` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/executions/{execution_id}/retry` | signed in | `src.ai.router` |
| GET | `/api/v1/ai/executions/{execution_id}/stream` | URL token | `src.ai.router` |
| GET | `/api/v1/ai/executions/{execution_id}/trace` | signed in | `src.ai.router` |
| GET | `/api/v1/ai/stats` | signed in | `src.ai.router` |
| GET | `/api/v1/ai/templates` | signed in | `src.ai.router` |
| POST | `/api/v1/ai/templates` | roles: app_admin | `src.ai.router` |
| DELETE | `/api/v1/ai/templates/{template_id}` | roles: app_admin | `src.ai.router` |
| GET | `/api/v1/ai/templates/{template_id}` | signed in | `src.ai.router` |
| PUT | `/api/v1/ai/templates/{template_id}` | roles: app_admin | `src.ai.router` |
| POST | `/api/v1/ai/templates/{template_id}/clone` | signed in | `src.ai.router` |
| GET | `/api/v1/ai/tool-registry` | signed in | `src.ai.tool_management_router` |
| POST | `/api/v1/ai/tool-registry` | roles: app_admin | `src.ai.tool_management_router` |
| POST | `/api/v1/ai/tool-registry/sync-built-in` | roles: app_admin | `src.ai.tool_management_router` |
| DELETE | `/api/v1/ai/tool-registry/{tool_id}` | roles: app_admin | `src.ai.tool_management_router` |
| GET | `/api/v1/ai/tool-registry/{tool_id}` | signed in | `src.ai.tool_management_router` |
| PUT | `/api/v1/ai/tool-registry/{tool_id}` | roles: app_admin | `src.ai.tool_management_router` |
| POST | `/api/v1/ai/tool-registry/{tool_id}/toggle` | roles: app_admin | `src.ai.tool_management_router` |
| GET | `/api/v1/app-templates` | signed in | `src.apps.api` |
| GET | `/api/v1/apps` | signed in | `src.apps.api` |
| POST | `/api/v1/apps` | signed in | `src.apps.api` |
| DELETE | `/api/v1/apps/{app_id}` | signed in | `src.apps.api` |
| GET | `/api/v1/apps/{app_id}` | signed in | `src.apps.api` |
| PATCH | `/api/v1/apps/{app_id}` | signed in | `src.apps.api` |
| POST | `/api/v1/apps/{app_id}/actions/{action}` | signed in | `src.apps.api` |
| GET | `/api/v1/apps/{app_id}/builds` | signed in | `src.apps.api` |
| POST | `/api/v1/apps/{app_id}/builds` | signed in | `src.apps.api` |
| GET | `/api/v1/apps/{app_id}/builds/{build_id}/log` | signed in | `src.apps.api` |
| GET | `/api/v1/apps/{app_id}/deployments` | signed in | `src.apps.api` |
| GET | `/api/v1/apps/{app_id}/domains` | signed in | `src.apps.api` |
| POST | `/api/v1/apps/{app_id}/domains` | signed in | `src.apps.api` |
| DELETE | `/api/v1/apps/{app_id}/domains/{hostname}` | signed in | `src.apps.api` |
| POST | `/api/v1/apps/{app_id}/domains/{hostname}/verify` | signed in | `src.apps.api` |
| GET | `/api/v1/apps/{app_id}/logs` | signed in | `src.apps.api` |
| GET | `/api/v1/apps/{app_id}/metrics` | signed in | `src.apps.api` |
| POST | `/api/v1/apps/{app_id}/preview` | signed in | `src.apps.api` |
| POST | `/api/v1/apps/{app_id}/publish` | signed in | `src.apps.api` |
| GET | `/api/v1/apps/{app_id}/roles` | signed in | `src.apps.api` |
| PUT | `/api/v1/apps/{app_id}/roles/{name}` | signed in | `src.apps.api` |
| DELETE | `/api/v1/apps/{app_id}/roles/{role_id}` | signed in | `src.apps.api` |
| POST | `/api/v1/apps/{app_id}/rollback` | signed in | `src.apps.api` |
| GET | `/api/v1/apps/{app_id}/status` | signed in | `src.apps.api` |
| GET | `/api/v1/apps/{app_id}/users` | signed in | `src.apps.api` |
| POST | `/api/v1/apps/{app_id}/users` | signed in | `src.apps.api` |
| DELETE | `/api/v1/apps/{app_id}/users/{app_user_id}` | signed in | `src.apps.api` |
| PATCH | `/api/v1/apps/{app_id}/users/{app_user_id}` | signed in | `src.apps.api` |
| POST | `/api/v1/apps/{app_id}/users/{app_user_id}/invite` | signed in | `src.apps.api` |
| GET | `/api/v1/artifacts` | signed in | `src.ai.artifact_router` |
| POST | `/api/v1/artifacts/upload` | signed in | `src.ai.artifact_router` |
| DELETE | `/api/v1/artifacts/{artifact_id}` | signed in | `src.ai.artifact_router` |
| GET | `/api/v1/artifacts/{artifact_id}` | signed in | `src.ai.artifact_router` |
| GET | `/api/v1/artifacts/{artifact_id}/download` | — | `src.ai.artifact_router` |
| POST | `/api/v1/auth/forgot-password` | — | `src.auth.router` |
| POST | `/api/v1/auth/login` | — | `src.auth.router` |
| POST | `/api/v1/auth/logout` | — | `src.auth.router` |
| GET | `/api/v1/auth/me` | signed in | `src.auth.router` |
| POST | `/api/v1/auth/oauth/{provider}` | — | `src.auth.router` |
| POST | `/api/v1/auth/refresh` | — | `src.auth.router` |
| POST | `/api/v1/auth/register` | — | `src.auth.router` |
| POST | `/api/v1/auth/resend-verification` | — | `src.auth.router` |
| POST | `/api/v1/auth/reset-password` | — | `src.auth.router` |
| POST | `/api/v1/auth/token` | — | `src.auth.router` |
| POST | `/api/v1/auth/url-token` | signed in | `src.auth.router` |
| GET | `/api/v1/auth/verify-email` | — | `src.auth.router` |
| GET | `/api/v1/automation/events` | signed in | `src.automation.control_room` |
| GET | `/api/v1/automation/events/{event_id}` | signed in | `src.automation.control_room` |
| POST | `/api/v1/automation/events/{event_id}/replay` | signed in | `src.automation.control_room` |
| GET | `/api/v1/automation/health` | signed in | `src.automation.control_room` |
| POST | `/api/v1/automation/pause` | signed in | `src.automation.api` |
| POST | `/api/v1/automation/resume` | signed in | `src.automation.api` |
| POST | `/api/v1/automation/scopes/{scope}/pause` | signed in | `src.automation.control_room` |
| POST | `/api/v1/automation/scopes/{scope}/resume` | signed in | `src.automation.control_room` |
| GET | `/api/v1/automation/settings` | signed in | `src.automation.api` |
| PUT | `/api/v1/automation/settings/limits` | signed in | `src.automation.api` |
| GET | `/api/v1/automation/triggers` | signed in | `src.automation.control_room` |
| POST | `/api/v1/automation/triggers` | signed in | `src.automation.control_room` |
| POST | `/api/v1/automation/triggers/preview` | signed in | `src.automation.control_room` |
| POST | `/api/v1/automation/triggers/test-filter` | signed in | `src.automation.control_room` |
| DELETE | `/api/v1/automation/triggers/{trigger_id}` | signed in | `src.automation.control_room` |
| GET | `/api/v1/automation/triggers/{trigger_id}` | signed in | `src.automation.control_room` |
| PATCH | `/api/v1/automation/triggers/{trigger_id}` | signed in | `src.automation.control_room` |
| GET | `/api/v1/automation/triggers/{trigger_id}/firings` | signed in | `src.automation.control_room` |
| POST | `/api/v1/automation/triggers/{trigger_id}/run` | signed in | `src.automation.control_room` |
| GET | `/api/v1/automation/waits` | signed in | `src.automation.control_room` |
| POST | `/api/v1/automation/waits/{wait_id}/cancel` | signed in | `src.automation.control_room` |
| GET | `/api/v1/billing/config` | roles: app_admin | `src.billing.billing_router` |
| PUT | `/api/v1/billing/config` | roles: app_admin | `src.billing.billing_router` |
| GET | `/api/v1/campaigns` | signed in | `src.ai.campaign_router` |
| POST | `/api/v1/campaigns` | signed in | `src.ai.campaign_router` |
| GET | `/api/v1/campaigns/interested/download` | signed in | `src.ai.campaign_router` |
| POST | `/api/v1/campaigns/retry-failed` | signed in | `src.ai.campaign_router` |
| POST | `/api/v1/campaigns/upload-contacts` | signed in | `src.ai.campaign_router` |
| POST | `/api/v1/campaigns/upload-csv` | signed in | `src.ai.campaign_router` |
| GET | `/api/v1/campaigns/{campaign_id}` | signed in | `src.ai.campaign_router` |
| GET | `/api/v1/campaigns/{campaign_id}/active-calls` | signed in | `src.ai.campaign_router` |
| GET | `/api/v1/campaigns/{campaign_id}/calls` | signed in | `src.mobile.analytics_router` |
| GET | `/api/v1/campaigns/{campaign_id}/download` | signed in | `src.ai.campaign_router` |
| GET | `/api/v1/campaigns/{campaign_id}/mobile-analytics` | signed in | `src.mobile.analytics_router` |
| GET | `/api/v1/campaigns/{campaign_id}/status` | signed in | `src.ai.campaign_router` |
| PATCH | `/api/v1/campaigns/{campaign_id}/status` | signed in | `src.ai.campaign_router` |
| GET | `/api/v1/code-items` | signed in | `src.apps.api` |
| GET | `/api/v1/code-items/{item_id}` | signed in | `src.apps.api` |
| POST | `/api/v1/code-items/{item_id}/promote` | signed in | `src.apps.api` |
| GET | `/api/v1/code-reviews` | signed in | `src.apps.api` |
| GET | `/api/v1/code-reviews/{review_id}` | signed in | `src.apps.api` |
| POST | `/api/v1/code-reviews/{review_id}/approve` | signed in | `src.apps.api` |
| POST | `/api/v1/code-reviews/{review_id}/checks` | signed in | `src.apps.api` |
| POST | `/api/v1/code-reviews/{review_id}/reject` | signed in | `src.apps.api` |
| GET | `/api/v1/companies` | signed in | `src.auth.company_router` |
| POST | `/api/v1/companies` | roles: app_admin, partner_admin | `src.auth.company_router` |
| GET | `/api/v1/companies/partners` | roles: app_admin | `src.auth.company_router` |
| GET | `/api/v1/companies/tenants` | roles: app_admin, partner_admin | `src.auth.company_router` |
| PATCH | `/api/v1/companies/{company_id}` | signed in | `src.auth.company_router` |
| GET | `/api/v1/config/integrations` | signed in | `src.config.router` |
| POST | `/api/v1/config/integrations` | signed in | `src.config.router` |
| DELETE | `/api/v1/config/integrations/{entry_id}` | signed in | `src.config.router` |
| GET | `/api/v1/config/integrations/{entry_id}` | signed in | `src.config.router` |
| PATCH | `/api/v1/config/integrations/{entry_id}` | signed in | `src.config.router` |
| GET | `/api/v1/config/models` | signed in | `src.config.router` |
| GET | `/api/v1/config/task-defaults` | roles: app_admin | `src.config.router` |
| POST | `/api/v1/config/task-defaults` | roles: app_admin | `src.config.router` |
| DELETE | `/api/v1/config/task-defaults/{task_type}` | roles: app_admin | `src.config.router` |
| GET | `/api/v1/config/task-types` | signed in | `src.config.router` |
| GET | `/api/v1/connections` | signed in | `src.connections.api` |
| POST | `/api/v1/connections/embedded-signup/complete` | signed in | `src.connections.api` |
| POST | `/api/v1/connections/form` | signed in | `src.connections.api` |
| GET | `/api/v1/connections/pending/{pending_id}` | signed in | `src.connections.api` |
| POST | `/api/v1/connections/pending/{pending_id}/finalize` | signed in | `src.connections.api` |
| POST | `/api/v1/connections/start` | signed in | `src.connections.api` |
| DELETE | `/api/v1/connections/{connection_id}` | signed in | `src.connections.api` |
| GET | `/api/v1/connections/{connection_id}` | signed in | `src.connections.api` |
| PUT | `/api/v1/connections/{connection_id}/grants` | signed in | `src.connections.api` |
| GET | `/api/v1/connections/{connection_id}/impact` | signed in | `src.connections.api` |
| POST | `/api/v1/connections/{connection_id}/reconnect` | signed in | `src.connections.api` |
| POST | `/api/v1/connections/{connection_id}/test` | signed in | `src.connections.api` |
| GET | `/api/v1/connectors` | signed in | `src.connections.api` |
| GET | `/api/v1/cortex/trees` | signed in | `src.ai.memory.cortex_router` |
| POST | `/api/v1/cortex/trees` | signed in | `src.ai.memory.cortex_router` |
| GET | `/api/v1/cortex/trees/{tree_id}` | signed in | `src.ai.memory.cortex_router` |
| POST | `/api/v1/cortex/trees/{tree_id}/checkpoint` | signed in | `src.ai.memory.cortex_router` |
| POST | `/api/v1/cortex/trees/{tree_id}/ingest` | signed in | `src.ai.memory.cortex_router` |
| POST | `/api/v1/cortex/trees/{tree_id}/navigate/{node_id}` | signed in | `src.ai.memory.cortex_router` |
| POST | `/api/v1/cortex/trees/{tree_id}/nodes` | signed in | `src.ai.memory.cortex_router` |
| GET | `/api/v1/cortex/trees/{tree_id}/nodes/{node_id}` | signed in | `src.ai.memory.cortex_router` |
| GET | `/api/v1/cortex/trees/{tree_id}/nodes/{node_id}/detail` | signed in | `src.ai.memory.cortex_router` |
| GET | `/api/v1/cortex/trees/{tree_id}/output` | signed in | `src.ai.memory.cortex_router` |
| POST | `/api/v1/cortex/trees/{tree_id}/recurse` | signed in | `src.ai.memory.cortex_router` |
| POST | `/api/v1/cortex/trees/{tree_id}/resume` | signed in | `src.ai.memory.cortex_router` |
| POST | `/api/v1/cortex/trees/{tree_id}/suspend` | signed in | `src.ai.memory.cortex_router` |
| GET | `/api/v1/credits/balance` | signed in | `src.billing.credits_router` |
| POST | `/api/v1/credits/razorpay/webhook` | — | `src.billing.razorpay_webhook` |
| GET | `/api/v1/credits/subscription-tiers` | signed in | `src.billing.credits_router` |
| POST | `/api/v1/credits/subscription-tiers` | roles: app_admin | `src.billing.credits_router` |
| DELETE | `/api/v1/credits/subscription-tiers/{tier_id}` | roles: app_admin | `src.billing.credits_router` |
| PUT | `/api/v1/credits/subscription-tiers/{tier_id}` | roles: app_admin | `src.billing.credits_router` |
| GET | `/api/v1/credits/subscriptions` | signed in | `src.billing.credits_router` |
| POST | `/api/v1/credits/subscriptions` | signed in | `src.billing.credits_router` |
| POST | `/api/v1/credits/subscriptions/verify` | signed in | `src.billing.credits_router` |
| DELETE | `/api/v1/credits/subscriptions/{subscription_id}` | signed in | `src.billing.credits_router` |
| POST | `/api/v1/credits/topup` | signed in | `src.billing.credits_router` |
| POST | `/api/v1/credits/topup/verify` | signed in | `src.billing.credits_router` |
| POST | `/api/v1/cron/daily-credits` | roles: app_admin | `src.billing.cron_router` |
| POST | `/api/v1/cron/monthly-billing` | roles: app_admin | `src.billing.cron_router` |
| GET | `/api/v1/data-keys` | signed in | `src.data_api.platform_router` |
| POST | `/api/v1/data-keys` | signed in | `src.data_api.platform_router` |
| DELETE | `/api/v1/data-keys/{key_id}` | signed in | `src.data_api.platform_router` |
| GET | `/api/v1/email/connections` | signed in | `src.ai.email_router` |
| POST | `/api/v1/email/connections` | signed in | `src.ai.email_router` |
| DELETE | `/api/v1/email/connections/{connection_id}` | signed in | `src.ai.email_router` |
| POST | `/api/v1/email/connections/{connection_id}/validate` | signed in | `src.ai.email_router` |
| GET | `/api/v1/email/provider-defaults` | signed in | `src.ai.email_router` |
| GET | `/api/v1/files/{artifact_id}` | — | `src.ai.artifact_router` |
| GET | `/api/v1/files/{artifact_id}/public` | — | `src.ai.artifact_router` |
| GET | `/api/v1/git/repos` | signed in | `src.apps.api` |
| POST | `/api/v1/git/repos` | signed in | `src.apps.api` |
| POST | `/api/v1/git/repos/{repo_id}/push-to-github` | signed in | `src.apps.api` |
| GET | `/api/v1/health` | — | `src.common.router_mounts` |
| POST | `/api/v1/messaging/send` | signed in | `src.voice.messaging_router` |
| POST | `/api/v1/messaging/send-template` | signed in | `src.voice.messaging_router` |
| GET | `/api/v1/mobile/agents` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/analytics/summary` | signed in | `src.mobile.analytics_router` |
| GET | `/api/v1/mobile/app-version` | — | `src.mobile.router` |
| POST | `/api/v1/mobile/call-attempts` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/call-attempts/{attempt_id}` | signed in | `src.mobile.router` |
| POST | `/api/v1/mobile/call-attempts/{attempt_id}/events` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/call-attempts/{attempt_id}/timeline` | signed in | `src.mobile.analytics_router` |
| GET | `/api/v1/mobile/callbacks` | signed in | `src.mobile.router` |
| PATCH | `/api/v1/mobile/campaign-calls/{campaign_call_id}/disposition` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/campaigns` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/campaigns/{campaign_id}` | signed in | `src.mobile.router` |
| PUT | `/api/v1/mobile/campaigns/{campaign_id}/assignees` | signed in | `src.mobile.router` |
| POST | `/api/v1/mobile/campaigns/{campaign_id}/runs` | signed in | `src.mobile.router` |
| POST | `/api/v1/mobile/devices` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/devices/{device_id}` | signed in | `src.mobile.router` |
| POST | `/api/v1/mobile/devices/{device_id}/verification` | signed in | `src.mobile.router` |
| POST | `/api/v1/mobile/devices/{device_id}/verification/dialing` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/leads/lookup` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/logs` | signed in | `src.mobile.router` |
| POST | `/api/v1/mobile/logs` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/me` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/preflight` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/reps` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/runs/active` | signed in | `src.mobile.router` |
| PATCH | `/api/v1/mobile/runs/{run_id}` | signed in | `src.mobile.router` |
| POST | `/api/v1/mobile/runs/{run_id}/next` | signed in | `src.mobile.router` |
| GET | `/api/v1/mobile/uploads/recent` | signed in | `src.mobile.router` |
| GET | `/api/v1/notifications` | signed in | `src.notifications.router` |
| POST | `/api/v1/notifications/read-all` | signed in | `src.notifications.router` |
| POST | `/api/v1/notifications/{notification_id}/read` | signed in | `src.notifications.router` |
| POST | `/api/v1/onboarding/complete` | signed in | `src.auth.onboarding_router` |
| POST | `/api/v1/onboarding/skip` | signed in | `src.auth.onboarding_router` |
| GET | `/api/v1/onboarding/status` | signed in | `src.auth.onboarding_router` |
| POST | `/api/v1/onboarding/step/{step_name}` | signed in | `src.auth.onboarding_router` |
| GET | `/api/v1/partner/analytics/summary` | roles: app_admin, partner_admin | `src.auth.partner_router` |
| GET | `/api/v1/partner/tenants` | roles: app_admin, partner_admin | `src.auth.partner_router` |
| GET | `/api/v1/partner/tenants/{tenant_id}/details` | roles: app_admin, partner_admin | `src.auth.partner_router` |
| GET | `/api/v1/phone-numbers` | signed in | `src.voice.phone_number_router` |
| POST | `/api/v1/phone-numbers` | signed in | `src.voice.phone_number_router` |
| POST | `/api/v1/phone-numbers/bulk` | roles: app_admin | `src.voice.phone_number_router` |
| POST | `/api/v1/phone-numbers/sync` | roles: app_admin | `src.voice.phone_number_router` |
| DELETE | `/api/v1/phone-numbers/{number_id}` | signed in | `src.voice.phone_number_router` |
| GET | `/api/v1/phone-numbers/{number_id}` | signed in | `src.voice.phone_number_router` |
| PATCH | `/api/v1/phone-numbers/{number_id}` | signed in | `src.voice.phone_number_router` |
| POST | `/api/v1/phone-numbers/{number_id}/assign` | signed in | `src.voice.phone_number_router` |
| POST | `/api/v1/phone-numbers/{number_id}/claim` | signed in | `src.voice.phone_number_router` |
| POST | `/api/v1/phone-numbers/{number_id}/release` | signed in | `src.voice.phone_number_router` |
| POST | `/api/v1/profile/avatar` | signed in | `src.auth.profile_router` |
| POST | `/api/v1/profile/company-logo` | signed in | `src.auth.profile_router` |
| GET | `/api/v1/records/settings` | signed in | `src.data_api.platform_router` |
| PUT | `/api/v1/records/settings` | signed in | `src.data_api.platform_router` |
| POST | `/api/v1/records/token` | signed in | `src.data_api.platform_router` |
| GET | `/api/v1/reports/analytics/agent-errors` | signed in | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/campaign-analytics` | signed in | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/credit-forecast` | signed in | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/data-growth` | roles: app_admin, app_user | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/entity-versions` | signed in | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/execution-health` | signed in | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/hitl-overview` | signed in | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/llm-performance` | signed in | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/partner-performance` | roles: app_admin | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/personal-tasks` | signed in | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/subscription-mrr` | roles: app_admin | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/tenant-health` | roles: app_admin, partner_admin, partner_user | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/tool-efficacy` | signed in | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/usage-breakdown` | signed in | `src.ai.reports_router` |
| GET | `/api/v1/reports/analytics/wallet-liability` | roles: app_admin | `src.ai.reports_router` |
| GET | `/api/v1/reports/billing` | roles: app_admin | `src.billing.billing_router` |
| GET | `/api/v1/reports/costing` | roles: app_admin | `src.billing.billing_router` |
| GET | `/api/v1/social-connections` | signed in | `src.ai.social_router` |
| POST | `/api/v1/social-connections` | signed in | `src.ai.social_router` |
| DELETE | `/api/v1/social-connections/{connection_id}` | signed in | `src.ai.social_router` |
| POST | `/api/v1/social-connections/{connection_id}/refresh` | signed in | `src.ai.social_router` |
| GET | `/api/v1/streaming/conversation-history` | signed in | `src.voice.sessions_router` |
| GET | `/api/v1/streaming/stats` | signed in | `src.voice.sessions_router` |
| GET | `/api/v1/streaming/voice-sessions` | signed in | `src.voice.sessions_router` |
| GET | `/api/v1/streaming/voice-sessions/{session_id}` | signed in | `src.voice.sessions_router` |
| PATCH | `/api/v1/streaming/voice-sessions/{session_id}/next-action` | signed in | `src.voice.sessions_router` |
| GET | `/api/v1/streaming/whatsapp-sessions` | signed in | `src.voice.sessions_router` |
| GET | `/api/v1/streaming/whatsapp-sessions/{session_id}` | signed in | `src.voice.sessions_router` |
| GET | `/api/v1/users` | signed in | `src.auth.user_router` |
| POST | `/api/v1/users` | roles: app_admin, partner_admin, tenant_admin | `src.auth.user_router` |
| PATCH | `/api/v1/users/{user_id}` | signed in | `src.auth.user_router` |
| GET | `/api/v1/webhook-endpoints` | roles: app_admin, partner_admin, tenant_admin | `src.gateway.webhook_endpoints_router` |
| POST | `/api/v1/webhook-endpoints` | roles: app_admin, partner_admin, tenant_admin | `src.gateway.webhook_endpoints_router` |
| DELETE | `/api/v1/webhook-endpoints/{endpoint_id}` | roles: app_admin, partner_admin, tenant_admin | `src.gateway.webhook_endpoints_router` |
| GET | `/api/v1/workspace` | signed in | `src.common.tenancy.api` |
| GET | `/health` | — | `src.common.router_mounts` |
| POST | `/internal/event` | internal token | `src.gateway.internal_event` |
| GET | `/internal/v1/edge/ask` | — | `src.apps.api` |
| POST | `/internal/v1/tokens` | internal token | `src.connections.api` |
| GET | `/metrics/gateway` | — | `src.gateway.status` |
| WS | `/mobile/ws` | own handshake | `src.mobile.push_gateway` |
| GET | `/oauth/callback/{provider}` | — | `src.connections.api` |
| WS | `/stream/audio` | own handshake | `src.gateway.audio_gateway` |
| WS | `/stream/tata/{company_id}/{session_id}` | own handshake | `src.gateway.telephony_streams` |
| WS | `/stream/tata/{session_id}` | own handshake | `src.gateway.telephony_streams` |
| WS | `/stream/twilio/{company_id}/{session_id}` | own handshake | `src.gateway.telephony_streams` |
| WS | `/stream/twilio/{session_id}` | own handshake | `src.gateway.telephony_streams` |
| WS | `/stream/video` | own handshake | `src.gateway.video_gateway` |
| POST | `/webhook/inbound` | — | `src.gateway.webhook_inbound` |
| POST | `/webhook/inbound/{endpoint_id}` | — | `src.gateway.webhook_inbound` |
| POST | `/webhook/provider/github` | — | `src.connections.webhooks` |
| GET | `/webhook/provider/meta` | — | `src.connections.webhooks` |
| POST | `/webhook/provider/meta` | — | `src.connections.webhooks` |
| GET | `/webhooks/voice/tata/incoming` | — | `src.voice.webhook_router` |
| POST | `/webhooks/voice/tata/incoming` | — | `src.voice.webhook_router` |
| WS | `/webhooks/voice/tata/incoming` | own handshake | `src.gateway.telephony_streams` |
| GET | `/webhooks/voice/tata/status` | — | `src.voice.webhook_router` |
| POST | `/webhooks/voice/tata/status` | — | `src.voice.webhook_router` |
| POST | `/webhooks/voice/tata/whatsapp/incoming` | — | `src.voice.webhook_router` |
| POST | `/webhooks/voice/twilio/incoming` | — | `src.voice.webhook_router` |
| POST | `/webhooks/voice/twilio/outbound-twiml` | — | `src.voice.webhook_router` |
| POST | `/webhooks/voice/twilio/status` | — | `src.voice.webhook_router` |
| POST | `/webhooks/voice/whatsapp/incoming` | — | `src.voice.webhook_router` |

<!-- route-census:end -->

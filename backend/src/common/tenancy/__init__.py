"""The tenant data plane (Phase 14 WS2, tech spec §5.3, §6).

Each tenant's data lives in its own database (decision D38); the control
database holds what every tenant shares and the directory that says where
each tenant's database is.

* ``bases`` — ``ControlBase`` / ``TenantBase``: which plane each table is on;
* ``models`` — the control tables of the tenant directory and server registry;
* ``directory`` — ``TenantDirectory``: company → tenant database (cached);
* ``engines`` — one engine per tenant database, least recently used closed;
* ``session`` — ``control_session()``, ``tenant_session(company_id)`` and the
  FastAPI dependencies ``get_control_db`` / ``get_tenant_db``;
* ``migrate`` — the migration runner CLI.

``TENANCY_MODE=single`` (the default) keeps today's single database: both
kinds of session open on it.
"""

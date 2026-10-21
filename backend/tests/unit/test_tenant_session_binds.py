"""A split-mode session sends every statement on a control table to the control
database (Phase 14 M2-3).

On Azure dev in split mode the credit admission gate's
``pg_insert(CreditHold.__table__)`` failed with "relation credit_holds does not
exist": a statement built on the table names no mapped class, and the session
was bound by declarative base only, so it fell to the default — the tenant
database. Control tables are bound to the control engine too.
"""
from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select, update


def _session():
    from src.common.tenancy import session as tenancy_session
    from src.common.tenancy.directory import TenantLocation

    location = TenantLocation(company_id=uuid.uuid4(), key="abc0123456", server_host="localhost",
                              db_name="t_abc0123456", status="active", schema_version=None,
                              automation_state="running", timezone="UTC")
    return tenancy_session._tenant_factory(location)()


def test_statements_on_control_tables_go_to_the_control_database():
    from src.ai.orm.execution import ExecutionRun
    from src.billing.billing_models import CreditHold
    from src.common import database

    db = _session()
    sync = db.sync_session
    control = database.engine.sync_engine
    tenant = db.bind.sync_engine
    assert tenant is not control
    # Built on the table (the gate's insert, claim_settlement's upsert): control.
    assert sync.get_bind(clause=pg_insert(CreditHold.__table__).values(amount=0)) is control
    assert sync.get_bind(clause=select(CreditHold.__table__)) is control
    # Built on the class: control, as before.
    assert sync.get_bind(mapper=CreditHold) is control
    assert sync.get_bind(clause=update(CreditHold).values(amount=0)) is control
    # Tenant tables stay on the tenant database, by class and by table.
    assert sync.get_bind(mapper=ExecutionRun) is tenant
    assert sync.get_bind(clause=pg_insert(ExecutionRun.__table__)) is tenant


def test_every_control_table_is_bound():
    from src.common import database
    from src.common.tenancy.bases import CONTROL, plane_tables
    from src.common.tenancy.session import control_tables

    tables = control_tables()
    assert set(tables) == set(plane_tables(CONTROL)) and len(tables) > 20
    db = _session()
    assert all(db.sync_session.get_bind(clause=select(t)) is database.engine.sync_engine for t in tables)

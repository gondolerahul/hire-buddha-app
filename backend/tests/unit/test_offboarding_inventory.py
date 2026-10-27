"""Erasure reaches every table that refers to a company (docs/phase15/13 §3: "a test fails when a new
table or resource with a company reference is not in it").

The purge walk (``src.offboarding.purge``) finds a company's rows through a ``company_id`` column,
a foreign key to ``companies`` (or to a table it deletes), or a declared cross-plane reference. A
column that names a company any other way — a bare ``tenant_id`` with no key, say — would be left
behind. This census fails on one until it is given a key, a reference marker, or explicit handling
below. It also checks the tables Flow A keeps exist, and that nothing it keeps is a business's data.
"""
from __future__ import annotations

from src.common.orm_models import import_all_models
from src.offboarding.steps import KEYLESS_REFERENCES, RETAINED_TABLES

COMPANY_COLUMNS = ("company_id", "tenant_id", "partner_id", "origin_partner_id", "recruiter_partner_id",
                   "target_company_id", "acting_company_id", "app_id")
# Columns the steps handle themselves, and why.
HANDLED = {
    ("admin_audit_log", "target_company_id"): "anonymised (Flow A) or deleted (Flow B) by the control step",
    ("admin_audit_log", "acting_company_id"): "same",
    ("company_offboardings", "company_id"): "the proof of erasure: outlives the company by design",
}
HANDLED.update({(table, column): "deleted by the control step (no foreign key)"
                for table, columns in KEYLESS_REFERENCES for column in columns})
# A business's own data: never among the tables Flow A keeps.
BUSINESS_DATA = {"users", "voice_sessions", "call_logs", "documents", "hierarchical_entities", "execution_runs",
                 "usage_logs", "billing_lines", "lead_queue", "campaigns", "contact_uploads", "notifications"}


def _tables():
    tables = {}
    for metadata in import_all_models():
        tables.update({t.name: t for t in metadata.tables.values()})
    return tables


def test_every_company_reference_is_reachable_by_erasure():
    from src.common.tenancy.bases import cross_plane_references

    refs = {(r.table, r.column) for r in cross_plane_references()}
    unreachable = []
    for name, table in _tables().items():
        for column in table.columns:
            if column.name not in COMPANY_COLUMNS or column.name == "company_id":
                continue
            keyed = any(fk.column.table.name == "companies" for fk in column.foreign_keys)
            if keyed or (name, column.name) in refs or (name, column.name) in HANDLED:
                continue
            if column.name == "app_id" and not any("compan" in str(fk.target_fullname) for fk in column.foreign_keys):
                continue          # an app's own id, not a company
            unreachable.append(f"{name}.{column.name}")
    assert unreachable == []


def test_the_books_flow_a_keeps_exist_and_hold_no_business_data():
    tables = _tables()
    assert sorted(RETAINED_TABLES - set(tables)) == []
    assert sorted(RETAINED_TABLES & BUSINESS_DATA) == []
